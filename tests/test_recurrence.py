from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from zoneinfo import ZoneInfo

from ccaccess.caldav_client import build_ics, parse_events
from ccaccess.recurrence import (
    RepeatSpec,
    build_rrule,
    days_text,
    delete_following,
    delete_occurrence,
    describe,
    describe_rrule,
    edit_occurrence,
    edit_series,
    parse_days,
    parse_rrule,
    split_following,
)

START = datetime(2026, 3, 1)
END = datetime(2026, 5, 1)
T0 = datetime(2026, 3, 2, 9)  # lunes
MAD = ZoneInfo("Europe/Madrid")


def mad(dt: datetime) -> datetime:
    """Hora de pared en Madrid de una hora local de la máquina (los TZID se muestran en la zona local)."""
    return dt.astimezone(MAD).replace(tzinfo=None)

TZ_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:s1
DTSTART;TZID=Europe/Madrid:20260302T090000
DTEND;TZID=Europe/Madrid:20260302T100000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6
SUMMARY:Serie
LOCATION:Sala
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:x
TRIGGER:-PT10M
END:VALARM
END:VEVENT
END:VCALENDAR
"""

FLOAT_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:f1
DTSTART:20260302T180000
DTEND:20260302T190000
RRULE:FREQ=DAILY;COUNT=5
SUMMARY:Diario
END:VEVENT
END:VCALENDAR
"""

DAY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:d1
DTSTART;VALUE=DATE:20260302
DTEND;VALUE=DATE:20260303
RRULE:FREQ=WEEKLY;UNTIL=20260330
SUMMARY:Basura
END:VEVENT
END:VCALENDAR
"""

EXC_ICS = TZ_ICS.replace(
    "END:VCALENDAR\n",
    """BEGIN:VEVENT
