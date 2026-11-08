import sys
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ccaccess.caldav_client import Event
from ccaccess.reminders import beep_wav, reminder_text
from ccaccess.ui.dialogs import EnterButton

SNOOZE, DISMISS, SHOW = "snooze", "dismiss", "show"


def play_alert() -> None:
    """Sonido corto de aviso. En Windows se genera en memoria; en otros sistemas, el pitido del sistema."""
    if sys.platform == "win32":
        try:
            import winsound

            winsound.PlaySound(beep_wav(), winsound.SND_MEMORY | winsound.SND_ASYNC)
            return
        except Exception:
            pass
    QApplication.beep()


def ask_reminder(parent: QWidget, ev: Event, now: datetime) -> tuple[str, int | None]:
    """Muestra el aviso y devuelve (acción, minutos). Esc o cerrar equivale a posponer 5 minutos."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("Aviso de evento")
    box.setText(reminder_text(ev, now))

    choices: list[tuple[str, tuple[str, int | None]]] = [
        ("&Posponer 5 minutos", (SNOOZE, 5)),
        ("Posponer 15 &minutos", (SNOOZE, 15)),
        ("Posponer 1 &hora", (SNOOZE, 60)),
    ]
    if not ev.all_day and (ev.start - now).total_seconds() > 120:
        choices.append(("Posponer hasta que &empiece", (SNOOZE, None)))
    choices += [("&Descartar", (DISMISS, None)), ("&Ver en la agenda", (SHOW, None))]

    buttons = {}
    for text, result in choices:
        btn = EnterButton(text)
        box.addButton(btn, QMessageBox.ButtonRole.ActionRole)
        buttons[btn] = result
    first = next(iter(buttons))
    box.setDefaultButton(first)
    box.setEscapeButton(first)

    play_alert()
    QApplication.alert(parent)  # parpadea en la barra de tareas si la ventana no está activa
    box.show()
    box.raise_()
    box.activateWindow()
    box.exec()
    return buttons.get(box.clickedButton(), (SNOOZE, 5))
