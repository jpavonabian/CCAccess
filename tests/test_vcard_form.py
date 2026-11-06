import pytest

from ccaccess.vcard_form import ContactForm, apply_form, form_from_vcard, split_typed

RAW_FULL = (
    "BEGIN:VCARD\nVERSION:3.0\nUID:u1\nFN:Ana Pérez\nN:Pérez;Ana;María;Dra.;\nNICKNAME:Anita\n"
    "ORG:Acme\nTITLE:Jefa\nTEL;TYPE=CELL:111\nTEL;TYPE=WORK,FAX:222\nEMAIL;TYPE=HOME:a@b.c\n"
    "ADR;TYPE=HOME:;;Calle 1;Madrid;;28001;España\nURL:https://x.es\nBDAY:1990-05-01\n"
    "CATEGORIES:amigos,trabajo\nNOTE:hola\nPHOTO;ENCODING=b:AAAA\nX-CUSTOM:z\nEND:VCARD\n"
)


def test_form_reads_everything():
    f = form_from_vcard(RAW_FULL)
    assert (f.fullname, f.prefix, f.given, f.additional, f.family) == ("Ana Pérez", "Dra.", "Ana", "María", "Pérez")
    assert f.nickname == "Anita" and f.org == "Acme" and f.title == "Jefa"
    assert f.phones == ["móvil: 111", "trabajo, fax: 222"]
    assert f.emails == ["casa: a@b.c"]
    assert f.addresses == ["casa: Calle 1; Madrid; ; 28001; España"]
    assert f.urls == ["https://x.es"]
    assert f.birthday == "01/05/1990"
    assert f.categories == "amigos, trabajo"


def test_unchanged_form_keeps_vcard_content():
    out = apply_form(RAW_FULL, form_from_vcard(RAW_FULL), "u1").replace("\r", "")
    for needle in ("BDAY:1990-05-01", "X-CUSTOM:z", "PHOTO", "N:Pérez;Ana;María;Dra.;", "TYPE=CELL", "111", "222"):
        assert needle in out


def test_edit_and_add_fields():
    f = form_from_vcard(RAW_FULL)
    f.phones = ["móvil: 111", "casa: 333"]  # quita 222, añade 333 con tipo
    f.emails.append("b@c.d")
    f.addresses = ["trabajo: Plaza 2; Sevilla; Andalucía; 41001; España"]
    f.birthday = "02/06/1991"
    f.title = ""
    f.role = "Directora"
    f.nickname = "Ani"
    f.categories = "familia"
    f.impps = ["xmpp:ana@x.org"]
    out = apply_form(RAW_FULL, f, "u1").replace("\r", "")
    back = form_from_vcard(out)
    assert back.phones == ["móvil: 111", "casa: 333"]
    assert back.emails == ["casa: a@b.c", "b@c.d"]
    assert back.addresses == ["trabajo: Plaza 2; Sevilla; Andalucía; 41001; España"]
    assert back.birthday == "02/06/1991" and "BDAY:1991-06-02" in out
    assert "TITLE" not in out and back.role == "Directora" and back.nickname == "Ani"
    assert back.categories == "familia" and back.impps == ["xmpp:ana@x.org"]
    assert "X-CUSTOM:z" in out and "PHOTO" in out


def test_new_contact_and_fullname_change():
    new = apply_form("", ContactForm(given="Luis", family="García", phones=["600"], note="n"), "uid-1")
    back = form_from_vcard(new)
    assert back.fullname == "Luis García" and back.given == "Luis" and back.phones == ["600"]
    f = form_from_vcard(RAW_FULL)
    f.fullname = "Ana López"  # cambia solo el nombre completo -> N se regenera
    assert form_from_vcard(apply_form(RAW_FULL, f, "u1")).family == "López"


def test_bad_date_raises():
    with pytest.raises(ValueError):
        apply_form("", ContactForm(fullname="A", birthday="31/31/2000"), "u")


def test_split_typed():
    assert split_typed("Móvil: 600") == (["cell"], "600")
    assert split_typed("https://x.es") == ([], "https://x.es")
    assert split_typed("casa, trabajo: 1") == (["home", "work"], "1")
