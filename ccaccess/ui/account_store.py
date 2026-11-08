"""Guarda la cuenta: URL y usuario en QSettings, contraseña en el llavero del sistema."""
from dataclasses import dataclass

import keyring
import keyring.errors
from PySide6.QtCore import QSettings

SERVICE = "CCAccess"


@dataclass
class Account:
    url: str
    username: str
    password: str
    caldav_url: str = ""  # vacía = deducirla de `url`


def _settings() -> QSettings:
    return QSettings("CCAccess", "CCAccess")


def load_account() -> Account | None:
    s = _settings()
    url = s.value("account/url", "")
    user = s.value("account/username", "")
    if not url or not user:
        return None
    pw = keyring.get_password(SERVICE, f"{user}@{url}") or ""
    return Account(url, user, pw, s.value("account/caldav_url", "") or "")


def clear_account() -> None:
    """Borra del disco la URL, el usuario y la contraseña guardados."""
    s = _settings()
    url = s.value("account/url", "")
    user = s.value("account/username", "")
    if url and user:
        try:
            keyring.delete_password(SERVICE, f"{user}@{url}")
        except keyring.errors.PasswordDeleteError:
            pass  # no había contraseña guardada
    s.clear()
    s.sync()


def save_account(acc: Account) -> None:
    s = _settings()
    s.setValue("account/url", acc.url)
    s.setValue("account/username", acc.username)
    s.setValue("account/caldav_url", acc.caldav_url)
    keyring.set_password(SERVICE, f"{acc.username}@{acc.url}", acc.password)
