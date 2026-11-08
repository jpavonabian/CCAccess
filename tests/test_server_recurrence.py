"""Prueba las series contra un servidor CalDAV real (Radicale) levantado en localhost.

El servidor y los calendarios salen de tests/conftest.py. Se omite si Radicale no está instalado.
"""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

pytest.importorskip("radicale")

from ccaccess.caldav_client import DavError, Event  # noqa: E402
from ccaccess.recurrence import RepeatSpec, build_rrule  # noqa: E402

START = datetime(2026, 3, 1).astimezone()
END = datetime(2026, 5, 1).astimezone()


def events(client, calendar):
    return client.fetch_events(calendar, START, END)


def new_series(client, calendar, rule, title="Serie", start=datetime(2026, 3, 2, 9), hours=1):
    ev = Event("", title, start, start + timedelta(hours=hours), False, rrule=rule, alarm=10)
    client.save_event(calendar, ev)
    return events(client, calendar)


def days(evs):
    return [(e.start.day, e.start.hour) for e in evs]


def test_discovery_and_create_series(cal):
    client, calendar = cal
    evs = new_series(client, calendar, build_rrule(RepeatSpec("WEEKLY", days=("MO", "WE"), count=6), "utc"))
    assert len(evs) == 6 and all(e.recurring for e in evs)
    assert evs[0].alarm == 10
    assert [d for d, _ in days(evs)] == [2, 4, 9, 11, 16, 18]
    assert evs[0].rrule.startswith("FREQ=WEEKLY") and not any(e.is_exception for e in evs)


def test_edit_whole_series_moves_it(cal):
    client, calendar = cal
    evs = new_series(client, calendar, "FREQ=DAILY;COUNT=4")
    ev = evs[1]  # 3 de marzo
    client.save_event(
        None,
        replace(ev, summary="Movida", start=ev.start + timedelta(hours=3), end=ev.end + timedelta(hours=3)),
    )
    after = events(client, calendar)
    assert [e.summary for e in after] == ["Movida"] * 4
    assert days(after) == [(2, 12), (3, 12), (4, 12), (5, 12)]


def test_edit_only_one_occurrence(cal):
    client, calendar = cal
    ev = new_series(client, calendar, "FREQ=DAILY;COUNT=4")[2]  # 4 de marzo
    client.save_event(
        None,
        replace(ev, scope="this", summary="Solo hoy", start=ev.start.replace(hour=17), end=ev.end.replace(hour=18)),
    )
    after = events(client, calendar)
    assert [e.summary for e in after] == ["Serie", "Serie", "Solo hoy", "Serie"]
    assert days(after)[2] == (4, 17) and after[2].is_exception and not after[1].is_exception
    # volver a editar la excepción desde el servidor no crea otra
    client.save_event(None, replace(after[2], scope="this", summary="Otra vez"))
    final = events(client, calendar)
    assert [e.summary for e in final] == ["Serie", "Serie", "Otra vez", "Serie"]


def test_delete_one_occurrence_and_exception(cal):
    client, calendar = cal
    evs = new_series(client, calendar, "FREQ=DAILY;COUNT=5")
    client.delete_event(evs[1], "this")
    after = events(client, calendar)
    assert [d for d, _ in days(after)] == [2, 4, 5, 6]
    client.save_event(None, replace(after[1], scope="this", summary="Excepción"))
    exc = events(client, calendar)[1]
    assert exc.is_exception
    client.delete_event(exc, "this")
    assert [d for d, _ in days(events(client, calendar))] == [2, 5, 6]


def test_delete_following_and_all(cal):
    client, calendar = cal
    evs = new_series(client, calendar, "FREQ=DAILY;COUNT=6")
    client.delete_event(evs[3], "following")  # desde el 5
    assert [d for d, _ in days(events(client, calendar))] == [2, 3, 4]
    client.delete_event(events(client, calendar)[0], "following")  # desde la primera: todo
    assert events(client, calendar) == []
    evs = new_series(client, calendar, "FREQ=DAILY;COUNT=3")
    client.delete_event(evs[1], "")
    assert events(client, calendar) == []


def test_edit_this_and_following_splits_series(cal):
    client, calendar = cal
    evs = new_series(client, calendar, "FREQ=DAILY;COUNT=6")
    ev = evs[3]  # 5 de marzo: quedan 3
    client.save_event(
        None,
        replace(ev, scope="following", summary="Nueva", start=ev.start.replace(hour=18), end=ev.end.replace(hour=19)),
    )
    after = events(client, calendar)
    assert [(e.summary, e.start.day, e.start.hour) for e in after] == [
        ("Serie", 2, 9), ("Serie", 3, 9), ("Serie", 4, 9),
        ("Nueva", 5, 18), ("Nueva", 6, 18), ("Nueva", 7, 18),
    ]
    assert len({e.uid for e in after}) == 2
    # la primera ocurrencia «y siguientes» equivale a editar toda la serie
    first = events(client, calendar)[0]
    client.save_event(None, replace(first, scope="following", summary="Todo"))
    assert [e.summary for e in events(client, calendar)][:3] == ["Todo"] * 3


def test_change_rule_and_stop_repeating(cal):
    client, calendar = cal
    ev = new_series(client, calendar, "FREQ=DAILY;COUNT=4")[0]
    client.save_event(None, replace(ev, rrule="FREQ=DAILY;INTERVAL=2;COUNT=3"))
    assert [d for d, _ in days(events(client, calendar))] == [2, 4, 6]
    client.save_event(None, replace(events(client, calendar)[0], rrule=""))
    after = events(client, calendar)
    assert len(after) == 1 and not after[0].recurring


def test_add_rule_to_single_event(cal):
    client, calendar = cal
    client.save_event(calendar, Event("", "Suelto", datetime(2026, 3, 10, 8), datetime(2026, 3, 10, 9), False))
    ev = events(client, calendar)[0]
    assert not ev.recurring
    client.save_event(None, replace(ev, rrule="FREQ=WEEKLY;COUNT=3"))
    assert [d for d, _ in days(events(client, calendar))] == [10, 17, 24]


def test_all_day_series_on_server(cal):
    client, calendar = cal
    client.save_event(
        calendar,
        Event("", "Basura", datetime(2026, 3, 3), datetime(2026, 3, 4), True,
              rrule=build_rrule(RepeatSpec("WEEKLY", until=datetime(2026, 3, 24).date()), "date")),
    )
    evs = events(client, calendar)
    assert [e.start.day for e in evs] == [3, 10, 17, 24] and all(e.all_day for e in evs)
    client.delete_event(evs[1], "this")
    assert [e.start.day for e in events(client, calendar)] == [3, 17, 24]


def test_stale_etag_is_rejected(cal):
    client, calendar = cal
    evs = new_series(client, calendar, "FREQ=DAILY;COUNT=3")
    client.save_event(None, replace(evs[0], summary="Primero"))
    with pytest.raises(DavError):  # el ETag de `evs` ya no es el del servidor
        client.delete_event(evs[1], "this")
    with pytest.raises(DavError):
        client.save_event(None, replace(evs[1], scope="following", summary="X"))
    assert [e.summary for e in events(client, calendar)] == ["Primero"] * 3  # nada a medias
