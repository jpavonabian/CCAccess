"""Visor del manual (el README del proyecto) dentro de la aplicación."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget


def manual_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "README.md"


def manual_text() -> str:
    try:
        return manual_path().read_text(encoding="utf-8")
    except OSError:
        return "# Manual\n\nNo se encontró el archivo del manual."


class ManualDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Manual de CCAccess")
        self.resize(760, 600)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setAccessibleName("Manual")
        self.view.setMarkdown(manual_text())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("&Cerrar")
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.view)
        lay.addWidget(buttons)
        self.view.setFocus()
