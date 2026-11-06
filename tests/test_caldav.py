from datetime import datetime

from ccaccess.caldav_client import caldav_url_from, parse_events

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:one
DTSTART:20260701T100000
DTEND:20260701T110000
SUMMARY:Reunión
LOCATION:Sala 1
END:VEVENT
BEGIN:VEVENT
UID:weekly
DTSTART:20260701T180000
DTEND:20260701T190000
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Yoga
END:VEVENT
BEGIN:VEVENT
UID:allday
DTSTART;VALUE=DATE:20260703
DTEND;VALUE=DATE:20260704
SUMMARY:Festivo
END:VEVENT
END:VCALENDAR
"""

START = datetime(2026, 6, 30)
END = datetime(2026, 7, 31)


def test_parse_and_expand():
    evs = parse_events(ICS, START, END, "Personal")
    assert [e.summary for e in evs] == ["Reunión", "Yoga", "Festivo", "Yoga", "Yoga"]
    assert evs[0].location == "Sala 1"
    assert evs[0].calendar == "Personal"
    assert evs[2].all_day and not evs[0].all_day


def test_garbage():
    assert parse_events("nada", START, END) == []


def test_url_swap():
    assert caldav_url_from("https://dav.mailbox.org/carddav/") == "https://dav.mailbox.org/caldav/"
    assert caldav_url_from("https://x.org/dav/") == "https://x.org/dav/"


def test_build_new_event_roundtrip():
    from ccaccess.caldav_client import Event, build_ics

    ev = Event("", "Dentista", datetime(2026, 7, 5, 9), datetime(2026, 7, 5, 10), False, "Clínica", "Revisión")
    ics = build_ics(ev, "uid-1")
    got = parse_events(ics, START, END)
    assert len(got) == 1
    assert got[0].summary == "Dentista" and got[0].start == datetime(2026, 7, 5, 9)
    assert got[0].end == datetime(2026, 7, 5, 10)
    assert got[0].location == "Clínica" and got[0].description == "Revisión"


def test_build_all_day():
    from ccaccess.caldav_client import Event, build_ics

    ev = Event("", "Viaje", datetime(2026, 7, 6), datetime(2026, 7, 9), True)
    got = parse_events(build_ics(ev, "u2"), START, END)
    assert got[0].all_day and got[0].end == datetime(2026, 7, 9)


def test_edit_recurring_keeps_rrule_and_times():
    from ccaccess.caldav_client import build_ics

    ev = [e for e in parse_events(ICS, START, END) if e.uid == "weekly"][0]
    assert ev.recurring
    ev.summary = "Pilates"
    out = build_ics(ev, ev.uid)
    got = [e for e in parse_events(out, START, END) if e.uid == "weekly"]
    assert [e.summary for e in got] == ["Pilates"] * 3
    assert "RRULE" in out and "SEQUENCE:1" in out
