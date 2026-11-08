"""Repeticiones de eventos, sin Qt.

- Modelo simple y editable de una regla (RepeatSpec) y su texto en español.
- Edición de series sobre el iCalendar original: toda la serie, una ocurrencia
  (VEVENT con RECURRENCE-ID), borrar una ocurrencia (EXDATE) y «este y los siguientes».
Lo que la app no sabe editar (BYSETPOS, días ordinales…) se conserva tal cual.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import icalendar
from dateutil import rrule as du_rrule

from ccaccess.caldav_client import Event, _same_instant, _set_start_alarm, _to_local

DAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_DAY_PLURAL = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos")
_LETTERS = {"L": "MO", "M": "TU", "X": "WE", "J": "TH", "V": "FR", "S": "SA", "D": "SU"}
_WORDS = {
    "lun": "MO", "lunes": "MO", "mar": "TU", "martes": "TU", "mie": "WE", "mié": "WE",
    "miercoles": "WE", "miércoles": "WE", "jue": "TH", "jueves": "TH", "vie": "FR",
    "viernes": "FR", "sab": "SA", "sáb": "SA", "sabado": "SA", "sábado": "SA", "dom": "SU",
    "domingo": "SU",
}
_UNITS = {
    "DAILY": ("día", "días"),
    "WEEKLY": ("semana", "semanas"),
    "MONTHLY": ("mes", "meses"),
    "YEARLY": ("año", "años"),
}


@dataclass(frozen=True)
class RepeatSpec:
    freq: str  # DAILY, WEEKLY, MONTHLY o YEARLY
    interval: int = 1
    days: tuple[str, ...] = ()  # solo semanal: MO, TU…; vacío = el día de la semana del inicio
    until: date | None = None  # último día (incluido)
    count: int | None = None  # número de veces; excluyente con until


def style_of(value) -> str:
    """Cómo escribe fechas la serie: «date» (todo el día), «floating» (sin zona) o «utc»."""
    if not isinstance(value, datetime):
        return "date"
    return "floating" if value.tzinfo is None else "utc"


# --- reglas ----------------------------------------------------------------
def _norm(rule: str) -> str:
    return icalendar.vRecur.from_ical(rule).to_ical().decode() if rule else ""


def parse_rrule(rule: str, start: datetime) -> RepeatSpec | None:
    """Convierte un RRULE en RepeatSpec, o None si es más complejo que lo que sabe editar la app."""
    if not rule:
        return None
    try:
        rr = icalendar.vRecur.from_ical(rule)
    except Exception:
        return None
    if set(rr) - {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "WKST"}:
        return None
    freq = str(rr.get("FREQ", [""])[0])
    if freq not in _UNITS or ("COUNT" in rr and "UNTIL" in rr):
        return None
    try:
        interval = int(rr.get("INTERVAL", [1])[0])
        count = int(rr["COUNT"][0]) if "COUNT" in rr else None
    except (TypeError, ValueError):
        return None
    if interval < 1 or (count is not None and count < 1):
        return None
    days = tuple(str(d) for d in rr.get("BYDAY", []))
    if days and (freq != "WEEKLY" or any(d not in DAY_CODES for d in days)):
        return None
    if "BYMONTHDAY" in rr:
        md = rr["BYMONTHDAY"]
        if freq not in ("MONTHLY", "YEARLY") or len(md) != 1 or int(md[0]) != start.day:
            return None
    if "BYMONTH" in rr:
        bm = rr["BYMONTH"]
        if freq != "YEARLY" or len(bm) != 1 or int(bm[0]) != start.month:
            return None
    if "WKST" in rr and str(rr["WKST"][0]) != "MO":
        return None
    until = None
    if "UNTIL" in rr:
        u = rr["UNTIL"][0]
        if isinstance(u, datetime):
            until = (u.astimezone() if u.tzinfo is not None else u).date()
        else:
            until = u
    return RepeatSpec(freq, interval, days, until, count)


def build_rrule(spec: RepeatSpec, style: str) -> str:
    """Texto RRULE de `spec`. `style` es el de style_of() para que UNTIL sea del mismo tipo que DTSTART."""
    parts: dict = {"FREQ": [spec.freq]}
    if spec.interval > 1:
        parts["INTERVAL"] = [spec.interval]
    if spec.days:
        parts["BYDAY"] = list(spec.days)
    if spec.count:
        parts["COUNT"] = [spec.count]
    elif spec.until:
        if style == "date":
            parts["UNTIL"] = [spec.until]
        else:
            end = datetime.combine(spec.until, time(23, 59, 59))
            parts["UNTIL"] = [end if style == "floating" else end.astimezone(timezone.utc)]
    return icalendar.vRecur(parts).to_ical().decode()


def parse_days(text: str) -> tuple[str, ...] | None:
    """«L M X», «lun, mié»… a códigos MO, WE… en orden de semana. None si algo no se entiende."""
    found = set()
    for tok in text.replace(",", " ").replace(";", " ").split():
        code = _WORDS.get(tok.lower()) or (_LETTERS.get(tok.upper()) if len(tok) == 1 else None)
        if code is None:
            return None
        found.add(code)
    return tuple(c for c in DAY_CODES if c in found)


def days_text(days: tuple[str, ...]) -> str:
    inv = {v: k for k, v in _LETTERS.items()}
    return " ".join(inv[d] for d in days)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def describe(spec: RepeatSpec) -> str:
    """«Cada 2 semanas, los lunes y miércoles, hasta el 30/06/2026»."""
    one, many = _UNITS[spec.freq]
    text = f"Cada {one}" if spec.interval == 1 else f"Cada {spec.interval} {many}"
    if spec.days:
        text += ", los " + _join([_DAY_PLURAL[DAY_CODES.index(d)] for d in spec.days])
    if spec.until:
        text += f", hasta el {spec.until:%d/%m/%Y}"
    elif spec.count:
        text += ", 1 vez" if spec.count == 1 else f", {spec.count} veces"
    return text


def describe_rrule(rule: str, start: datetime) -> str:
    """Texto hablado de una regla; vacío si no hay. Las avanzadas se muestran como personalizadas."""
    if not rule:
        return ""
    spec = parse_rrule(rule, start)
    return describe(spec) if spec else f"Repetición personalizada ({rule})"


# --- utilidades de edición ----------------------------------------------------
def _cmp(value) -> datetime:
    """Valor comparable de una fecha/hora de iCalendar (dentro de una misma serie)."""
    if not isinstance(value, datetime):
        return datetime.combine(value, time.min)
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _load(raw: str, uid: str):
    cal = icalendar.Calendar.from_ical(raw)
    masters = [c for c in cal.walk("VEVENT") if c.get("RECURRENCE-ID") is None]
    master = next((c for c in masters if str(c.get("UID", "")) == uid), masters[0] if masters else None)
    if master is None:
        raise ValueError("El evento no tiene serie principal.")
    return cal, master


def _overrides(cal, master) -> list:
    uid = str(master.get("UID", ""))
    return [
        c for c in cal.walk("VEVENT")
        if c.get("RECURRENCE-ID") is not None and str(c.get("UID", "")) == uid
    ]


def _find_override(cal, master, key):
    return next((c for c in _overrides(cal, master) if _same_instant(c["RECURRENCE-ID"].dt, key)), None)


def _remove(cal, comp) -> None:
    cal.subcomponents[:] = [c for c in cal.subcomponents if c is not comp]


def _bump(vevent) -> None:
    seq = int(vevent.get("SEQUENCE", 0)) + 1
    for key in ("SEQUENCE", "DTSTAMP"):
        vevent.pop(key, None)
    vevent.add("SEQUENCE", seq)
    vevent.add("DTSTAMP", datetime.now(timezone.utc))


def _set_text(vevent, ev: Event) -> None:
    _bump(vevent)
    for key in ("SUMMARY", "LOCATION", "DESCRIPTION"):
        vevent.pop(key, None)
    vevent.add("SUMMARY", ev.summary)
    if ev.location:
        vevent.add("LOCATION", ev.location)
    if ev.description:
        vevent.add("DESCRIPTION", ev.description)
    _set_start_alarm(vevent, ev)


def _write_times(vevent, start: datetime, end: datetime, all_day: bool, style: str) -> None:
    for key in ("DTSTART", "DTEND", "DURATION"):
        vevent.pop(key, None)
    if all_day:
        vevent.add("DTSTART", start.date())
        vevent.add("DTEND", end.date())
    elif style == "floating":
        vevent.add("DTSTART", start)
        vevent.add("DTEND", end)
    else:
        vevent.add("DTSTART", start.astimezone(timezone.utc))
        vevent.add("DTEND", end.astimezone(timezone.utc))


def _times_changed(ev: Event) -> bool:
    return ev.occ_start is not None and (ev.start != ev.occ_start or ev.end != ev.occ_end)


def _shift_byday(rr, days: int) -> None:
    byday = [str(d) for d in rr.get("BYDAY", [])]
    if str(rr.get("FREQ", [""])[0]) == "WEEKLY" and byday and all(d in DAY_CODES for d in byday):
        rr["BYDAY"] = [DAY_CODES[(DAY_CODES.index(d) + days) % 7] for d in byday]


# --- toda la serie ------------------------------------------------------------
def _shift_series_times(master, ev: Event) -> int:
    """Mueve la serie lo que el usuario movió la ocurrencia. Devuelve el desplazamiento en días."""
    old = master["DTSTART"].dt
    old_all_day = not isinstance(old, datetime)
    if ev.occ_start is None or (not _times_changed(ev) and ev.all_day == old_all_day):
        return 0
    delta = ev.start - ev.occ_start
    delta_days = (ev.start.date() - ev.occ_start.date()).days
    pars = None
    if ev.all_day:
        first = old + timedelta(days=delta_days) if old_all_day else (_to_local(old)[0] + delta).date()
        start_v = first
        end_v = first + timedelta(days=max((ev.end.date() - ev.start.date()).days, 1))
    else:
        if old_all_day:
            local = datetime.combine(old + timedelta(days=delta_days), ev.start.time())
            start_v = local.astimezone(timezone.utc)
        else:
            start_v = old + delta  # suma de reloj de pared en la zona de la serie
            if old.tzinfo is not None:
                pars = dict(master["DTSTART"].params)
        end_v = start_v + (ev.end - ev.start)
    for key in ("DTSTART", "DTEND", "DURATION"):
        master.pop(key, None)
    master.add("DTSTART", start_v, parameters=pars)
    master.add("DTEND", end_v, parameters=pars)
    return delta_days


def edit_series(raw: str, ev: Event, uid: str) -> str:
    cal, master = _load(raw, uid)
    _set_text(master, ev)
    old_style = style_of(master["DTSTART"].dt)
    delta_days = _shift_series_times(master, ev)
    current = master.get("RRULE")
    current_str = current.to_ical().decode() if current is not None else ""
    desired = ev.rrule or ""
    if _norm(desired) == _norm(current_str):
        new_style = style_of(master["DTSTART"].dt)
        if current is not None and new_style != old_style and "UNTIL" in current:
            # de todo el día a con hora (o al revés): UNTIL debe ser del mismo tipo que DTSTART
            spec = parse_rrule(current_str, ev.occ_start or ev.start)
            if spec:
                master["RRULE"] = icalendar.vRecur.from_ical(build_rrule(spec, new_style))
                current = master["RRULE"]
        if current is not None and delta_days:
            _shift_byday(current, delta_days)  # lunes y miércoles movidos un día -> martes y jueves
    else:
        master.pop("RRULE", None)
        if desired:
            master.add("RRULE", icalendar.vRecur.from_ical(desired))
        else:  # deja de repetirse: se descartan fechas excluidas y excepciones
            for key in ("RDATE", "EXDATE", "EXRULE"):
                master.pop(key, None)
            for ov in _overrides(cal, master):
                _remove(cal, ov)
    return cal.to_ical().decode("utf-8")


# --- una sola ocurrencia ------------------------------------------------------
def edit_occurrence(raw: str, ev: Event, uid: str) -> str:
    cal, master = _load(raw, uid)
    key = ev.occ_key
    ov = _find_override(cal, master, key)
    is_new = ov is None
    if is_new:
        ov = copy.deepcopy(master)  # conserva campos y avisos de la serie
        for k in ("RRULE", "RDATE", "EXDATE", "EXRULE", "DTSTART", "DTEND", "DURATION", "RECURRENCE-ID"):
            ov.pop(k, None)
        ov.add("RECURRENCE-ID", key)
    _set_text(ov, ev)
    if is_new or _times_changed(ev):
        _write_times(ov, ev.start, ev.end, ev.all_day, style_of(master["DTSTART"].dt))
    if is_new:
        cal.add_component(ov)
    return cal.to_ical().decode("utf-8")


def delete_occurrence(raw: str, ev: Event, uid: str) -> str:
    cal, master = _load(raw, uid)
    ov = _find_override(cal, master, ev.occ_key)
    if ov is not None:
        _remove(cal, ov)
    master.add("EXDATE", ev.occ_key)
    _bump(master)
    return cal.to_ical().decode("utf-8")


# --- esta y las siguientes ----------------------------------------------------
def _until_before(key, style: str):
    if style == "date":
        return key - timedelta(days=1)
    before = key - timedelta(seconds=1)
    return before if style == "floating" else before.astimezone(timezone.utc)


def delete_following(raw: str, ev: Event, uid: str) -> str | None:
    """Corta la serie justo antes de la ocurrencia. None si es la primera: hay que borrar todo."""
    cal, master = _load(raw, uid)
    key = ev.occ_key
    if _cmp(key) <= _cmp(master["DTSTART"].dt):
        return None
    rr = master.get("RRULE")
    if rr is None:  # serie solo con RDATE: no hay regla que acortar
        return delete_occurrence(raw, ev, uid)
    for ov in _overrides(cal, master):
        if _cmp(ov["RECURRENCE-ID"].dt) >= _cmp(key):
            _remove(cal, ov)
    rr.pop("COUNT", None)
    rr["UNTIL"] = [_until_before(key, style_of(master["DTSTART"].dt))]
    _bump(master)
    return cal.to_ical().decode("utf-8")


def _count_before(master, rule: str, key) -> int:
    start = master["DTSTART"].dt
    if not isinstance(start, datetime):
        start = datetime.combine(start, time.min)
    n = 0
    for occ in du_rrule.rrulestr(rule, dtstart=start):
        if _cmp(occ) >= _cmp(key):
            break
        n += 1
    return n


def split_following(raw: str, ev: Event, uid: str, new_uid: str) -> tuple[str, str] | None:
    """Parte la serie: devuelve (serie original acortada, serie nueva desde esta ocurrencia).

    None si es la primera ocurrencia (equivale a editar toda la serie). Las excepciones
    posteriores de la serie original no pasan a la nueva.
    """
    short = delete_following(raw, ev, uid)
    if short is None:
        return None
    cal, master = _load(raw, uid)
    nv = copy.deepcopy(master)
    for k in ("RRULE", "RDATE", "EXDATE", "EXRULE", "RECURRENCE-ID", "UID"):
        nv.pop(k, None)
    nv.add("UID", new_uid)
    _set_text(nv, ev)
    style = style_of(master["DTSTART"].dt)
    _write_times(nv, ev.start, ev.end, ev.all_day, style)
    if ev.rrule:
        rr = icalendar.vRecur.from_ical(ev.rrule)
        orig = master.get("RRULE")
        if orig is not None and "COUNT" in rr and _norm(ev.rrule) == _norm(orig.to_ical().decode()):
            done = _count_before(master, ev.rrule, ev.occ_key)  # las veces que ya ocurrieron
            rr["COUNT"] = [max(int(rr["COUNT"][0]) - done, 1)]
        nv.add("RRULE", rr)
    new_cal = icalendar.Calendar()
    new_cal.add("PRODID", "-//CCAccess//ES")
    new_cal.add("VERSION", "2.0")
    new_cal.add_component(nv)
    return short, new_cal.to_ical().decode("utf-8")
