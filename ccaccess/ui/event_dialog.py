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

DATE_FMT = "%d/%m/%Y"
TIME_FMT = "%H:%M"
ALARM_PRESETS = [None, 0, 5, 10, 15, 30, 60, 120, 1440, 2880, 10080]


class EventDialog(QDialog):
    """Crea o edita un evento. Fechas como dd/mm/aaaa y horas como hh:mm (campos de texto)."""

    def __init__(self, parent=None, event: Event | None = None, calendars: list[Calendar] | None = None):
        super().__init__(parent)
        self._editing = event is not None
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
            ("A&viso:", self.alarm),
            ("D&escripción:", self.description),
        ]
        for text, widget in rows:
            lab = QLabel(text)
            lab.setBuddy(widget)
            if widget is self.start_date:
                form.addRow(self.all_day)
            form.addRow(lab, widget)

        self.recurring_note = QLabel(
            "Este evento se repite. Los cambios de título, lugar y descripción afectan "
            "a toda la serie. Las fechas y horas no se pueden cambiar desde aquí."
        )
        self.recurring_note.setWordWrap(True)
        self.recurring_note.setVisible(event.recurring)

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
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        rec = self._base.recurring
        for w in (self.all_day, self.start_date, self.end_date):
            w.setEnabled(not rec)
        for w in (self.start_time, self.end_time):
            w.setEnabled(not rec and not self.all_day.isChecked())

    def _fail(self, msg: str, widget) -> None:
        QMessageBox.warning(self, "Datos incorrectos", msg)
        widget.setFocus()

    def _parse(self) -> Event | None:
        if not self.title.text().strip():
            self._fail("Falta el título del evento.", self.title)
            return None
        if self._base.recurring:
            return replace(
                self._base,
                summary=self.title.text().strip(),
                location=self.location.text().strip(),
                description=self.description.toPlainText().strip(),
                alarm=self.alarm.currentData(),
            )
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
