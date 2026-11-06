"""Avisos para lectores de pantalla (región viva equivalente)."""
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QWidget


def announce(widget: QWidget, text: str) -> None:
    """Pide al lector de pantalla que lea `text`. Falla en silencio si Qt no lo soporta."""
    try:
        event = QAccessible.QAccessibleAnnouncementEvent(widget, text)  # Qt >= 6.8
        QAccessible.updateAccessibility(event)
    except Exception:
        try:
            QAccessible.updateAccessibility(
                QAccessible.QAccessibleEvent(widget, QAccessible.Event.Alert)
            )
        except Exception:
            pass
