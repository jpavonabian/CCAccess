import pytest

from ccaccess.carddav import DavConflict, DavError
from ccaccess.exchange import (
    ImportResult,
    import_contacts,
    join_vcards,
    merge_icalendars,
    read_text,
    safe_name,
    split_icalendar,
    split_vcards,
)
from ccaccess.textutil import fold

VCF = """BEGIN:VCARD
VERSION:3.0
UID:ana-1
FN:Ana López
TEL;TYPE=CELL:600 000 000
X-CUSTOM:conservado
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Sin identificador
END:VCARD
BEGIN:VCARD
VERSION:3.0
UID:roto
FN:Bloque roto
END:VCARD
"""


def test_split_vcards_keeps_original_text_and_adds_missing_uid():
    items, bad = split_vcards(VCF)
    assert bad == 0 and len(items) == 3
    uid, card = items[0]
    assert uid == "ana-1" and "X-CUSTOM:conservado" in card and "TEL;TYPE=CELL" in card
    assert card.endswith("END:VCARD\r\n") and "\n" not in card.replace("\r\n", "")
    new_uid, new_card = items[1]
    assert new_uid and f"UID:{new_uid}" in new_card and "Sin identificador" in new_card


def test_split_vcards_ignores_garbage_and_counts_unreadable():
    assert split_vcards("esto no es un vcf") == ([], 0)
    assert split_vcards("")[0] == []


def test_join_vcards_roundtrip():
    items, _ = split_vcards(VCF)
    again, _ = split_vcards(join_vcards([c for _, c in items]))
    assert [u for u, _ in again] == [u for u, _ in items]


def test_read_text_utf8_and_latin1(tmp_path):
    a = tmp_path / "a.vcf"
    a.write_bytes("FN:José\r\n".encode("utf-8-sig"))
    assert read_text(str(a)) == "FN:José\r\n"
    b = tmp_path / "b.vcf"
    b.write_bytes("FN:José\r\n".encode("cp1252"))  # Outlook antiguo
    assert read_text(str(b)) == "FN:José\r\n"


ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VTIMEZONE
TZID:Europe/Madrid
BEGIN:STANDARD
DTSTART:19701025T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:America/Mexico_City
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:-0600
TZOFFSETTO:-0600
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:serie
DTSTART;TZID=Europe/Madrid:20260302T090000
DTEND;TZID=Europe/Madrid:20260302T100000
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Serie
END:VEVENT
BEGIN:VEVENT
UID:serie
RECURRENCE-ID;TZID=Europe/Madrid:20260303T090000
DTSTART;TZID=Europe/Madrid:20260303T150000
DTEND;TZID=Europe/Madrid:20260303T160000
SUMMARY:Excepción
END:VEVENT
BEGIN:VEVENT
UID:suelto
DTSTART:20260310T100000Z
DTEND:20260310T110000Z
SUMMARY:Suelto
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260315
SUMMARY:Sin UID
END:VEVENT
BEGIN:VTODO
UID:tarea
SUMMARY:Tarea
END:VTODO
END:VCALENDAR
"""


def test_split_icalendar_groups_series_and_picks_timezones():
    items, ignored = split_icalendar(ICS)
    assert ignored == 1 and len(items) == 3
    by_uid = dict(items)
    serie = by_uid["serie"]
    assert serie.count("BEGIN:VEVENT") == 2 and "RECURRENCE-ID" in serie  # serie y excepción juntas
    assert "TZID:Europe/Madrid" in serie and "Mexico_City" not in serie
    assert "VTIMEZONE" not in by_uid["suelto"]
    assert all("UID:" in ics for ics in by_uid.values())  # al evento sin UID se le dio uno


def test_split_icalendar_rejects_garbage():
    with pytest.raises(ValueError):
        split_icalendar("esto no es un calendario")


def test_merge_icalendars_dedupes_timezones():
    items, _ = split_icalendar(ICS)
    merged = merge_icalendars([ics for _, ics in items] + [items[0][1]])
    assert merged.count("BEGIN:VTIMEZONE") == 1
    assert merged.count("BEGIN:VEVENT") == 4 + 2  # los 4 VEVENT del archivo y los 2 de la serie repetida
    assert "VTODO" not in merged


def test_safe_name_is_stable_and_clean():
    assert safe_name("a@b.com", ".ics") == "a@b.com.ics"
    assert safe_name("../../etc/pa ss", ".vcf") == "_.._etc_pa_ss.vcf" or "/" not in safe_name("../../etc/pa ss", ".vcf")
    assert safe_name("x", ".ics") == safe_name("x", ".ics")
    assert safe_name("", ".ics").endswith(".ics") and len(safe_name("u" * 500, ".ics")) < 140


class FakeClient:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.sent = []

    def import_contact(self, book, uid, text):
        self.sent.append(uid)
        action = self.behaviour.get(uid)
        if action:
            raise action


def test_import_counts_created_existing_and_failed():
    client = FakeClient({"b": DavConflict("existe"), "c": DavError("El servidor respondió 500")})
    r = import_contacts(client, "/book/", [("a", "x"), ("b", "x"), ("c", "x"), ("d", "x")], invalid=2)
    assert (r.created, r.existing, r.invalid, len(r.failed)) == (2, 1, 2, 1) and r.has_problems
    text = r.summary("contacto", "contactos")
    assert "Importados 2 contactos" in text and "1 ya existía" in text and "2 no se pudo leer" in text
    assert "falló en el servidor" in text and "500" in text


def test_import_aborts_on_auth_error():
    client = FakeClient({"a": DavError("Usuario o contraseña incorrectos.")})
    with pytest.raises(DavError):
        import_contacts(client, "/book/", [("a", "x"), ("b", "x")])
    assert client.sent == ["a"]  # no sigue intentándolo


def test_summary_singular():
    assert ImportResult(created=1).summary("evento", "eventos") == "Importado 1 evento."
    assert not ImportResult(created=3, existing=1).has_problems


def test_fold_ignores_case_and_accents():
    assert fold("José NIÑO Ünder") == "jose nino under"
    assert fold("jose") in fold("Reunión con José")
