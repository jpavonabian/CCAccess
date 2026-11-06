"""Edición completa de un vCard: conversión entre el texto del formulario y las propiedades.

Los campos repetibles (teléfonos, correos, direcciones, webs, mensajería) se editan como
una línea por elemento con el formato opcional «tipo: valor». Ejemplo: «móvil: 600 000 000».
Lo que la app no muestra (foto, campos X-…) se conserva tal cual.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

import vobject

DATE_FMT = "%d/%m/%Y"

_TYPE_ES = {
    "cell": "móvil", "home": "casa", "work": "trabajo", "voice": "voz", "text": "sms",
    "pager": "buscapersonas", "video": "vídeo", "other": "otro",
}
_KNOWN_TYPES = {
    "cell", "home", "work", "voice", "text", "pager", "video", "other", "fax", "internet",
    "msg", "car", "isdn", "modem", "bbs", "pcs", "textphone", "x400", "pref",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().casefold())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


_ES_TO_EN = {_norm(v): k for k, v in _TYPE_ES.items()}
_ES_TO_EN.update({"movil": "cell", "oficina": "work", "particular": "home"})


def _type_to_en(word: str) -> str | None:
    n = _norm(word)
    if n in _KNOWN_TYPES:
        return n
    return _ES_TO_EN.get(n)


def split_typed(line: str) -> tuple[list[str], str]:
    """«móvil, trabajo: 600» -> (['cell','work'], '600'). Sin tipo reconocido -> ([], línea entera)."""
    line = line.strip()
    head, sep, rest = line.partition(":")
    if sep:
        words = [w for w in head.split(",") if w.strip()]
        types = [_type_to_en(w) for w in words]
        if words and all(types) and rest.strip():
            return types, rest.strip()  # type: ignore[return-value]
    return [], line


def join_typed(types: list[str], value: str) -> str:
    shown = [_TYPE_ES.get(t.lower(), t.lower()) for t in types if t.lower() != "pref"]
    return f"{', '.join(shown)}: {value}" if shown else value


def _s(v) -> str:
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v if x)
    return str(v or "").strip()


def _addr_text(a) -> str:
    return "; ".join(_s(x) for x in (a.street, a.city, a.region, a.code, a.country))


def _addr_from_text(text: str) -> vobject.vcard.Address:
    parts = [p.strip() for p in text.split(";")]
    parts += [""] * (5 - len(parts))
    return vobject.vcard.Address(
        street=parts[0], city=parts[1], region=parts[2], code=parts[3], country=" ".join(parts[4:]).strip()
    )


def date_to_text(value: str) -> str:
    v = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(v, fmt).strftime(DATE_FMT)
        except ValueError:
            pass
    return v  # formato raro (sin año, etc.): se muestra tal cual


def date_from_text(text: str) -> str:
    """dd/mm/aaaa -> aaaa-mm-dd. ValueError si no es válida."""
    return datetime.strptime(text.strip(), DATE_FMT).strftime("%Y-%m-%d")


@dataclass
class ContactForm:
    fullname: str = ""
    prefix: str = ""
    given: str = ""
    additional: str = ""
    family: str = ""
    suffix: str = ""
    nickname: str = ""
    org: str = ""
    title: str = ""
    role: str = ""
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    impps: list[str] = field(default_factory=list)
    birthday: str = ""
    anniversary: str = ""
    categories: str = ""
    note: str = ""


_MULTI = {  # campo del formulario -> propiedad vCard
    "phones": "tel", "emails": "email", "addresses": "adr", "urls": "url", "impps": "impp",
}


def _first(card, key: str) -> str:
    comps = card.contents.get(key, [])
    return _s(comps[0].value) if comps else ""


def _comp_text(comp) -> str:
    value = _addr_text(comp.value) if comp.name.lower() == "adr" else _s(comp.value)
    return join_typed(list(comp.params.get("TYPE", [])), value)


def form_from_vcard(raw: str) -> ContactForm:
    if not raw:
        return ContactForm()
    card = vobject.readOne(raw)
    f = ContactForm(fullname=_first(card, "fn"))
    n = card.contents.get("n")
    if n:
        v = n[0].value
        f.prefix, f.given, f.additional = _s(v.prefix), _s(v.given), _s(v.additional)
        f.family, f.suffix = _s(v.family), _s(v.suffix)
    f.nickname, f.org = _first(card, "nickname"), _first(card, "org")
    f.title, f.role = _first(card, "title"), _first(card, "role")
    for name, key in _MULTI.items():
        setattr(f, name, [t for t in (_comp_text(c) for c in card.contents.get(key, [])) if t])
    f.birthday = date_to_text(_first(card, "bday"))
    f.anniversary = date_to_text(_first(card, "anniversary"))
    cats = []
    for comp in card.contents.get("categories", []):
        cats += comp.value if isinstance(comp.value, list) else [comp.value]
    f.categories = ", ".join(str(c) for c in cats if c)
    f.note = _first(card, "note")
    return f


def _compose_name(f: ContactForm) -> str:
    return " ".join(p for p in (f.prefix, f.given, f.additional, f.family, f.suffix) if p.strip())


def _set_single(card, key: str, new: str, old: str, value) -> None:
    if new == old:
        return
    for comp in list(card.contents.get(key, [])):
        card.remove(comp)
    if new:
        card.add(key).value = value


def _sync_lines(card, key: str, lines: list[str]) -> None:
    comps = list(card.contents.get(key, []))
    old = {id(c): _comp_text(c) for c in comps}
    unused = {id(c): c for c in comps}
    to_add: list[str] = []
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        match = next((i for i, c in unused.items() if old[i] == line), None)
        if match is not None:
            del unused[match]
        else:
            to_add.append(line)
    for c in unused.values():
        card.remove(c)
    for line in to_add:
        types, value = split_typed(line)
        comp = card.add(key)
        comp.value = _addr_from_text(value) if key == "adr" else value
        if types:
            comp.params["TYPE"] = [t.upper() for t in types]


def apply_form(raw: str, form: ContactForm, uid: str) -> str:
    """Devuelve el vCard con los cambios del formulario aplicados sobre `raw` (o uno nuevo)."""
    card = vobject.readOne(raw) if raw else vobject.vCard()
    orig = form_from_vcard(raw)

    fullname = form.fullname.strip() or _compose_name(form)
    if not card.contents.get("fn"):
        card.add("fn")
    card.fn.value = fullname

    parts = ("prefix", "given", "additional", "family", "suffix")
    parts_changed = any(getattr(form, p) != getattr(orig, p) for p in parts)
    if parts_changed or fullname != orig.fullname or not card.contents.get("n"):
        if card.contents.get("n"):
            card.remove(card.n)
        if any(getattr(form, p).strip() for p in parts) and (parts_changed or not orig.fullname):
            card.add("n").value = vobject.vcard.Name(
                family=form.family.strip(), given=form.given.strip(),
                additional=form.additional.strip(), prefix=form.prefix.strip(), suffix=form.suffix.strip(),
            )
        else:
            from ccaccess.carddav import _split_name

            card.add("n").value = _split_name(fullname)

    _set_single(card, "nickname", form.nickname.strip(), orig.nickname, form.nickname.strip())
    _set_single(card, "org", form.org.strip(), orig.org, [form.org.strip()])
    _set_single(card, "title", form.title.strip(), orig.title, form.title.strip())
    _set_single(card, "role", form.role.strip(), orig.role, form.role.strip())
    _set_single(card, "note", form.note.strip(), orig.note, form.note.strip())
    for attr, key in (("birthday", "bday"), ("anniversary", "anniversary")):
        new = getattr(form, attr).strip()
        value = date_from_text(new) if new and new != getattr(orig, attr) else new
        _set_single(card, key, new, getattr(orig, attr), value)
    cats = [c.strip() for c in form.categories.split(",") if c.strip()]
    _set_single(card, "categories", ", ".join(cats), orig.categories, cats)

    for name, key in _MULTI.items():
        _sync_lines(card, key, getattr(form, name))
    if not card.contents.get("uid"):
        card.add("uid").value = uid
    return card.serialize()