UID:s1
RECURRENCE-ID;TZID=Europe/Madrid:20260309T090000
DTSTART;TZID=Europe/Madrid:20260309T140000
DTEND;TZID=Europe/Madrid:20260309T150000
SUMMARY:Movida
END:VEVENT
END:VCALENDAR
""",
)


def load(ics, uid=None, href="/x.ics"):
    return [e for e in parse_events(ics, START, END, "Cal", href, '"e1"') if uid in (None, e.uid)]


def starts(ics, uid=None):
    return [(e.start, e.summary) for e in load(ics, uid)]


# --- reglas ----------------------------------------------------------------
def test_parse_build_describe():
    spec = parse_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;UNTIL=20260630T215959Z", T0)
    assert spec == RepeatSpec("WEEKLY", 2, ("MO", "WE"), date(2026, 6, 30), None)
    assert describe(spec) == "Cada 2 semanas, los lunes y miércoles, hasta el 30/06/2026"
    assert parse_rrule(build_rrule(spec, "utc"), T0) == spec
    assert parse_rrule(build_rrule(spec, "floating"), T0) == spec
    assert "UNTIL=20260630;" in build_rrule(spec, "date") + ";"
    assert describe(RepeatSpec("DAILY")) == "Cada día"
    assert describe(RepeatSpec("MONTHLY", count=1)) == "Cada mes, 1 vez"
    assert describe(RepeatSpec("YEARLY", 3, count=4)) == "Cada 3 años, 4 veces"
    assert describe(RepeatSpec("WEEKLY", days=("MO", "TU", "SA"))) == "Cada semana, los lunes, martes y sábados"


def test_complex_rules_are_not_editable_but_described():
    for rule in (
        "FREQ=MONTHLY;BYDAY=1MO",
        "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
        "FREQ=HOURLY",
        "FREQ=WEEKLY;COUNT=3;UNTIL=20260401",
        "FREQ=MONTHLY;BYMONTHDAY=3",  # no coincide con el día de inicio (2)
        "FREQ=YEARLY;BYMONTH=5",
    ):
        assert parse_rrule(rule, T0) is None, rule
    assert describe_rrule("FREQ=MONTHLY;BYDAY=1MO", T0).startswith("Repetición personalizada")
    assert describe_rrule("", T0) == ""
    assert parse_rrule("FREQ=MONTHLY;BYMONTHDAY=2", T0) == RepeatSpec("MONTHLY")


def test_days_text_roundtrip():
    assert parse_days("L, X v") == ("MO", "WE", "FR")
    assert parse_days("lun mié") == ("MO", "WE")
    assert parse_days("") == ()
    assert parse_days("lunes pepe") is None
    assert days_text(("MO", "WE", "SU")) == "L X D"


# --- toda la serie ------------------------------------------------------------
def test_series_text_change_keeps_everything_else():
    ev = load(TZ_ICS)[0]
    out = edit_series(ev.raw, replace(ev, summary="Pilates"), ev.uid)
    assert [s for _, s in starts(out)] == ["Pilates"] * 6
    assert [d for d, _ in starts(out)] == [d for d, _ in starts(TZ_ICS)]
    assert "TZID=Europe/Madrid" in out and "BYDAY=MO,WE" in out and "TRIGGER:-PT10M" in out


def test_series_move_shifts_all_and_byday():
    ev = load(TZ_ICS)[0]  # lunes 2 de marzo 09:00
    moved = replace(ev, start=ev.start + timedelta(days=1, hours=2), end=ev.end + timedelta(days=1, hours=2))
    out = edit_series(ev.raw, moved, ev.uid)
    got = [d for d, _ in starts(out)]
    assert got[0] == ev.start + timedelta(days=1, hours=2)
    assert [mad(d).weekday() for d in got] == [1, 3, 1, 3, 1, 3]  # martes y jueves
    assert all(mad(d).hour == 11 for d in got)
    assert "BYDAY=TU,TH" in out and "COUNT=6" in out
    assert "TZID=Europe/Madrid" in out  # la zona de la serie se mantiene


def test_series_change_duration_only():
    ev = load(FLOAT_ICS)[0]
    out = edit_series(ev.raw, replace(ev, end=ev.end + timedelta(minutes=30)), ev.uid)
    assert all(e.end - e.start == timedelta(minutes=90) for e in load(out))
    assert len(load(out)) == 5


def test_series_change_rule_and_remove_rule():
    ev = load(FLOAT_ICS)[0]
    out = edit_series(ev.raw, replace(ev, rrule="FREQ=DAILY;INTERVAL=2;COUNT=3"), ev.uid)
    assert [d.day for d, _ in starts(out)] == [2, 4, 6]
    once = edit_series(ev.raw, replace(ev, rrule=""), ev.uid)
    assert len(load(once)) == 1 and "RRULE" not in once


def test_remove_rule_drops_exceptions():
    ev = load(EXC_ICS)[0]
    out = edit_series(ev.raw, replace(ev, rrule=""), ev.uid)
    assert len(load(out)) == 1 and "RECURRENCE-ID" not in out and "EXDATE" not in out


def test_all_day_series_move():
    ev = load(DAY_ICS)[0]
    moved = replace(ev, start=ev.start + timedelta(days=2), end=ev.end + timedelta(days=2))
    out = edit_series(ev.raw, moved, ev.uid)
    assert [d.date() for d, _ in starts(out)] == [date(2026, 3, d) for d in (4, 11, 18, 25)]
    assert all(e.all_day for e in load(out))


def test_series_to_timed():
    ev = load(DAY_ICS)[0]
    timed = replace(ev, all_day=False, start=datetime(2026, 3, 2, 8), end=datetime(2026, 3, 2, 9))
    out = edit_series(ev.raw, timed, ev.uid)
    got = load(out)
    assert not got[0].all_day and got[0].start == datetime(2026, 3, 2, 8) and len(got) == 5


# --- una ocurrencia -------------------------------------------------------------
def test_edit_one_occurrence():
    evs = load(TZ_ICS)
    ev = evs[2]  # lunes 9 de marzo
    assert not ev.is_exception
    new = replace(
        ev, scope="this", summary="Solo hoy", start=ev.start.replace(hour=16), end=ev.end.replace(hour=17)
    )
    out = edit_occurrence(ev.raw, new, ev.uid)
    got = load(out)
    assert [e.summary for e in got] == ["Serie", "Serie", "Solo hoy", "Serie", "Serie", "Serie"]
    assert got[2].start == ev.start.replace(hour=16) and got[2].is_exception
    assert got[0].start == evs[0].start and not got[0].is_exception
    assert out.count("BEGIN:VEVENT") == 2 and "RECURRENCE-ID" in out
    assert "TRIGGER:-PT10M" in out  # la excepción hereda el aviso
    again = edit_occurrence(out, replace(got[2], scope="this", summary="Otra vez"), ev.uid)
    assert again.count("BEGIN:VEVENT") == 2  # se edita la excepción, no se crea otra
    assert [e.summary for e in load(again)][2] == "Otra vez"


def test_edit_existing_exception_keeps_its_time():
    ev = [e for e in load(EXC_ICS) if e.is_exception][0]
    assert mad(ev.start) == datetime(2026, 3, 9, 14)
    out = edit_occurrence(ev.raw, replace(ev, scope="this", location="Otra sala"), ev.uid)
    got = [e for e in load(out) if e.is_exception][0]
    assert got.start == ev.start and got.location == "Otra sala"


def test_floating_and_all_day_occurrence():
    ev = load(FLOAT_ICS)[1]
    out = edit_occurrence(ev.raw, replace(ev, scope="this", summary="X"), ev.uid)
    assert [e.start.hour for e in load(out)] == [18] * 5 and load(out)[1].summary == "X"
    ev = load(DAY_ICS)[1]
    out = edit_occurrence(ev.raw, replace(ev, scope="this", summary="Y"), ev.uid)
    got = load(out)
    assert got[1].summary == "Y" and got[1].all_day and got[1].start.date() == date(2026, 3, 9)


def test_build_ics_dispatches_by_scope():
    ev = load(TZ_ICS)[2]
    assert build_ics(replace(ev, scope="this", summary="A"), ev.uid).count("BEGIN:VEVENT") == 2
    assert build_ics(replace(ev, summary="B"), ev.uid).count("BEGIN:VEVENT") == 1


def test_delete_occurrence():
    ev = load(TZ_ICS)[2]
    out = delete_occurrence(ev.raw, ev, ev.uid)
    got = [d for d, _ in starts(out)]
    assert len(got) == 5 and ev.start not in got and "EXDATE" in out
    # borrar una excepción quita su VEVENT y deja el hueco
    exc = [e for e in load(EXC_ICS) if e.is_exception][0]
    out = delete_occurrence(exc.raw, exc, exc.uid)
    assert "Movida" not in out and len(load(out)) == 5


def test_delete_occurrence_all_day_and_floating():
    for ics, idx in ((DAY_ICS, 1), (FLOAT_ICS, 2)):
        ev = load(ics)[idx]
        before = load(ics)
        after = load(delete_occurrence(ev.raw, ev, ev.uid))
        assert len(after) == len(before) - 1 and ev.start not in [e.start for e in after]


# --- esta y las siguientes ---------------------------------------------------------
def test_delete_following():
    ev = load(TZ_ICS)[3]  # miércoles 11 de marzo
    out = delete_following(ev.raw, ev, ev.uid)
    assert [d.date() for d, _ in starts(out)] == [date(2026, 3, 2), date(2026, 3, 4), date(2026, 3, 9)]
    assert "COUNT" not in out and "UNTIL" in out
    assert delete_following(ev.raw, load(TZ_ICS)[0], ev.uid) is None  # la primera: todo
    ev = load(DAY_ICS)[2]
    out = delete_following(ev.raw, ev, ev.uid)
    assert [d.day for d, _ in starts(out)] == [2, 9]


def test_delete_following_drops_later_exceptions():
    ev = load(EXC_ICS)[0]
    late = load(EXC_ICS)[3]
    out = delete_following(ev.raw, late, ev.uid)
    assert "Movida" in out  # la del 9 es anterior
    out = delete_following(ev.raw, load(EXC_ICS)[2], ev.uid)  # desde la excepción
    assert "Movida" not in out


def test_split_following_adjusts_count():
    ev = load(TZ_ICS)[3]  # 4.ª ocurrencia: quedan 3
    short, new = split_following(ev.raw, replace(ev, scope="following", summary="Nueva"), ev.uid, "n1")
    assert [d.date() for d, _ in starts(short)] == [date(2026, 3, 2), date(2026, 3, 4), date(2026, 3, 9)]
    got = load(new)
    assert [e.summary for e in got] == ["Nueva"] * 3 and got[0].uid == "n1"
    assert mad(got[0].start) == datetime(2026, 3, 11, 9)


def test_split_following_moved_and_new_rule():
    ev = load(TZ_ICS)[3]
    moved = replace(ev, scope="following", start=ev.start.replace(hour=18), end=ev.end.replace(hour=19),
                    rrule="FREQ=DAILY;COUNT=2")
    short, new = split_following(ev.raw, moved, ev.uid, "n2")
    got = load(new)
    assert [e.start for e in got] == [datetime(2026, 3, 11, 18), datetime(2026, 3, 12, 18)]
    assert mad(load(short)[-1].start) == datetime(2026, 3, 9, 9)
    assert split_following(ev.raw, replace(load(TZ_ICS)[0], scope="following"), ev.uid, "n3") is None


def test_new_event_with_rule():
    from ccaccess.caldav_client import Event

    ev = Event("", "Gimnasio", datetime(2026, 3, 3, 8), datetime(2026, 3, 3, 9), False,
               rrule=build_rrule(RepeatSpec("WEEKLY", days=("TU", "TH"), count=4), "utc"))
    got = load(build_ics(ev, "g1"))
    assert [d.day for d in (e.start for e in got)] == [3, 5, 10, 12]
    assert got[0].recurring and "BYDAY=TU,TH" in got[0].rrule


def test_add_rule_to_existing_single_event():
    single = FLOAT_ICS.replace("RRULE:FREQ=DAILY;COUNT=5\n", "")
    ev = load(single)[0]
    assert not ev.recurring
    out = build_ics(replace(ev, rrule="FREQ=DAILY;COUNT=3"), ev.uid)
    assert len(load(out)) == 3


@pytest.mark.parametrize("ics", [TZ_ICS, FLOAT_ICS, DAY_ICS, EXC_ICS])
def test_unchanged_series_edit_is_stable(ics):
    ev = load(ics)[0]
    out = edit_series(ev.raw, ev, ev.uid)
    assert starts(out) == starts(ics)
    assert parse_events(out, START, END)[0].rrule == ev.rrule
