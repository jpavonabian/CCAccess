from dataclasses import replace
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ccaccess.caldav_client import Calendar, Event, alarm_label
from ccaccess.recurrence import (
    RepeatSpec,
    build_rrule,
    days_text,
    describe_rrule,
    parse_days,
    parse_rrule,
    style_of,
)

DATE_FMT = "%d/%m/%Y"
TIME_FMT = "%H:%M"
REPEAT_CHOICES = [
    ("No se repite", ""),
    ("Cada día", "DAILY"),
    ("Cada semana", "WEEKLY"),
    ("Cada mes", "MONTHLY"),
    ("Cada año", "YEARLY"),
]
ALARM_PRESETS = [None, 0, 5, 10, 15, 30, 60, 120, 1440, 2880, 10080]


class EventDialog(QDialog):
    """Crea o edita un evento. Fechas como dd/mm/aaaa y horas como hh:mm (campos de texto)."""

    def __init__(
        self,
        parent=None,
        event: Event | None = None,
        calendars: list[Calendar] | None = None,
        scope: str = "",
    ):
        """`scope` solo importa en eventos repetidos: «this», «following» o «series»."""
        super().__init__(parent)
        self._editing = event is not None
        self._scope = scope if event is not None and event.recurring else ""
        self._calendars = calendars or []
        if event is None:
            start = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            event = Event("", "", start, start + timedelta(hours=1), False)
        self._base = event
        self.setWindowTitle("Editar evento" if self._editing else "Nuevo evento")
        self.setMinimumWidth(480)

        self.title = QLineEdit(event.summary)
        self.cal = QComboBox()
        for c in self._calendars:
            self.cal.addItem(c.name, c)
        if self._editing:
            self.cal.setEnabled(False)
            idx = self.cal.findText(event.calendar)
            if idx >= 0:
                self.cal.setCurrentIndex(idx)

        self.all_day = QCheckBox("Todo el &día")
        self.all_day.setChecked(event.all_day)
        end_shown = event.end - timedelta(days=1) if event.all_day else event.end
        self.start_date = QLineEdit(event.start.strftime(DATE_FMT))
        self.start_time = QLineEdit(event.start.strftime(TIME_FMT))
        self.end_date = QLineEdit(end_shown.strftime(DATE_FMT))
        self.end_time = QLineEdit(event.end.strftime(TIME_FMT))
        self.location = QLineEdit(event.location)
        self._build_repeat(event)
        self.alarm = QComboBox()
        presets = list(ALARM_PRESETS)
        if event.alarm not in presets:
            presets.append(event.alarm)  # aviso del servidor que no está en la lista
            presets.sort(key=lambda m: -1 if m is None else m)
        for m in presets:
            self.alarm.addItem(alarm_label(m), m)
        self.alarm.setCurrentIndex(self.alarm.findData(event.alarm))
        self.description = QPlainTextEdit(event.description)
        self.description.setTabChangesFocus(True)
        for w, name in (
            (self.start_date, "Fecha de inicio, formato día barra mes barra año"),
            (self.start_time, "Hora de inicio, formato horas dos puntos minutos"),
            (self.end_date, "Fecha de fin, formato día barra mes barra año"),
            (self.end_time, "Hora de fin, formato horas dos puntos minutos"),
        ):
            w.setAccessibleName(name)

        form = QFormLayout()
        rows = [("&Título:", self.title)]
        if not self._editing:
            rows.append(("&Calendario:", self.cal))
        rows += [
            ("Fecha de &inicio (dd/mm/aaaa):", self.start_date),
            ("&Hora de inicio (hh:mm):", self.start_time),
            ("Fecha de &fin (dd/mm/aaaa):", self.end_date),
            ("Hora de fi&n (hh:mm):", self.end_time),
            ("&Lugar:", self.location),
            ("Re&petir:", self.repeat),
            ("Interval&o (1 = cada vez, 2 = una de cada dos):", self.interval),
            ("Día&s de la semana (L M X J V S D):", self.days),
            ("Ter&mina el (dd/mm/aaaa, vacío = sin fecha):", self.until),
            ("Número de &veces (vacío = sin límite):", self.count),
            ("&Aviso:", self.alarm),
            ("D&escripción:", self.description),
        ]
        for text, widget in rows:
            lab = QLabel(text)
            lab.setBuddy(widget)
            if widget is self.start_date:
                form.addRow(self.all_day)
            form.addRow(lab, widget)

        self.recurring_note = QLabel(
            {
                "this": "Solo se cambia esta ocurrencia.",
                "following": "Los cambios afectan a esta ocurrencia y a las siguientes.",
                "series": "Los cambios afectan a toda la serie. Si cambias la fecha o la hora, se mueve la serie entera.",
            }.get(self._scope, "")
        )
        self.recurring_note.setWordWrap(True)
        self.recurring_note.setVisible(bool(self._scope))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("&Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.recurring_note)
        lay.addLayout(form)
        lay.addWidget(buttons)

        self.all_day.toggled.connect(self._sync_enabled)
        self.repeat.currentIndexChanged.connect(self._sync_enabled)
        self._sync_enabled()

    def _build_repeat(self, event: Event) -> None:
        self.repeat = QComboBox()
        for text, data in REPEAT_CHOICES:
            self.repeat.addItem(text, data)
        self.interval = QLineEdit("1")
        self.days = QLineEdit()
        self.until = QLineEdit()
        self.count = QLineEdit()
        start = event.occ_start or event.start
        spec = parse_rrule(event.rrule, start)
        if spec is not None:
            self.repeat.setCurrentIndex(self.repeat.findData(spec.freq))
            self.interval.setText(str(spec.interval))
            self.days.setText(days_text(spec.days))
            self.until.setText(spec.until.strftime(DATE_FMT) if spec.until else "")
            self.count.setText(str(spec.count) if spec.count else "")
        elif event.rrule:  # regla que la app no sabe editar: se conserva tal cual
            self.repeat.addItem(describe_rrule(event.rrule, start), "CUSTOM")
            self.repeat.setCurrentIndex(self.repeat.count() - 1)
        for w, name in (
            (self.interval, "Intervalo de repetición, 1 es cada vez y 2 es una de cada dos"),
            (self.days, "Días de la semana, letras L M X J V S D separadas por espacios"),
            (self.until, "Fecha de fin de la repetición, formato día barra mes barra año"),
            (self.count, "Número de veces que se repite"),
        ):
            w.setAccessibleName(name)

    def _sync_enabled(self) -> None:
        for w in (self.start_time, self.end_time):
            w.setEnabled(not self.all_day.isChecked())
        freq = self.repeat.currentData()
        simple = self._scope != "this" and freq in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
        self.repeat.setEnabled(self._scope != "this")
        for w in (self.interval, self.until, self.count):
            w.setEnabled(simple)
        self.days.setEnabled(simple and freq == "WEEKLY")

    def _repeat_rule(self, all_day: bool, start: datetime) -> str | None:
        """RRULE resultante de los campos de repetición; None si hay un error (ya avisado)."""
        base = self._base
        data = self.repeat.currentData()
        if self._scope == "this" or data == "CUSTOM":
            return base.rrule
        if not data:
            return ""
        try:
            interval = int(self.interval.text().strip() or "1")
            if interval < 1:
                raise ValueError
        except ValueError:
            self._fail("El intervalo debe ser un número entero de 1 en adelante.", self.interval)
            return None
        days = ()
        if data == "WEEKLY":
            days = parse_days(self.days.text())
            if days is None:
                self._fail("Los días no son válidos. Usa letras L M X J V S D, por ejemplo L X.", self.days)
                return None
        until_text, count_text = self.until.text().strip(), self.count.text().strip()
        if until_text and count_text:
            self._fail("Indica una fecha de fin o un número de veces, no las dos cosas.", self.until)
            return None
        until = count = None
        if until_text:
            try:
                until = datetime.strptime(until_text, DATE_FMT).date()
            except ValueError:
                self._fail("La fecha de fin no es válida. Usa dd/mm/aaaa, por ejemplo 31/12/2026.", self.until)
                return None
            if until < start.date():
                self._fail("La repetición no puede terminar antes de empezar.", self.until)
                return None
        if count_text:
            try:
                count = int(count_text)
                if count < 1:
                    raise ValueError
            except ValueError:
                self._fail("El número de veces debe ser un entero de 1 en adelante.", self.count)
                return None
        spec = RepeatSpec(data, interval, days, until, count)
        if spec == parse_rrule(base.rrule, base.occ_start or base.start):
            return base.rrule  # sin cambios: no se reescribe la regla original
        key = base.occ_key
        style = "date" if all_day else (style_of(key) if isinstance(key, datetime) else "utc")
        return build_rrule(spec, style)

    def _fail(self, msg: str, widget) -> None:
        QMessageBox.warning(self, "Datos incorrectos", msg)
        widget.setFocus()

    def _parse(self) -> Event | None:
        if not self.title.text().strip():
            self._fail("Falta el título del evento.", self.title)
            return None
        all_day = self.all_day.isChecked()
        try:
            sd = datetime.strptime(self.start_date.text().strip(), DATE_FMT)
        except ValueError:
            self._fail("La fecha de inicio no es válida. Usa dd/mm/aaaa, por ejemplo 25/12/2026.", self.start_date)
            return None
        try:
            ed = datetime.strptime(self.end_date.text().strip(), DATE_FMT)
        except ValueError:
            self._fail("La fecha de fin no es válida. Usa dd/mm/aaaa, por ejemplo 25/12/2026.", self.end_date)
            return None
        if all_day:
            start, end = sd, ed + timedelta(days=1)
        else:
            try:
                st = datetime.strptime(self.start_time.text().strip(), TIME_FMT).time()
            except ValueError:
                self._fail("La hora de inicio no es válida. Usa hh:mm, por ejemplo 09:30.", self.start_time)
                return None
            try:
                et = datetime.strptime(self.end_time.text().strip(), TIME_FMT).time()
            except ValueError:
                self._fail("La hora de fin no es válida. Usa hh:mm, por ejemplo 10:30.", self.end_time)
                return None
            start, end = datetime.combine(sd.date(), st), datetime.combine(ed.date(), et)
        if end < start or (all_day and end <= start):
            self._fail("El fin no puede ser anterior al inicio.", self.end_date)
            return None
        cal_name = self.cal.currentText() if self.cal.count() else self._base.calendar
        rule = self._repeat_rule(all_day, start)
        if rule is None:
            return None
        return replace(
            self._base,
            summary=self.title.text().strip(),
            start=start,
            end=end,
            all_day=all_day,
            location=self.location.text().strip(),
            description=self.description.toPlainText().strip(),
            calendar=cal_name,
            alarm=self.alarm.currentData(),
            rrule=rule,
            scope=self._scope,
        )

    def _validate(self) -> None:
        ev = self._parse()
        if ev is not None:
            self._result = ev
            self.accept()

    def result_event(self) -> Event:
        return self._result

    def calendar(self) -> Calendar | None:
        return self.cal.currentData() if self.cal.count() else None
