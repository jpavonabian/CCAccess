from PySide6.QtWidgets import QMessageBox, QWidget


def confirm(parent: QWidget, title: str, text: str, ok_label: str) -> bool:
    """Confirmación destructiva. El foco empieza en Cancelar y Esc cancela."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(ok_label, QMessageBox.ButtonRole.DestructiveRole)
    no = box.addButton("&Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes
