"""Importar y exportar contra un servidor real (Radicale en localhost, ver conftest.py)."""
from datetime import datetime

import pytest

pytest.importorskip("radicale")

from ccaccess.exchange import (  # noqa: E402
    import_contacts,
    import_events,
    join_vcards,
    merge_icalendars,
    split_icalendar,
    split_vcards,
)

START = datetime(2026, 3, 1).astimezone()
END = datetime(2026, 5, 1).astimezone()

VCF = """BEGIN:VCARD
VERSION:3.0
UID:ana-1
FN:Ana López
EMAIL:ana@example.com
X-CUSTOM:conservado
END:VCARD
BEGIN:VCARD
VERSION:3.0
UID:luis@example.com
FN:Luis Pérez
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Sin UID
END:VCARD
"""

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:serie@example.com
DTSTART:20260302T090000Z
DTEND:20260302T100000Z
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Serie
END:VEVENT
BEGIN:VEVENT
UID:serie@example.com
RECURRENCE-ID:20260303T090000Z
DTSTART:20260303T150000Z
DTEND:20260303T160000Z
SUMMARY:Excepción
END:VEVENT
BEGIN:VEVENT
UID:suelto
DTSTART;VALUE=DATE:20260310
DTEND;VALUE=DATE:20260311
SUMMARY:Suelto
END:VEVENT
END:VCALENDAR
"""


def test_import_contacts_then_again_skips_existing(book):
    client, b = book
    items, bad = split_vcards(VCF)
    first = import_contacts(client, b.url, items, bad)
    assert (first.created, first.existing, first.failed) == (3, 0, [])
    names = sorted(c.name for c in client.fetch_contacts(b.url))
    assert names == ["Ana López", "Luis Pérez", "Sin UID"]
    again = import_contacts(client, b.url, items, bad)
    assert (again.created, again.existing) == (0, 3)
    assert len(client.fetch_contacts(b.url)) == 3  # nada duplicado


def test_imported_contact_keeps_unknown_fields(book):
    client, b = book
    import_contacts(client, b.url, split_vcards(VCF)[0])
    ana = [c for c in client.fetch_contacts(b.url) if c.uid == "ana-1"][0]
    assert "X-CUSTOM:conservado" in ana.raw and ana.emails == ["ana@example.com"]


def test_export_contacts_and_import_elsewhere(book, server):
    from ccaccess.carddav import CardDavClient
    import requests

    client, b = book
    import_contacts(client, b.url, split_vcards(VCF)[0])
    exported = join_vcards([c.raw for c in client.fetch_contacts(b.url)])
    other = f"{server}/ana/otra-libreta/"
    body = (
        '<d:mkcol xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:set><d:prop>'
        "<d:resourcetype><d:collection/><c:addressbook/></d:resourcetype></d:prop></d:set></d:mkcol>"
    )
    assert requests.request("MKCOL", other, data=body, auth=("ana", "x")).status_code in (200, 201)
    items, bad = split_vcards(exported)
    assert bad == 0 and len(items) == 3
    res = import_contacts(CardDavClient(f"{server}/ana/", "ana", "x"), other, items)
    assert res.created == 3 and not res.has_problems


def test_import_events_keeps_series_with_exception(cal):
    client, calendar = cal
    items, ignored = split_icalendar(ICS)
    res = import_events(client, calendar, items, ignored)
    assert (res.created, res.existing, res.failed) == (2, 0, [])
    evs = client.fetch_events(calendar, START, END)
    assert [(e.summary, e.start.day) for e in evs if e.uid.startswith("serie")] == [
        ("Serie", 2), ("Excepción", 3), ("Serie", 4),
    ]
    assert [e for e in evs if e.summary == "Suelto"][0].all_day
    again = import_events(client, calendar, items, ignored)
    assert (again.created, again.existing) == (0, 2)
    assert len(client.fetch_events(calendar, START, END)) == 4  # nada duplicado


def test_export_all_events_roundtrip(cal, server, request):
    import requests

    from ccaccess.caldav_client import CalDavClient

    client, calendar = cal
    import_events(client, calendar, split_icalendar(ICS)[0])
    raws = client.fetch_raw(calendar)
    assert len(raws) == 2  # recursos, no ocurrencias
    exported = merge_icalendars(raws)
    assert exported.count("BEGIN:VEVENT") == 3 and "RRULE" in exported
    name = "destino"
    body = (
        '<c:mkcalendar xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:"><d:set><d:prop>'
        f"<d:displayname>{name}</d:displayname></d:prop></d:set></c:mkcalendar>"
    )
    requests.request("MKCALENDAR", f"{server}/ana/{name}/", data=body, auth=("ana", "x"))
    other = CalDavClient(f"{server}/ana/", "ana", "x")
    dest = [c for c in other.discover_calendars() if c.name == name][0]
    res = import_events(other, dest, split_icalendar(exported)[0])
    assert res.created == 2
    assert [(e.summary, e.start.day) for e in other.fetch_events(dest, START, END)] == [
        (e.summary, e.start.day) for e in client.fetch_events(calendar, START, END)
    ]
