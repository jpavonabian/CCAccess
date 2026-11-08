"""Fixtures compartidos: un servidor CalDAV/CardDAV real (Radicale) en localhost.

Radicale es solo dependencia de desarrollo (requirements-dev.txt); sin él, los tests que lo usan se omiten.
"""
import socket
import subprocess
import sys
import time

import pytest
import requests

AUTH = ("ana", "x")


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    pytest.importorskip("radicale")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    folder = tmp_path_factory.mktemp("radicale")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "radicale",
            "--hosts", f"127.0.0.1:{port}",
            "--auth-type", "none",
            "--storage-filesystem-folder", str(folder),
            "--logging-level", "error",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                requests.get(url, timeout=0.5)
                break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            pytest.fail("Radicale no arrancó")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _unique(request) -> str:
    return "t" + str(abs(hash(request.node.name)))


@pytest.fixture
def cal(server, request):
    """Un calendario vacío y propio de cada test."""
    from ccaccess.caldav_client import CalDavClient

    name = _unique(request)
    body = (
        '<c:mkcalendar xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:"><d:set><d:prop>'
        f"<d:displayname>{name}</d:displayname></d:prop></d:set></c:mkcalendar>"
    )
    r = requests.request("MKCALENDAR", f"{server}/ana/{name}/", data=body, auth=AUTH)
    assert r.status_code in (200, 201), r.text
    client = CalDavClient(f"{server}/ana/", *AUTH)
    cals = [c for c in client.discover_calendars() if c.name == name]
    assert cals, "el cliente no encuentra el calendario recién creado"
    return client, cals[0]


@pytest.fixture
def book(server, request):
    """Una libreta de direcciones vacía y propia de cada test."""
    from ccaccess.carddav import CardDavClient

    name = "b" + _unique(request)
    body = (
        '<d:mkcol xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:set><d:prop>'
        "<d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>"
        f"<d:displayname>{name}</d:displayname></d:prop></d:set></d:mkcol>"
    )
    r = requests.request("MKCOL", f"{server}/ana/{name}/", data=body, auth=AUTH)
    assert r.status_code in (200, 201), r.text
    client = CardDavClient(f"{server}/ana/", *AUTH)
    books = [b for b in client.discover_addressbooks() if b.name == name]
    assert books, "el cliente no encuentra la libreta recién creada"
    return client, books[0]
