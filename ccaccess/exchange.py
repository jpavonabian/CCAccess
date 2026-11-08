"""Importar y exportar contactos (.vcf) y eventos (.ics), sin Qt."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import icalendar
import vobject

from ccaccess.carddav import DavConflict, DavError

_VCARD_RE = re.compile(r"BEGIN:VCARD.*?END:VCARD", re.IGNORECASE | re.DOTALL)
_BAD_NAME_CHARS = re.compile(r"[^A-Za-z0-9._@=-]")


def read_text(path: str) -> str:
    """Lee un archivo de texto: UTF-8 y, si no lo es, Windows-1252 (típico de exportaciones antiguas)."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def safe_name(uid: str, ext: str) -> str:
    """Nombre de archivo para el servidor a partir del UID; el mismo UID da siempre el mismo nombre."""
    name = _BAD_NAME_CHARS.sub("_", uid)[:120].strip(".")
    return (name or str(uuid.uuid4())) + ext


def file_stem(name: str, default: str) -> str:
    """Nombre de archivo razonable (sin caracteres prohibidos en Windows) a partir de un título."""
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" ._")[:80] or default


# --- contactos ---------------------------------------------------------------
def split_vcards(text: str) -> tuple[list[tuple[str, str]], int]:
    """Separa un .vcf en [(uid, vcard)] y cuenta los bloques ilegibles. Se respeta el texto original."""
    out: list[tuple[str, str]] = []
    bad = 0
    for block in _VCARD_RE.findall(text):
        block = re.sub(r"\r?\n", "\r\n", block.strip()) + "\r\n"
        try:
            card = vobject.readOne(block)
        except Exception:
            bad += 1
            continue
        uid = card.contents.get("uid")
        if uid and str(uid[0].value).strip():
            out.append((str(uid[0].value).strip(), block))
        else:  # sin UID no se puede crear en el servidor ni detectar repetidos
            new = str(uuid.uuid4())
            card.add("uid").value = new
            out.append((new, card.serialize()))
    return out, bad


def join_vcards(vcards: list[str]) -> str:
    return "".join(v if v.endswith("\n") else v + "\r\n" for v in vcards)


# --- eventos -----------------------------------------------------------------
def _tzids(vevents) -> set[str]:
    found = set()
    for ev in vevents:
        for value in ev.values():
            for item in value if isinstance(value, list) else [value]:
                tzid = getattr(item, "params", {}).get("TZID")
                if tzid:
                    found.add(str(tzid))
    return found


def split_icalendar(text: str) -> tuple[list[tuple[str, str]], int]:
    """Separa un .ics en [(uid, icalendar)] con una serie y sus excepciones juntas.

    Devuelve también cuántos elementos que no son eventos (tareas…) se ignoran.
    Lanza ValueError si el archivo no es un iCalendar.
    """
    try:
        cals = icalendar.Calendar.from_ical(text, multiple=True)
    except Exception as e:
        raise ValueError("El archivo no es un calendario iCalendar válido.") from e
    groups: dict[str, list] = {}
    zones: dict[str, object] = {}
    ignored = 0
    for cal in cals:
        for sub in cal.subcomponents:
            if sub.name == "VTIMEZONE":
                zones.setdefault(str(sub.get("TZID", "")), sub)
            elif sub.name == "VEVENT":
                if not str(sub.get("UID", "")).strip():
                    sub.add("UID", str(uuid.uuid4()))
                groups.setdefault(str(sub["UID"]).strip(), []).append(sub)
            else:
                ignored += 1
    out = []
    for uid, vevents in groups.items():
        new = icalendar.Calendar()
        new.add("PRODID", "-//CCAccess//ES")
        new.add("VERSION", "2.0")
        for tzid in sorted(_tzids(vevents)):
            if tzid in zones:
                new.add_component(zones[tzid])
        for ev in vevents:
            new.add_component(ev)
        out.append((uid, new.to_ical().decode("utf-8")))
    return out, ignored


def merge_icalendars(raws: list[str]) -> str:
    """Junta varios iCalendar en uno solo, sin repetir husos horarios."""
    merged = icalendar.Calendar()
    merged.add("PRODID", "-//CCAccess//ES")
    merged.add("VERSION", "2.0")
    seen: set[str] = set()
    for raw in raws:
        try:
            cal = icalendar.Calendar.from_ical(raw)
        except Exception:
            continue
        for sub in cal.subcomponents:
            if sub.name == "VTIMEZONE":
                tzid = str(sub.get("TZID", ""))
                if tzid in seen:
                    continue
                seen.add(tzid)
            elif sub.name != "VEVENT":
                continue
            merged.add_component(sub)
    return merged.to_ical().decode("utf-8")


# --- importación -------------------------------------------------------------
@dataclass
class ImportResult:
    created: int = 0
    existing: int = 0  # ya estaban en el servidor
    invalid: int = 0  # no se pudieron leer del archivo
    ignored: int = 0  # elementos que no son del tipo importado (tareas…)
    failed: list[str] = field(default_factory=list)  # errores del servidor

    def summary(self, singular: str, plural: str) -> str:
        n = self.created
        parts = [f"Importado{'s' if n != 1 else ''} {n} {singular if n == 1 else plural}."]
        if self.existing:
            parts.append(f"{self.existing} ya existía{'n' if self.existing != 1 else ''} y se omitió.")
        if self.invalid:
            parts.append(f"{self.invalid} no se pudo leer del archivo.")
        if self.ignored:
            parts.append(f"{self.ignored} elemento{'s' if self.ignored != 1 else ''} de otro tipo se ignoró.")
        if self.failed:
            parts.append(f"{len(self.failed)} falló en el servidor: {'; '.join(self.failed[:3])}")
        return " ".join(parts)

    @property
    def has_problems(self) -> bool:
        return bool(self.invalid or self.failed)


def _import_all(items, put, result: ImportResult) -> ImportResult:
    for uid, text in items:
        try:
            put(uid, text)
            result.created += 1
        except DavConflict:
            result.existing += 1
        except DavError as e:
            if "incorrectos" in str(e) or "No se pudo conectar" in str(e):
                raise  # no tiene sentido seguir
            result.failed.append(str(e))
    return result


def import_contacts(client, book_url: str, items: list[tuple[str, str]], invalid: int = 0) -> ImportResult:
    return _import_all(items, lambda uid, text: client.import_contact(book_url, uid, text), ImportResult(invalid=invalid))


def import_events(client, calendar, items: list[tuple[str, str]], ignored: int = 0) -> ImportResult:
    return _import_all(items, lambda uid, text: client.import_event(calendar, uid, text), ImportResult(ignored=ignored))
