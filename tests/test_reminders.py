import io
import wave
from datetime import datetime, timedelta

from ccaccess.caldav_client import Event
from ccaccess.reminders import ReminderTracker, beep_wav, reminder_text, when_text

T0 = datetime(2026, 3, 10, 10, 0)


def ev(alarm=15, start=T0, minutes=60, uid="u1", all_day=False):
    return Event(uid, "Cita", start, start + timedelta(minutes=minutes), all_day, alarm=alarm, location="Sala 2")


def test_due_window():
    t = ReminderTracker()
    e = ev()
    assert t.due([e], T0 - timedelta(minutes=16)) == []
    assert t.due([e], T0 - timedelta(minutes=15)) == [e]
    assert t.due([e], T0 + timedelta(minutes=30)) == [e]  # ya empezó pero no ha acabado
    assert t.due([e], T0 + timedelta(minutes=60)) == []  # terminado
    assert t.due([ev(alarm=None)], T0) == []


def test_dismiss_and_snooze():
    t = ReminderTracker()
    e = ev()
    now = T0 - timedelta(minutes=10)
    t.snooze(e, 5, now)
    assert t.due([e], now + timedelta(minutes=4)) == []
    assert t.due([e], now + timedelta(minutes=5)) == [e]
    t.dismiss(e)
    assert t.due([e], now + timedelta(minutes=6)) == []
    # otra ocurrencia de la misma serie sigue avisando
    other = ev(start=T0 + timedelta(days=7))
    assert t.due([other], other.start - timedelta(minutes=1)) == [other]


def test_snooze_until_start():
    t = ReminderTracker()
    e = ev()
    now = T0 - timedelta(minutes=10)
    t.snooze(e, None, now)
    assert t.due([e], T0 - timedelta(minutes=1)) == []
    assert t.due([e], T0) == [e]
    t2 = ReminderTracker()
    t2.snooze(e, None, T0 + timedelta(minutes=5))  # ya empezado: vuelve en 1 minuto
    assert t2.due([e], T0 + timedelta(minutes=5, seconds=30)) == []
    assert t2.due([e], T0 + timedelta(minutes=6)) == [e]


def test_zero_length_event_still_fires_after_start():
    t = ReminderTracker()
    e = ev(alarm=0, minutes=0)
    assert t.due([e], T0 + timedelta(minutes=2)) == [e]


def test_texts():
    assert when_text(ev(), T0 - timedelta(minutes=15)) == "Empieza en 15 minutos"
    assert when_text(ev(), T0 - timedelta(minutes=1)) == "Empieza en 1 minuto"
    assert when_text(ev(), T0 - timedelta(hours=2)) == "Empieza en 2 horas"
    assert when_text(ev(), T0) == "Empieza ahora"
    assert when_text(ev(), T0 + timedelta(minutes=3)) == "Empezó hace 3 minutos"
    assert when_text(ev(all_day=True), T0) == "Todo el día 10/03/2026"
    txt = reminder_text(ev(), T0 - timedelta(minutes=15))
    assert "Cita" in txt and "Lugar: Sala 2" in txt and "10:00 a 11:00" in txt


def test_beep_is_valid_wav():
    with wave.open(io.BytesIO(beep_wav())) as w:
        assert w.getnchannels() == 1 and w.getnframes() > 1000
