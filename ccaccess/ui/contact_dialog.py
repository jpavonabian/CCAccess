from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ccaccess.carddav import Contact


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


class ContactDialog(QDialog):
    def __init__(self, parent=None, contact: Contact | None = None):
        super().__init__(parent)
        self._base = contact or Contact("", "", "")
        self.setWindowTitle("Editar contacto" if contact else "Nuevo contacto")
        self.setMinimumWidth(480)

        self.name = QLineEdit(self._base.name)
        self.phones = QPlainTextEdit("\n".join(self._base.phones))
        self.emails = QPlainTextEdit("\n".join(self._base.emails))
        self.org = QLineEdit(self._base.org)
        self.note = QPlainTextEdit(self._base.note)
        for box in (self.phones, self.emails, self.note):
            box.setTabChangesFocus(True)
        self.phones.setFixedHeight(80)
        self.emails.setFixedHeight(80)

        form = QFormLayout()
        for text, widget in (
            ("&Nombre completo:", self.name),
            ("&Teléfonos (uno por línea):", self.phones),
            ("C&orreos (uno por línea):", self.emails),
            ("Organi&zación:", self.org),
            ("Not&a:", self.note),
        ):
            lab = QLabel(text)
            lab.setBuddy(widget)
            form.addRow(lab, widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("&Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _validate(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Datos incompletos", "Falta el nombre del contacto.")
            self.name.setFocus()
            return
        self.accept()

    def contact(self) -> Contact:
        return replace(
            self._base,
            name=self.name.text().strip(),
            phones=_lines(self.phones.toPlainText()),
            emails=_lines(self.emails.toPlainText()),
            org=self.org.text().strip(),
            note=self.note.toPlainText().strip(),
        )
