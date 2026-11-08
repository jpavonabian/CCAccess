"""Cliente CalDAV mínimo (solo lectura), sin dependencias de Qt."""
from __future__ import annotations

from dataclasses import dataclass, replace
import uuid
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import icalendar
import recurring_ical_events

from ccaccess.carddav import NS
from ccaccess.carddav import CardDavClient, DavError



@dataclass
class Calendar:
    url: str
    name: str


@dataclass
class Event:
    uid: str
    summary: str
    start: datetime  # hora local, sin zona (para eventos de día completo: 00:00)
    end: datetime
    all_day: bool
    location: str = ""
    description: str = ""
    calendar: str = ""
    href: str = ""
    etag: str = ""
    raw: str = ""  # iCalendar original, para conservar lo que la app no edita
    recurring: bool = False
    alarm: int | None = None  # minutos antes del inicio del primer aviso; None = sin aviso
    rrule: str = ""  # regla de repetición de la serie (RRULE), vacía si no se repite
    # Solo en ocurrencias leídas del servidor: identifican qué ocurrencia es y su horario original.
    occ_key: object = None  # RECURRENCE-ID de la ocurrencia (fecha o datetime, con su zona)
    occ_start: datetime | None = None
    occ_end: datetime | None = None
    is_exception: bool = False  # la ocurrencia tiene su propio VEVENT dentro de la serie
    scope: str = ""  # al guardar una serie: "this", "following" o "" (= toda la serie)


# Proveedores cuyo servidor de calendarios está en otro host que el de contactos.
KNOWN_CALDAV_HOSTS = {"contacts.icloud.com": "caldav.icloud.com"}


