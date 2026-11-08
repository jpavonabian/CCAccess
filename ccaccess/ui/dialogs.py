from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget


class EnterButton(QPushButton):
    """Botón que también se activa con Intro (el estándar solo responde a Espacio)."""

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
        else:
            super().keyPressEvent(event)


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


def ask_choice(
    parent: QWidget,
    title: str,
    text: str,
    options: list[tuple[str, str]],
    destructive: bool = False,
) -> str | None:
    """Pregunta con varios botones (texto, valor) y Cancelar. Devuelve el valor, o None si se cancela.

    El foco empieza en la primera opción; si `destructive`, en Cancelar.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    choices = {}
    for label, value in options:
        btn = EnterButton(label)
        box.addButton(btn, QMessageBox.ButtonRole.ActionRole)
        choices[btn] = value
    cancel = EnterButton("&Cancelar")
    box.addButton(cancel, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel if destructive else next(iter(choices)))
    box.setEscapeButton(cancel)
    box.exec()
    return choices.get(box.clickedButton())


def ask_scope(parent: QWidget, title: str, text: str, destructive: bool = False) -> str | None:
    """Pregunta a qué parte de una serie afecta la acción: «this», «following» o «series»."""
    return ask_choice(
        parent,
        title,
        text,
        [
            ("Solo &este evento", "this"),
            ("Este y los &siguientes", "following"),
            ("Toda la se&rie", "series"),
        ],
        destructive,
    )


def report_import(parent: QWidget, say, result, singular: str, plural: str) -> None:
    """Resultado de una importación: barra de estado y, si hubo problemas, también un aviso."""
    text = result.summary(singular, plural)
    say(text)
    if result.has_problems:
        QMessageBox.warning(parent, "Importación con problemas", text)


def make_readonly_navigable(box) -> None:
    """Solo lectura pero con cursor y selección por teclado (flechas, Mayús+flechas, Ctrl+E).

    setReadOnly(True) deja solo «seleccionable con ratón»: las flechas no mueven el cursor
    y un lector de pantalla se queda en la primera línea.
    """
    box.setReadOnly(True)
    box.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
