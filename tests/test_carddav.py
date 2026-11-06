from ccaccess.carddav import parse_vcard

VCARD = """BEGIN:VCARD
VERSION:3.0
UID:abc-1
FN:Ana Pérez
ORG:Acme;Ventas
TEL;TYPE=CELL:+34 600 000 000
EMAIL:ana@example.com
NOTE:Hola
END:VCARD
"""


def test_parse_full():
    c = parse_vcard("/a.vcf", VCARD)
    assert c.name == "Ana Pérez"
    assert c.emails == ["ana@example.com"]
    assert c.phones == ["+34 600 000 000"]
    assert c.org == "Acme Ventas"
    assert c.uid == "abc-1"


def test_parse_no_name_falls_back_to_email():
    c = parse_vcard("/b.vcf", "BEGIN:VCARD\nVERSION:3.0\nFN:\nEMAIL:x@y.z\nEND:VCARD\n")
    assert c.name == "x@y.z"


def test_parse_garbage():
    assert parse_vcard("/c.vcf", "no es vcard") is None


def test_build_new_and_roundtrip():
    from ccaccess.carddav import Contact, build_vcard

    c = Contact("", "", "Luis García", ["l@x.com"], ["111", "222"], "Acme", "nota")
    text = build_vcard(c, "uid-9")
    back = parse_vcard("/l.vcf", text)
    assert back.name == "Luis García"
    assert back.phones == ["111", "222"]
    assert back.emails == ["l@x.com"]
    assert back.org == "Acme" and back.note == "nota"
    assert back.uid == "uid-9"
    assert "N:García;Luis" in text.replace("\r", "") or "N:García;Luis;;;" in text.replace("\r", "")


def test_update_preserves_unknown_fields_and_params():
    from ccaccess.carddav import build_vcard

    raw = (
        "BEGIN:VCARD\nVERSION:3.0\nUID:u1\nFN:Ana Pérez\nN:Pérez;Ana;;;\n"
        "TEL;TYPE=CELL:111\nTEL:222\nBDAY:1990-01-02\nX-CUSTOM:hola\nEND:VCARD\n"
    )
    c = parse_vcard("/a.vcf", raw)
    c.phones = ["111", "333"]  # quita 222, añade 333
    c.org = "Nueva"
    text = build_vcard(c, "u1").replace("\r", "")
    assert "BDAY:1990-01-02" in text
    assert "X-CUSTOM:hola" in text
    assert "TYPE=CELL" in text and "222" not in text and "333" in text
    assert "N:Pérez;Ana" in text  # el nombre no cambió: N intacto


def test_describe_vcard_shows_everything():
    from ccaccess.carddav import describe_vcard

    raw = (
        "BEGIN:VCARD\nVERSION:3.0\nUID:u\nFN:Ana Pérez\nN:Pérez;Ana;;;\nORG:Acme;Ventas\n"
        "TITLE:Jefa\nTEL;TYPE=CELL:+34 600\nEMAIL;TYPE=WORK:a@b.c\n"
        "ADR;TYPE=HOME:;;Calle 1;Madrid;;28001;España\nBDAY:1990-05-01\n"
        "URL:https://x.es\nX-CUSTOM:hola\nPHOTO;ENCODING=b:AAAA\nNOTE:Hola\nEND:VCARD\n"
    )
    lines = describe_vcard(raw)
    assert "Nombre: Ana Pérez" in lines
    assert "Cargo: Jefa" in lines
    assert "Teléfono (cell): +34 600" in lines
    assert "Correo (work): a@b.c" in lines
    assert any(l.startswith("Dirección (home):") and "Madrid" in l and "Calle 1" in l for l in lines)
    assert "Cumpleaños: 1990-05-01" in lines
    assert "Custom: hola" in lines
    assert "Foto: sí" in lines
    assert not any("UID" in l or "VERSION" in l for l in lines)
