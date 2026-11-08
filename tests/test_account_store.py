import keyring
import pytest
from keyring.backend import KeyringBackend
from PySide6.QtCore import QSettings

from ccaccess.ui import account_store
from ccaccess.ui.account_store import Account, clear_account, load_account, save_account


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.data = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.data:
            raise keyring.errors.PasswordDeleteError("no existe")
        del self.data[(service, username)]


@pytest.fixture
def store(tmp_path, monkeypatch):
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    ini = str(tmp_path / "test.ini")
    monkeypatch.setattr(
        account_store, "_settings", lambda: QSettings(ini, QSettings.Format.IniFormat)
    )
    return backend


def test_save_load_clear(store):
    save_account(Account("https://x/dav/", "ana", "secreto"))
    acc = load_account()
    assert acc == Account("https://x/dav/", "ana", "secreto")
    clear_account()
    assert load_account() is None
    assert store.data == {}


def test_caldav_url_roundtrip(store):
    save_account(Account("https://contacts.icloud.com", "ana", "pw", "https://caldav.icloud.com"))
    assert load_account().caldav_url == "https://caldav.icloud.com"


def test_clear_when_empty(store):
    clear_account()  # no debe fallar
    assert load_account() is None
