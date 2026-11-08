from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QLocale, QTimer
from ccaccess.ui.dialogs import EnterButton, make_readonly_navigable
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ccaccess.caldav_client import CalDavClient, Calendar, Event, alarm_label
from ccaccess.ui.announce import announce
from ccaccess.recurrence import describe_rrule
from ccaccess import exchange
from ccaccess.textutil import fold
from ccaccess.ui.dialogs import ask_choice, ask_scope, confirm, report_import
from ccaccess.reminders import ReminderTracker
from ccaccess.ui.event_dialog import DATE_FMT, EventDialog
from ccaccess.ui.reminder_dialog import DISMISS, SHOW, ask_reminder

EVENT_ROLE = 256  # Qt.UserRole
REMINDER_DAYS = 14  # cuántos días por delante se vigilan los avisos
RANGES = [("Próximos 7 días", 7), ("Próximos 30 días", 30), ("Próximos 90 días", 90)]


def day_title(d: datetime) -> str:
    return QLocale().toString(d.date(), "dddd d 'de' MMMM 'de' yyyy")


def event_line(ev: Event) -> str:
    if ev.all_day:
        return f"Todo el día: {ev.summary}"
    return f"{ev.start:%H:%M} a {ev.end:%H:%M}: {ev.summary}"


class CalendarTab(QWidget):
    """Vista de agenda: eventos agrupados por día. `run(fn, on_done)` ejecuta en segundo plano."""

    def __init__(self, run, say, run_silent=None):
        super().__init__()
        self._run = run
        self._run_silent = run_silent or run
        self._say = say
        self.reminders_enabled = True
        self._tracker = ReminderTracker()
        self._alarm_events: list[Event] = []
        self._showing_reminder = False
        self.base_date: date | None = None  # primer día de la agenda; None = hoy
        # Los avisos se vigilan aparte de la agenda visible, para no mover la selección.
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_reminders)
        self._check_timer.start(30_000)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_reminders)
        self._refresh_timer.start(10 * 60_000)
        self.client: CalDavClient | None = None
        self.calendars: list[Calendar] = []
        self.events: list[Event] = []

        self.cal_combo = QComboBox()
        self.cal_combo.currentIndexChanged.connect(self._refresh_tree)
        cal_label = QLabel("Ca&lendario:")
        cal_label.setBuddy(self.cal_combo)

        self.range_combo = QComboBox()
        for text, days in RANGES:
            self.range_combo.addItem(text, days)
        self.range_combo.setCurrentIndex(1)
        self.range_combo.currentIndexChanged.connect(self.reload)
        range_label = QLabel("&Periodo:")
        range_label.setBuddy(self.range_combo)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Escribe para filtrar")
        self.search.textChanged.connect(self._refresh_tree)
        search_label = QLabel("&Buscar evento:")
        search_label.setBuddy(self.search)

        self.goto_date = QLineEdit()
        self.goto_date.setAccessibleName("Fecha de inicio de la agenda, formato día barra mes barra año")
        self.goto_date.returnPressed.connect(self.go_to_date)
        goto_label = QLabel("Ir a la &fecha (dd/mm/aaaa):")
        goto_label.setBuddy(self.goto_date)
        self.btn_goto = EnterButton("&Ir")
        self.btn_today = EnterButton("&Hoy")
        self.btn_goto.clicked.connect(self.go_to_date)
        self.btn_today.clicked.connect(self.go_today)
        goto_row = QHBoxLayout()
        for w in (self.goto_date, self.btn_goto, self.btn_today):
            goto_row.addWidget(w)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Agenda")
        self.tree.currentItemChanged.connect(self._show_detail)
        tree_label = QLabel("&Agenda:")
        tree_label.setBuddy(self.tree)

        self.detail = QPlainTextEdit()
        make_readonly_navigable(self.detail)
        self.detail.setAccessibleName("Detalles del evento")
        detail_label = QLabel("&Detalles:")
        detail_label.setBuddy(self.detail)

        left = QWidget()
        ll = QVBoxLayout(left)
        for w in (cal_label, self.cal_combo, range_label, self.range_combo, search_label, self.search, goto_label):
            ll.addWidget(w)
        ll.addLayout(goto_row)
        for w in (tree_label, self.tree):
            ll.addWidget(w)
        self.btn_new = EnterButton("N&uevo…")
        self.btn_edit = EnterButton("&Editar…")
        self.btn_del = EnterButton("Eli&minar…")
        self.btn_new.clicked.connect(self.new_event)
        self.btn_edit.clicked.connect(self.edit_event)
        self.btn_del.clicked.connect(self.delete_event)
        self.tree.itemActivated.connect(lambda _item, _col: self.edit_event())
        row = QHBoxLayout()
        for b in (self.btn_new, self.btn_edit, self.btn_del):
            row.addWidget(b)
        ll.addLayout(row)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(detail_label)
        rl.addWidget(self.detail)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(split)

        self.setTabOrder(self.cal_combo, self.range_combo)
        self.setTabOrder(self.range_combo, self.search)
        self.setTabOrder(self.search, self.goto_date)
        self.setTabOrder(self.goto_date, self.btn_goto)
        self.setTabOrder(self.btn_goto, self.btn_today)
        self.setTabOrder(self.btn_today, self.tree)
        self.setTabOrder(self.tree, self.btn_new)
        self.setTabOrder(self.btn_new, self.btn_edit)
        self.setTabOrder(self.btn_edit, self.btn_del)
        self.setTabOrder(self.btn_del, self.detail)

    # --- carga ------------------------------------------------------------
    def set_calendars(self, client: CalDavClient, calendars: list[Calendar]) -> None:
        self.client = client
        self.calendars = calendars
        self.cal_combo.blockSignals(True)
        self.cal_combo.clear()
        self.cal_combo.addItem("Todos los calendarios", None)
        for c in calendars:
            self.cal_combo.addItem(c.name, c.url)
        self.cal_combo.blockSignals(False)
        self.reload()
        self.refresh_reminders()

    # --- avisos -----------------------------------------------------------
    def reset_reminders(self) -> None:
        self._alarm_events = []
        self._tracker = ReminderTracker()

    def refresh_reminders(self) -> None:
        """Descarga en segundo plano los eventos de los próximos días para vigilar sus avisos."""
        client, cals = self.client, list(self.calendars)
        if client is None or not cals or not self.reminders_enabled:
            return
        start = datetime.combine(datetime.now().date(), time.min).astimezone()
        end = start + timedelta(days=REMINDER_DAYS)

        def work() -> list[Event]:
            events: list[Event] = []
            for c in cals:
                events += client.fetch_events(c, start, end)
            return events

        def done(events: list[Event]) -> None:
            self._alarm_events = events
            self._check_reminders()

        self._run_silent(work, done)

    def _check_reminders(self) -> None:
        # exec() del aviso deja correr el temporizador: sin esto saldrían avisos apilados.
        if self._showing_reminder or not self.reminders_enabled:
            return
        self._showing_reminder = True
        try:
            while True:
                now = datetime.now()
                due = self._tracker.due(self._alarm_events, now)
                if not due:
                    break
                ev = due[0]
                action, minutes = ask_reminder(self.window(), ev, now)
                if action == DISMISS:
                    self._tracker.dismiss(ev)
                elif action == SHOW:
                    self._tracker.dismiss(ev)
                    self._show_event(ev)
                else:
                    self._tracker.snooze(ev, minutes, datetime.now())
        finally:
            self._showing_reminder = False

    def _show_event(self, ev: Event) -> None:
        """Lleva el foco a ese evento en la agenda, si está en el periodo que se muestra."""
        tabs = self.parentWidget()
        while tabs is not None and not hasattr(tabs, "setCurrentWidget"):
            tabs = tabs.parentWidget()
        if tabs is not None:
            tabs.setCurrentWidget(self)
        self.cal_combo.setCurrentIndex(0)  # «Todos los calendarios», para que no quede filtrado
        for i in range(self.tree.topLevelItemCount()):
            day = self.tree.topLevelItem(i)
            for j in range(day.childCount()):
                child = day.child(j)
                cur = child.data(0, EVENT_ROLE)
                if isinstance(cur, Event) and cur.uid == ev.uid and cur.start == ev.start:
                    self.tree.setCurrentItem(child)
                    self.tree.setFocus()
                    return
        self._say("El evento no está en el periodo mostrado. Amplía el periodo para verlo.")

    def reload(self) -> None:
        client = self.client
        if client is None or not self.calendars:
            return
        start = datetime.combine(self.base_date or datetime.now().date(), time.min).astimezone()
        end = start + timedelta(days=self.range_combo.currentData())
        cals = list(self.calendars)
        self._say("Cargando agenda…")

        def work() -> list[Event]:
            events: list[Event] = []
            for c in cals:
                events += client.fetch_events(c, start, end)
            events.sort(key=lambda e: (e.start, e.summary.casefold()))
            return events

        self._run(work, self._on_events)

    def _on_events(self, events: list[Event]) -> None:
        self.events = events
        self._refresh_tree()
        if self.base_date:
            last = self.base_date + timedelta(days=self.range_combo.currentData() - 1)
            self._say(f"{len(events)} eventos del {self.base_date:%d/%m/%Y} al {last:%d/%m/%Y}.")
        else:
            self._say(f"{len(events)} eventos en la agenda.")

    def go_to_date(self) -> None:
        text = self.goto_date.text().strip()
        if not text:
            return self.go_today()
        try:
            self.base_date = datetime.strptime(text, DATE_FMT).date()
        except ValueError:
            QMessageBox.warning(self, "Fecha no válida", "Usa dd/mm/aaaa, por ejemplo 25/12/2026.")
            self.goto_date.setFocus()
            return
        self.reload()

    def go_today(self) -> None:
        self.base_date = None
        self.goto_date.clear()
        self.reload()

    # --- vista ------------------------------------------------------------
    def _refresh_tree(self) -> None:
        cal_name = self.cal_combo.currentText() if self.cal_combo.currentData() else None
        query = fold(self.search.text().strip())
        self.tree.clear()
        self.detail.clear()
        days: dict = {}
        shown = 0
        for ev in self.events:
            if cal_name and ev.calendar != cal_name:
                continue
            if query and query not in fold(" ".join([ev.summary, ev.location, ev.description])):
                continue
            key = ev.start.date()
            if key not in days:
                item = QTreeWidgetItem([day_title(ev.start)])
                self.tree.addTopLevelItem(item)
                days[key] = item
            child = QTreeWidgetItem([event_line(ev)])
            child.setData(0, EVENT_ROLE, ev)
            days[key].addChild(child)
            shown += 1
        self.tree.expandAll()
        if shown:
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first)
        else:
            empty = QTreeWidgetItem(["Ningún evento coincide con la búsqueda." if query else "No hay eventos en este periodo."])
            self.tree.addTopLevelItem(empty)
            self.tree.setCurrentItem(empty)
        announce(self.tree, f"{shown} resultados" if query else f"{shown} eventos")

    def _show_detail(self, item: QTreeWidgetItem | None) -> None:
        ev = item.data(0, EVENT_ROLE) if item else None
        if not isinstance(ev, Event):
            self.detail.clear()
            return
        lines = [f"Título: {ev.summary}"]
        if ev.all_day:
            lines.append(f"Fecha: {day_title(ev.start)} (todo el día)")
        else:
            lines.append(f"Inicio: {day_title(ev.start)}, {ev.start:%H:%M}")
            lines.append(f"Fin: {day_title(ev.end)}, {ev.end:%H:%M}")
        if ev.location:
            lines.append(f"Lugar: {ev.location}")
        if ev.rrule:
            lines.append(f"Repetición: {describe_rrule(ev.rrule, ev.occ_start or ev.start)}")
        elif ev.recurring:
            lines.append("Repetición: en fechas concretas")
        if ev.is_exception:
            lines.append("Esta ocurrencia se ha cambiado respecto al resto de la serie.")
        if ev.alarm is not None:
            lines.append(f"Aviso: {alarm_label(ev.alarm)}")
        if ev.calendar:
            lines.append(f"Calendario: {ev.calendar}")
        if ev.description:
            lines.append(f"Descripción: {ev.description}")
        self.detail.setPlainText("\n".join(lines))

    # --- importar y exportar ---------------------------------------------------
    def _pick_calendar(self, title: str) -> Calendar | None:
        url = self.cal_combo.currentData()
        if url:
            return next((c for c in self.calendars if c.url == url), None)
        if len(self.calendars) == 1:
            return self.calendars[0]
        names = [c.name for c in self.calendars]
        name, ok = QInputDialog.getItem(self, title, "&Calendario de destino:", names, 0, False)
        return self.calendars[names.index(name)] if ok else None

    def import_events(self) -> None:
        client = self.client
        if client is None or not self.calendars:
            QMessageBox.information(self, "CCAccess", "Conecta primero con un calendario.")
            return
        cal = self._pick_calendar("Importar eventos")
        if cal is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar eventos", "", "Calendarios iCalendar (*.ics);;Todos los archivos (*)"
        )
        if not path:
            return
        try:
            items, ignored = exchange.split_icalendar(exchange.read_text(path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "CCAccess", f"No se pudo leer el archivo: {e}")
            return
        if not items:
            QMessageBox.warning(self, "CCAccess", "No se encontró ningún evento en el archivo.")
            return
        if not confirm(
            self,
            "Importar eventos",
            f"Se van a añadir {len(items)} eventos al calendario {cal.name}. "
            "Los que ya existan se omitirán. ¿Continuar?",
            "&Importar",
        ):
            return
        self._say(f"Importando {len(items)} eventos…")

        def done(result) -> None:
            report_import(self, self._say, result, "evento", "eventos")
            self.reload()
            self.refresh_reminders()

        self._run(lambda: exchange.import_events(client, cal, items, ignored), done)

    def export_events(self) -> None:
        client = self.client
        if client is None or not self.calendars:
            QMessageBox.information(self, "CCAccess", "Conecta primero con un calendario.")
            return
        item = self.tree.currentItem()
        current = item.data(0, EVENT_ROLE) if item else None
        url = self.cal_combo.currentData()
        cals = [c for c in self.calendars if c.url == url] if url else list(self.calendars)
        scope = "all"
        if isinstance(current, Event):
            scope = ask_choice(
                self,
                "Exportar eventos",
                "¿Qué quieres exportar?",
                [
                    ("&Evento seleccionado, con toda su serie", "one"),
                    ("&Todos los eventos del calendario" if len(cals) == 1 else "&Todos los eventos de todos los calendarios", "all"),
                ],
            )
            if scope is None:
                return
        stem = exchange.file_stem(current.summary, "evento") if scope == "one" else "agenda"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar eventos", f"{stem}.ics", "Calendarios iCalendar (*.ics)")
        if not path:
            return

        def write(raws: list[str]) -> int:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(exchange.merge_icalendars(raws))
            return len(raws)

        def done(n: int) -> None:
            self._say(f"{n} evento{'s' if n != 1 else ''} exportado{'s' if n != 1 else ''} a {path}.")

        def work() -> int:
            if scope == "one":
                return write([current.raw])
            raws: list[str] = []
            for c in cals:
                raws += client.fetch_raw(c)
            return write(raws)

        self._say("Exportando…")
        self._run(work, done)

    # --- CRUD ---------------------------------------------------------------
    def _current_event(self) -> Event | None:
        item = self.tree.currentItem()
        ev = item.data(0, EVENT_ROLE) if item else None
        if not isinstance(ev, Event):
            QMessageBox.information(self, "CCAccess", "Selecciona primero un evento.")
            return None
        return ev

    def _write(self, fn, done_msg: str) -> None:
        def finished(_result) -> None:
            self._say(done_msg)
            self.reload()
            self.refresh_reminders()

        self._say("Guardando…")
        self._run(fn, finished)

    def new_event(self) -> None:
        client = self.client
        if client is None or not self.calendars:
            QMessageBox.information(self, "CCAccess", "Conecta primero con un calendario.")
            return
        dlg = EventDialog(self, None, self.calendars)
        if dlg.exec():
            ev, cal = dlg.result_event(), dlg.calendar()
            self._write(lambda: client.save_event(cal, ev), f"Evento {ev.summary} creado.")

    def edit_event(self) -> None:
        client = self.client
        current = self._current_event()
        if client is None or current is None:
            return
        scope = ""
        if current.recurring:
            scope = ask_scope(
                self, "Editar evento repetido", f"{current.summary} se repite. ¿Qué quieres editar?"
            )
            if scope is None:
                return
        dlg = EventDialog(self, current, self.calendars, scope)
        if dlg.exec():
            ev = dlg.result_event()
            self._write(lambda: client.save_event(None, ev), f"Evento {ev.summary} guardado.")

    def delete_event(self) -> None:
        client = self.client
        current = self._current_event()
        if client is None or current is None:
            return
        scope = ""
        if current.recurring:
            scope = ask_scope(
                self,
                "Eliminar evento repetido",
                f"{current.summary} se repite. ¿Qué quieres eliminar del servidor? No se puede deshacer.",
                destructive=True,
            )
            if scope is None:
                return
        elif not confirm(
            self,
            "Eliminar evento",
            f"¿Eliminar el evento {current.summary} del servidor? No se puede deshacer.",
            "&Eliminar",
        ):
            return
        self._write(lambda: client.delete_event(current, scope), f"Evento {current.summary} eliminado.")
