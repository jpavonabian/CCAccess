"""Punto de entrada para PyInstaller y para ejecutar desde el código fuente."""
import sys


def selftest() -> int:
    """Comprueba en el .exe empaquetado que el llavero y Qt cargan. Uso: CCAccess.exe --selftest"""
    import keyring
    from PySide6.QtCore import QSettings  # noqa: F401

    import ccaccess.caldav_client  # noqa: F401
    import ccaccess.carddav  # noqa: F401

    backend = keyring.get_keyring()
    print("llavero:", type(backend).__module__, type(backend).__name__)
    return 0 if "fail" not in type(backend).__module__ else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from ccaccess.ui.app import run

    sys.exit(run())
