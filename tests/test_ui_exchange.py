"""Búsqueda en la agenda, «ir a fecha» e importar/exportar desde la interfaz (Qt sin pantalla)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from ccaccess.caldav_client import Calendar, parse_events  # noqa: E402
from ccaccess.exchange import ImportResult  # noqa: E402
from ccaccess.ui import calendar_tab as ct_mod  # noqa: E402
from ccaccess.ui.calendar_tab import EVENT_ROLE, CalendarTab  # noqa: E402

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:a
DTSTART:20260310T100000
DTEND:20260310T110000
SUMMARY:Reunión con José
LOCATION:Sala Ñandú
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART:20260311T100000
DTEND:20260311T110000
SUMMARY:Dentista
DESCRIPTION:Revisión anual
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def messages(monkeypatch):
    shown = []
    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: shown.append(a[2])))
    return shown


class FakeClient:
    def __init__(self):
        self.imported = []

    def fetch_events(self, cal, start, end):
        return []

    def fetch_raw(self, cal):
        return [ICS]

    def import_event(self, cal, uid, ics):
        self.imported.append(uid)


@pytest.fixture
def tab(app, messages):
    said = []
    t = CalendarTab(lambda fn, done: done(fn()), said.append)
    t.said = said
    t.client = FakeClient()
    t.calendars = [Calendar("http://x/c/", "Mi calendario")]
    t.cal_combo.addItem("Todos los calendarios", None)
    t.events = parse_events(ICS, datetime(2026, 3, 1), datetime(2026, 4, 1), "Mi calendario", "/a.ics", '"1"')
    t.reminders_enabled = False
    t._refresh_tree()
    return t


def titles(tab):
    out = []
    for i in range(tab.tree.topLevelItemCount()):
        day = tab.tree.topLevelItem(i)
        out += [day.child(j).text(0) for j in range(day.childCount())] or [day.text(0)]
    return out


def test_search_ignores_case_and_accents_and_searches_all_fields(tab):
    assert len(titles(tab)) == 2
    tab.search.setText("jose")
    assert titles(tab) == ["10:00 a 11:00: Reunión con José"]
    tab.search.setText("NANDU")  # en el lugar, con ñ
    assert len(titles(tab)) == 1
    tab.search.setText("revision")  # en la descripción
    assert "Dentista" in titles(tab)[0]
    tab.search.setText("nada de esto")
    assert titles(tab) == ["Ningún evento coincide con la búsqueda."]
    tab.search.setText("")
    assert len(titles(tab)) == 2


def test_goto_date_and_today(tab, messages):
    loaded = []
    tab.reload = lambda: loaded.append(tab.base_date)
    tab.goto_date.setText("15/03/2026")
    tab.go_to_date()
    assert tab.base_date == date(2026, 3, 15) and loaded == [date(2026, 3, 15)]
    tab.goto_date.setText("31-12")
    tab.go_to_date()
    assert messages and tab.base_date == date(2026, 3, 15)  # sigue donde estaba
    tab.go_today()
    assert tab.base_date is None and tab.goto_date.text() == "" and loaded[-1] is None
    tab.goto_date.setText("")
    tab.go_to_date()  # vacío equivale a hoy
    assert tab.base_date is None


def test_goto_changes_the_loaded_window(app, messages):
    calls = []

    class Client(FakeClient):
        def fetch_events(self, cal, start, end):
            calls.append((start.date(), end.date()))
            return []

    t = CalendarTab(lambda fn, done: done(fn()), lambda s: None)
    t.reminders_enabled = False
    t.client, t.calendars = Client(), [Calendar("http://x/c/", "C")]
    t.range_combo.setCurrentIndex(0)  # 7 días
    calls.clear()
    t.goto_date.setText("01/02/2026")
    t.go_to_date()
    assert calls[-1] == (date(2026, 2, 1), date(2026, 2, 8))


def test_export_selected_event_and_all(tab, tmp_path, monkeypatch):
    out = tmp_path / "uno.ics"
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    monkeypatch.setattr(ct_mod, "ask_choice", lambda *a, **k: "one")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    tab.export_events()
    text = out.read_text(encoding="utf-8")
    assert "Reunión con José" in text and text.startswith("BEGIN:VCALENDAR")
    assert "exportado" in tab.said[-1]
    out_all = tmp_path / "todo.ics"
    monkeypatch.setattr(ct_mod, "ask_choice", lambda *a, **k: "all")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_all), "")))
    tab.export_events()
    assert out_all.read_text(encoding="utf-8").count("BEGIN:VEVENT") == 2


def test_export_cancelled_writes_nothing(tab, tmp_path, monkeypatch):
    def no_file_dialog(*a, **k):
        raise AssertionError("no debía abrirse el diálogo de archivo")

    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))  # con un evento seleccionado pregunta el alcance
    monkeypatch.setattr(ct_mod, "ask_choice", lambda *a, **k: None)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(no_file_dialog))
    tab.export_events()
    monkeypatch.setattr(ct_mod, "ask_choice", lambda *a, **k: "all")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    tab.export_events()
    assert list(tmp_path.iterdir()) == []


def test_import_events_flow(tab, tmp_path, monkeypatch):
    f = tmp_path / "in.ics"
    f.write_text(ICS, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(f), "")))
    monkeypatch.setattr(ct_mod, "confirm", lambda *a, **k: True)
    tab.reload = lambda: None
    tab.refresh_reminders = lambda: None
    tab.import_events()
    assert tab.client.imported == ["a", "b"]
    assert "Importados 2 eventos" in tab.said[-1]


def test_import_events_rejects_garbage_and_respects_cancel(tab, tmp_path, monkeypatch, messages):
    bad = tmp_path / "bad.ics"
    bad.write_text("esto no es un calendario", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    tab.import_events()
    assert messages and tab.client.imported == []
    f = tmp_path / "in.ics"
    f.write_text(ICS, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(f), "")))
    monkeypatch.setattr(ct_mod, "confirm", lambda *a, **k: False)
    tab.import_events()
    assert tab.client.imported == []


def test_import_report_warns_only_on_problems(app, monkeypatch):
    from ccaccess.ui.dialogs import report_import

    shown, said = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    report_import(None, said.append, ImportResult(created=2, existing=1), "evento", "eventos")
    assert not shown and "Importados 2 eventos" in said[-1]
    report_import(None, said.append, ImportResult(created=1, invalid=1), "evento", "eventos")
    assert shown and "no se pudo leer" in shown[0]


def test_event_roles_survive_search(tab):
    tab.search.setText("dentista")
    item = tab.tree.topLevelItem(0).child(0)
    assert item.data(0, EVENT_ROLE).uid == "b"


# --- contactos (ventana principal) ---------------------------------------------
VCF = """BEGIN:VCARD
VERSION:3.0
UID:u1
FN:José Pérez
EMAIL:jose@example.com
END:VCARD
BEGIN:VCARD
VERSION:3.0
UID:u2
FN:Luis Gómez
END:VCARD
"""


class FakeBookClient:
    def __init__(self):
        self.imported = []

    def import_contact(self, book, uid, text):
        self.imported.append(uid)


@pytest.fixture
def win(app, messages):
    from ccaccess.carddav import parse_vcard
    from ccaccess.ui.main_window import MainWindow

    w = MainWindow()
    w._run = lambda fn, done: done(fn())
    w.client = FakeBookClient()
    w.book_combo.addItem("Mis contactos", "http://x/book/")
    cards = [block + "END:VCARD\n" for block in VCF.split("END:VCARD\n") if block.strip()]
    w.contacts = [parse_vcard(f"/u{i}.vcf", text) for i, text in enumerate(cards, 1)]
    w._load_contacts = lambda: None
    w._refresh_list()
    return w


def test_contact_search_ignores_accents(win):
    win.search.setText("jose")
    assert win.list.count() == 1
    win.search.setText("gomez")
    assert win.list.count() == 1 and win.list.item(0).text() == "Luis Gómez"


def test_import_contacts_flow(win, tmp_path, monkeypatch):
    import ccaccess.ui.main_window as mw

    f = tmp_path / "c.vcf"
    f.write_text(VCF, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(f), "")))
    monkeypatch.setattr(mw, "confirm", lambda *a, **k: True)
    win.import_contacts()
    assert win.client.imported == ["u1", "u2"]
    assert "Importados 2 contactos" in win.statusBar().currentMessage()


def test_export_contacts_one_and_all(win, tmp_path, monkeypatch):
    import ccaccess.ui.main_window as mw

    win.search.setText("")
    win.list.setCurrentRow(0)
    one, every = tmp_path / "uno.vcf", tmp_path / "todos.vcf"
    monkeypatch.setattr(mw, "ask_choice", lambda *a, **k: "one")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(one), "")))
    win.export_contacts()
    assert one.read_text(encoding="utf-8").count("BEGIN:VCARD") == 1
    monkeypatch.setattr(mw, "ask_choice", lambda *a, **k: "all")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(every), "")))
    win.export_contacts()
    assert every.read_text(encoding="utf-8").count("BEGIN:VCARD") == 2
    assert "2 contactos exportados" in win.statusBar().currentMessage()


def test_menu_has_import_export_and_calendar_shortcuts(win):
    texts = [a.text() for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu())) for a in m.actions()]
    assert "&Importar…" in texts and "E&xportar…" in texts
    assert "Buscar e&vento" in texts and "Ir a &fecha del calendario" in texts
