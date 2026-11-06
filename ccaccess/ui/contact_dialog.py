from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ccaccess.carddav import Contact
from ccaccess.vcard_form import ContactForm, date_from_text, form_from_vcard, split_typed


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


class ContactDialog(QDialog):
    """Editor con todos los campos del contacto, repartidos en pestañas."""

    def __init__(self, parent=None, contact: Contact | None = None):
        super().__init__(parent)
        self._base = contact or Contact("", "", "")
        try:
            self._orig = form_from_vcard(self._base.raw)
        except Exception:
            self._orig = ContactForm()
        f = self._orig
        if not self._base.raw and contact is not None:  # contacto sin vCard original
            f = ContactForm(
                fullname=contact.name, org=contact.org, note=contact.note,
                phones=list(contact.phones), emails=list(contact.emails),
            )
            self._orig = f
        self.setWindowTitle("Editar contacto" if contact else "Nuevo contacto")
        self.setMinimumWidth(560)

        def line(text: str) -> QLineEdit:
            return QLineEdit(text)

        def multi(lines: list[str], rows: int = 3) -> QPlainTextEdit:
            box = QPlainTextEdit("\n".join(lines))
            box.setTabChangesFocus(True)
            box.setFixedHeight(box.fontMetrics().lineSpacing() * rows + 16)
            return box

        self.fullname = line(f.fullname)
        self.prefix = line(f.prefix)
        self.given = line(f.given)
        self.additional = line(f.additional)
        self.family = line(f.family)
        self.suffix = line(f.suffix)
        self.nickname = line(f.nickname)
        self.org = line(f.org)
        self.title = line(f.title)
        self.role = line(f.role)
        self.phones = multi(f.phones)
        self.emails = multi(f.emails)
        self.addresses = multi(f.addresses)
        self.urls = multi(f.urls, 2)
        self.impps = multi(f.impps, 2)
        self.birthday = line(f.birthday)
        self.anniversary = line(f.anniversary)
        self.categories = line(f.categories)
        self.note = QPlainTextEdit(f.note)
        self.note.setTabChangesFocus(True)

        tabs = QTabWidget()
        tabs.addTab(
            self._page(
                ("&Nombre completo:", self.fullname),
                ("Pre&fijo (Dr., Sra.…):", self.prefix),
                ("N&ombre de pila:", self.given),
                ("&Segundo nombre:", self.additional),
                ("&Apellidos:", self.family),
                ("S&ufijo (Jr.…):", self.suffix),
                ("A&podo:", self.nickname),
            ),
            "&Nombre",
        )
        tabs.addTab(
            self._page(
                ("Organi&zación:", self.org),
                ("&Cargo:", self.title),
                ("&Función:", self.role),
                ("&Teléfonos (uno por línea, p. ej. «móvil: 600 000 000»):", self.phones),
                ("Co&rreos (uno por línea, p. ej. «trabajo: a@b.com»):", self.emails),
                ("&Direcciones (una por línea: calle; ciudad; región; código postal; país):", self.addresses),
                ("&Webs (una por línea):", self.urls),
                ("&Mensajería (una por línea, p. ej. «xmpp:usuario@servidor»):", self.impps),
            ),
            "&Contacto",
        )
        tabs.addTab(
            self._page(
                ("&Cumpleaños (dd/mm/aaaa):", self.birthday),
                ("&Aniversario (dd/mm/aaaa):", self.anniversary),
                ("Cate&gorías (separadas por comas):", self.categories),
                ("Not&a:", self.note),
            ),
            "&Más datos",
        )
        self.tabs = tabs

        hint = QLabel(
            "Tipos de teléfono, correo y dirección: móvil, casa, trabajo, fax, voz, sms, otro. "
            "Se pueden combinar con comas, por ejemplo «casa, fax: 910 000 000»."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("&Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(hint)
        lay.addWidget(buttons)
        self.fullname.setFocus()

    @staticmethod
    def _page(*rows) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for text, widget in rows:
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setBuddy(widget)
            form.addRow(lab, widget)
        return page

    def form(self) -> ContactForm:
        return ContactForm(
            fullname=self.fullname.text().strip(),
            prefix=self.prefix.text().strip(),
            given=self.given.text().strip(),
            additional=self.additional.text().strip(),
            family=self.family.text().strip(),
            suffix=self.suffix.text().strip(),
            nickname=self.nickname.text().strip(),
            org=self.org.text().strip(),
            title=self.title.text().strip(),
            role=self.role.text().strip(),
            phones=_lines(self.phones.toPlainText()),
            emails=_lines(self.emails.toPlainText()),
            addresses=_lines(self.addresses.toPlainText()),
            urls=_lines(self.urls.toPlainText()),
            impps=_lines(self.impps.toPlainText()),
            birthday=self.birthday.text().strip(),
            anniversary=self.anniversary.text().strip(),
            categories=self.categories.text().strip(),
            note=self.note.toPlainText().strip(),
        )

    def _fail(self, msg: str, tab: int, widget: QWidget) -> None:
        QMessageBox.warning(self, "Datos incorrectos", msg)
        self.tabs.setCurrentIndex(tab)
        widget.setFocus()

    def _validate(self) -> None:
        f = self.form()
        if not (f.fullname or f.given or f.family):
            return self._fail("Falta el nombre del contacto.", 0, self.fullname)
        for text, orig, widget, label in (
            (f.birthday, self._orig.birthday, self.birthday, "cumpleaños"),
            (f.anniversary, self._orig.anniversary, self.anniversary, "aniversario"),
        ):
            if text and text != orig:
                try:
                    date_from_text(text)
                except ValueError:
                    return self._fail(
                        f"La fecha de {label} no es válida. Usa dd/mm/aaaa, por ejemplo 25/12/1990.", 2, widget
                    )
        self.accept()

    def contact(self) -> Contact:
        f = self.form()
        name = f.fullname or " ".join(p for p in (f.prefix, f.given, f.additional, f.family, f.suffix) if p)
        return replace(
            self._base,
            name=name,
            phones=[split_typed(ln)[1] for ln in f.phones],
            emails=[split_typed(ln)[1] for ln in f.emails],
            org=f.org,
            note=f.note,
            form=f,
        )