def caldav_url_from(url: str) -> str:
    """Deduce la URL de calendarios a partir de la de contactos."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in KNOWN_CALDAV_HOSTS:
        return urlunsplit(parts._replace(netloc=KNOWN_CALDAV_HOSTS[host] + (f":{parts.port}" if parts.port else "")))
    if "/carddav" in url:
        return url.replace("/carddav", "/caldav", 1)
    return url


def alarm_label(minutes: int | None) -> str:
    """Texto hablado de un aviso, p. ej. «15 minutos antes»."""
    if minutes is None:
        return "Sin aviso"
    if minutes == 0:
        return "En el momento del evento"
    for unit, size in (("semana", 10080), ("día", 1440), ("hora", 60), ("minuto", 1)):
        if minutes % size == 0:
            n = minutes // size
            plural = {"semana": "semanas", "día": "días", "hora": "horas", "minuto": "minutos"}[unit]
            return f"{n} {unit if n == 1 else plural} antes"
    return f"{minutes} minutos antes"


def _start_alarm(vevent):
    """Primer VALARM con disparo relativo al inicio y anterior (o igual) a él, o None."""
    for sub in vevent.subcomponents:
        if sub.name != "VALARM":
            continue
        trig = sub.get("TRIGGER")
        if trig is None or not isinstance(trig.dt, timedelta) or trig.dt > timedelta(0):
            continue
        if str(trig.params.get("RELATED", "START")).upper() == "END":
            continue
        return sub
    return None


def _alarm_minutes(vevent) -> int | None:
    sub = _start_alarm(vevent)
    if sub is None:
        return None
    return int(-sub.get("TRIGGER").dt.total_seconds() // 60)


def _same_instant(a, b) -> bool:
    """Compara dos valores de fecha/hora de iCalendar (fecha, flotante o con zona)."""
    if isinstance(a, datetime) != isinstance(b, datetime):
        return False
    if isinstance(a, datetime) and (a.tzinfo is None) != (b.tzinfo is None):
        return a.replace(tzinfo=None) == b.replace(tzinfo=None)
    return a == b


def _to_local(value) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value, False
    return datetime.combine(value, time.min), True


def parse_events(
    ics: str, start: datetime, end: datetime, calendar: str = "", href: str = "", etag: str = ""
) -> list[Event]:
    """Lee un iCalendar y devuelve sus eventos entre start y end, con recurrencias expandidas."""
    try:
        cal = icalendar.Calendar.from_ical(ics)
    except Exception:
        return []
    out: list[Event] = []
    masters = {
        str(c.get("UID", "")): c
        for c in cal.walk("VEVENT")
        if c.get("RECURRENCE-ID") is None
    }
    overrides = [
        (str(c.get("UID", "")), c["RECURRENCE-ID"].dt)
        for c in cal.walk("VEVENT")
        if c.get("RECURRENCE-ID") is not None
    ]
    recurring_uids = {
        str(c.get("UID", ""))
        for c in cal.walk("VEVENT")
        if c.get("RRULE") is not None or c.get("RDATE") is not None or c.get("RECURRENCE-ID") is not None
    }
    try:
        comps = recurring_ical_events.of(cal).between(start, end)
    except Exception:
        return []
    for comp in comps:
        if comp.name != "VEVENT" or comp.get("DTSTART") is None:
            continue
        s, all_day = _to_local(comp.get("DTSTART").dt)
        if comp.get("DTEND") is not None:
            e, _ = _to_local(comp.get("DTEND").dt)
        elif comp.get("DURATION") is not None:
            e = s + comp.get("DURATION").dt
        else:
            e = s + (timedelta(days=1) if all_day else timedelta())
        uid = str(comp.get("UID", ""))
        is_rec = uid in recurring_uids
        key = comp["RECURRENCE-ID"].dt if comp.get("RECURRENCE-ID") is not None else comp["DTSTART"].dt
        master = masters.get(uid)
        rrule = ""
        if is_rec and master is not None and master.get("RRULE") is not None:
            rrule = master["RRULE"].to_ical().decode()
        out.append(
            Event(
                uid=uid,
                summary=str(comp.get("SUMMARY", "")).strip() or "(sin título)",
                start=s,
                end=e,
                all_day=all_day,
                location=str(comp.get("LOCATION", "")).strip(),
                description=str(comp.get("DESCRIPTION", "")).strip(),
                calendar=calendar,
                href=href,
                etag=etag,
                raw=ics,
                recurring=is_rec,
                alarm=_alarm_minutes(comp),
                rrule=rrule,
                occ_key=key if is_rec else None,
                occ_start=s,
                occ_end=e,
                is_exception=is_rec and any(u == uid and _same_instant(k, key) for u, k in overrides),
            )
        )
    out.sort(key=lambda ev: (ev.start, ev.summary.casefold()))
    return out


class CalDavClient(CardDavClient):
    """Reutiliza la parte HTTP/WebDAV de CardDavClient."""

    def discover_calendars(self) -> list[Calendar]:
        info_xml = (
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><d:resourcetype/><d:displayname/>"
            "<d:current-user-principal/><c:calendar-home-set/>"
            "</d:prop></d:propfind>"
        )
        start, root = self._propfind_start(info_xml, "caldav")

        for resp in root.findall("d:response", NS):
            if resp.find(".//cal:calendar", NS) is not None:
                dn = resp.find(".//d:displayname", NS)
                name = dn.text.strip() if dn is not None and dn.text else "Calendario"
                return [Calendar(start, name)]

        home = self._href(root, ".//cal:calendar-home-set/d:href")
        home_url = urljoin(start, home) if home else None
        if not home_url:
            principal = self._href(root, ".//d:current-user-principal/d:href")
            if principal:
                purl = urljoin(start, principal)
                hx = (
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    "<d:prop><c:calendar-home-set/></d:prop></d:propfind>"
                )
                proot = self._try("PROPFIND", purl, hx)
                h = self._href(proot, ".//cal:calendar-home-set/d:href") if proot is not None else None
                if h:
                    home_url = urljoin(purl, h)
        if not home_url:
            home_url = start

        list_xml = (
            '<d:propfind xmlns:d="DAV:"><d:prop>'
            "<d:resourcetype/><d:displayname/></d:prop></d:propfind>"
        )
        root = self._request("PROPFIND", home_url, list_xml, depth="1")
        cals = []
        for resp in root.findall("d:response", NS):
            if resp.find(".//cal:calendar", NS) is None:
                continue
            href = self._href(resp, "d:href")
            if not href:
                continue
            dn = resp.find(".//d:displayname", NS)
            name = dn.text.strip() if dn is not None and dn.text else href.rstrip("/").split("/")[-1]
            cals.append(Calendar(urljoin(home_url, href), name))
        return cals

    def fetch_events(self, cal: Calendar, start: datetime, end: datetime) -> list[Event]:
        def utc(dt: datetime) -> str:
            return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        query = (
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
            '<c:filter><c:comp-filter name="VCALENDAR">'
            '<c:comp-filter name="VEVENT">'
            f'<c:time-range start="{utc(start)}" end="{utc(end)}"/>'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        root = self._request("REPORT", cal.url, query, depth="1")
        events: list[Event] = []
        for resp in root.findall("d:response", NS):
            data = resp.find(".//cal:calendar-data", NS)
            if data is None or not data.text:
                continue
            href = self._href(resp, "d:href") or ""
            etag_el = resp.find(".//d:getetag", NS)
            etag = etag_el.text.strip() if etag_el is not None and etag_el.text else ""
            events += parse_events(data.text, start, end, cal.name, urljoin(cal.url, href), etag)
        events.sort(key=lambda ev: (ev.start, ev.summary.casefold()))
        return events

    def save_event(self, cal: Calendar, ev: Event) -> None:
        """Crea el evento (si no tiene href) o actualiza el existente."""
        if ev.href:
            if ev.recurring and ev.scope == "following":
                return self._save_following(ev)
            self._put(ev.href, build_ics(ev, ev.uid), "text/calendar", etag=ev.etag)
        else:
            uid = str(uuid.uuid4())
            base = cal.url if cal.url.endswith("/") else cal.url + "/"
            self._put(urljoin(base, f"{uid}.ics"), build_ics(ev, uid), "text/calendar", new=True)

    def import_event(self, cal: Calendar, uid: str, ics: str) -> None:
        """Crea un evento ya escrito (importación). Falla con DavConflict si ese UID ya existe."""
        from ccaccess.exchange import safe_name

        base = cal.url if cal.url.endswith("/") else cal.url + "/"
        self._put(urljoin(base, safe_name(uid, ".ics")), ics, "text/calendar", new=True)

    def fetch_raw(self, cal: Calendar) -> list[str]:
        """Todos los eventos del calendario tal como están en el servidor (series sin expandir)."""
        query = (
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/>'
            "</c:comp-filter></c:filter></c:calendar-query>"
        )
        root = self._request("REPORT", cal.url, query, depth="1")
        out = []
        for resp in root.findall("d:response", NS):
            data = resp.find(".//cal:calendar-data", NS)
            if data is not None and data.text:
                out.append(data.text)
        return out

    def _save_following(self, ev: Event) -> None:
        """Cambia esta ocurrencia y las siguientes: acorta la serie y crea otra desde aquí."""
        from ccaccess.recurrence import split_following

        new_uid = str(uuid.uuid4())
        parts = split_following(ev.raw, ev, ev.uid, new_uid)
        if parts is None:  # es la primera: lo mismo que editar toda la serie
            ics = build_ics(replace(ev, scope=""), ev.uid)
            return self._put(ev.href, ics, "text/calendar", etag=ev.etag)
        short_ics, new_ics = parts
        new_href = urljoin(ev.href, f"{new_uid}.ics")
        self._put(new_href, new_ics, "text/calendar", new=True)
        try:
            self._put(ev.href, short_ics, "text/calendar", etag=ev.etag)
        except DavError:
            try:  # que no queden las dos series solapadas
                self._delete(new_href)
            except DavError:
                pass
            raise

    def delete_event(self, ev: Event, scope: str = "") -> None:
        """Borra el evento. En series, scope es «this» (una ocurrencia), «following» o «» (todo)."""
        if not ev.recurring or scope not in ("this", "following"):
            return self._delete(ev.href, ev.etag)
        from ccaccess.recurrence import delete_following, delete_occurrence

        fn = delete_occurrence if scope == "this" else delete_following
        ics = fn(ev.raw, ev, ev.uid)
        if ics is None:  # era la primera ocurrencia: no queda nada
            return self._delete(ev.href, ev.etag)
        self._put(ev.href, ics, "text/calendar", etag=ev.etag)


def _set_start_alarm(vevent, ev: Event) -> None:
    """Pone, cambia o quita el aviso relativo al inicio; no toca el resto de VALARM."""
    current = _start_alarm(vevent)
    if _alarm_minutes(vevent) == ev.alarm:
        return
    if ev.alarm is None:
        vevent.subcomponents.remove(current)
        return
    trigger = -timedelta(minutes=ev.alarm)
    if current is not None:
        current.pop("TRIGGER", None)
        current.add("TRIGGER", trigger)
        return
    alarm = icalendar.Alarm()
    alarm.add("ACTION", "DISPLAY")
    alarm.add("DESCRIPTION", ev.summary)
    alarm.add("TRIGGER", trigger)
    vevent.add_component(alarm)


def build_ics(ev: Event, uid: str) -> str:
    """Genera el iCalendar de `ev`. Si tiene `raw`, parte de él y conserva el resto de campos."""
    now = datetime.now(timezone.utc)
    if ev.raw and ev.recurring:
        from ccaccess.recurrence import edit_occurrence, edit_series

        return (edit_occurrence if ev.scope == "this" else edit_series)(ev.raw, ev, uid)
    if ev.raw:
        cal = icalendar.Calendar.from_ical(ev.raw)
        masters = [
            c
            for c in cal.walk("VEVENT")
            if c.get("RECURRENCE-ID") is None and str(c.get("UID", "")) == uid
        ]
        vevent = masters[0] if masters else cal.walk("VEVENT")[0]
        seq = int(vevent.get("SEQUENCE", 0)) + 1
        for key in ("SEQUENCE", "DTSTAMP", "SUMMARY", "LOCATION", "DESCRIPTION"):
            vevent.pop(key, None)
        vevent.add("SEQUENCE", seq)
    else:
        cal = icalendar.Calendar()
        cal.add("PRODID", "-//CCAccess//ES")
        cal.add("VERSION", "2.0")
        vevent = icalendar.Event()
        vevent.add("UID", uid)
        cal.add_component(vevent)
    vevent.add("DTSTAMP", now)
    vevent.add("SUMMARY", ev.summary)
    _set_start_alarm(vevent, ev)
    if ev.location:
        vevent.add("LOCATION", ev.location)
    if ev.description:
        vevent.add("DESCRIPTION", ev.description)
    for key in ("DTSTART", "DTEND", "DURATION"):
        vevent.pop(key, None)
    if ev.all_day:
        vevent.add("DTSTART", ev.start.date())
        vevent.add("DTEND", ev.end.date())
    else:
        vevent.add("DTSTART", ev.start.astimezone(timezone.utc))
        vevent.add("DTEND", ev.end.astimezone(timezone.utc))
    vevent.pop("RRULE", None)
    if ev.rrule:  # evento nuevo (o sin repetición) al que se le pone una regla
        vevent.add("RRULE", icalendar.vRecur.from_ical(ev.rrule))
    return cal.to_ical().decode("utf-8")


__all__ = ["Calendar", "Event", "CalDavClient", "DavError", "parse_events", "caldav_url_from", "build_ics", "alarm_label"]
