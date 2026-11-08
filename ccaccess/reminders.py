"""Lógica de avisos de eventos, sin Qt: qué avisos tocan ahora y cómo se describen."""
from __future__ import annotations

import io
import math
import struct
import wave
from datetime import datetime, timedelta

from ccaccess.caldav_client import Event

# (texto, minutos). None = hasta que empiece el evento.
SNOOZE_OPTIONS: list[tuple[str, int | None]] = [
    ("5 minutos", 5),
    ("10 minutos", 10),
    ("15 minutos", 15),
    ("30 minutos", 30),
    ("1 hora", 60),
    ("Hasta que empiece", None),
]


def _key(ev: Event) -> tuple[str, datetime]:
    return ev.uid, ev.start


class ReminderTracker:
    """Recuerda qué avisos se descartaron o pospusieron (solo en memoria, no se guarda nada)."""

    def __init__(self) -> None:
        self._dismissed: set[tuple[str, datetime]] = set()
        self._snoozed: dict[tuple[str, datetime], datetime] = {}

    def due(self, events: list[Event], now: datetime) -> list[Event]:
        out = []
        for ev in events:
            if ev.alarm is None:
                continue
            key = _key(ev)
            if key in self._dismissed:
                continue
            until = self._snoozed.get(key)
            if until is not None:
                if now >= until:
                    out.append(ev)
                continue
            fire = ev.start - timedelta(minutes=ev.alarm)
            # Un aviso de un evento ya terminado no sirve; los de duración cero valen unos minutos.
            end = max(ev.end, ev.start + timedelta(minutes=5))
            if fire <= now < end:
                out.append(ev)
        out.sort(key=lambda e: (e.start, e.summary.casefold()))
        return out

    def dismiss(self, ev: Event) -> None:
        self._dismissed.add(_key(ev))
        self._snoozed.pop(_key(ev), None)

    def snooze(self, ev: Event, minutes: int | None, now: datetime) -> None:
        """Pospone `minutes` minutos; None = hasta la hora de inicio (o 1 minuto si ya empezó)."""
        if minutes is None:
            until = max(ev.start, now + timedelta(minutes=1))
        else:
            until = now + timedelta(minutes=minutes)
        self._snoozed[_key(ev)] = until


def _span(minutes: int) -> str:
    for unit, plural, size in (("día", "días", 1440), ("hora", "horas", 60)):
        if minutes >= size and minutes % size == 0:
            n = minutes // size
            return f"{n} {unit if n == 1 else plural}"
    if minutes >= 120:
        return f"{minutes // 60} horas y {minutes % 60} minutos"
    return f"{minutes} minuto" + ("" if minutes == 1 else "s")


def when_text(ev: Event, now: datetime) -> str:
    """Cuándo es el evento respecto a ahora, p. ej. «Empieza en 15 minutos»."""
    if ev.all_day:
        return f"Todo el día {ev.start:%d/%m/%Y}"
    minutes = round((ev.start - now).total_seconds() / 60)
    if minutes > 0:
        return f"Empieza en {_span(minutes)}"
    if minutes == 0:
        return "Empieza ahora"
    return f"Empezó hace {_span(-minutes)}"


def reminder_text(ev: Event, now: datetime) -> str:
    """Texto completo del diálogo de aviso."""
    lines = [ev.summary, when_text(ev, now)]
    if not ev.all_day:
        lines.append(f"De {ev.start:%d/%m/%Y %H:%M} a {ev.end:%H:%M}")
    if ev.location:
        lines.append(f"Lugar: {ev.location}")
    if ev.calendar:
        lines.append(f"Calendario: {ev.calendar}")
    return "\n".join(lines)


def beep_wav() -> bytes:
    """Dos tonos cortos y suaves en formato WAV, generados al vuelo (no hay archivos de sonido)."""
    rate = 22050
    frames = bytearray()
    for freq, dur in ((880, 0.16), (0, 0.06), (1175, 0.22)):
        n = int(rate * dur)
        for i in range(n):
            fade = min(1.0, i / 200, (n - i) / 400)  # sin chasquidos al empezar y acabar
            v = 0 if freq == 0 else int(9000 * fade * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", v)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()
