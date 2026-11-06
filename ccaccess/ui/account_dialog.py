from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ccaccess.ui.account_store import Account
from ccaccess.ui.announce import announce


class AccountDialog(QDialog):
    def __init__(self, parent=None, account: Account | None = None):
        super().__init__(parent)
        self.setWindowTitle("Cuenta del servidor")
        self.setMinimumWidth(480)

        intro = QLabel(
            "Introduce los datos de tu servidor CardDAV/CalDAV "
            "(por ejemplo Nextcloud, Radicale o Baïkal)."
        )
        intro.setWordWrap(True)

        self.url = QLineEdit(account.url if account else "")
        self.url.setPlaceholderText("https://ejemplo.com/remote.php/dav")
        self.user = QLineEdit(account.username if account else "")
        self.password = QLineEdit(account.password if account else "")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setAccessibleName("Error")

        form = QFormLayout()
        for label, widget in (
            ("&URL del servidor:", self.url),
            ("&Usuario:", self.user),
            ("&Contraseña:", self.password),
        ):
            lab = QLabel(label)
            lab.setBuddy(widget)
            form.addRow(lab, widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("&Conectar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Ca&ncelar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

        self.setTabOrder(self.url, self.user)
        self.setTabOrder(self.user, self.password)

    def _validate(self) -> None:
        url = self.url.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            self._fail("La URL debe empezar por http:// o https://.", self.url)
        elif not self.user.text().strip():
            self._fail("Falta el usuario.", self.user)
        elif not self.password.text():
            self._fail("Falta la contraseña.", self.password)
        else:
            self.accept()

    def _fail(self, msg: str, widget) -> None:
        self.error.setText(f"Error: {msg}")
        announce(self.error, msg)
        QMessageBox.warning(self, "Datos incompletos", msg)
        widget.setFocus()

    def account(self) -> Account:
        return Account(self.url.text().strip(), self.user.text().strip(), self.password.text())
