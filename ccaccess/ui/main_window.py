from PySide6.QtCore import QObject, QSettings, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QHBoxLayout,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ccaccess.caldav_client import CalDavClient, Calendar, caldav_url_from
from ccaccess.carddav import AddressBook, CardDavClient, Contact, DavError, describe_vcard
from ccaccess.ui.calendar_tab import CalendarTab
from ccaccess.ui.account_dialog import AccountDialog
from ccaccess.ui.contact_dialog import ContactDialog
from ccaccess import exchange
from ccaccess.textutil import fold
from ccaccess.ui.dialogs import (
    EnterButton,
    ask_choice,
    confirm,
    make_readonly_navigable,
    report_import,
)
from ccaccess.ui.account_store import Account, clear_account, load_account, save_account
from ccaccess.ui.announce import announce
from ccaccess.ui.manual_dialog import ManualDialog
from ccaccess import __version__, updater

CONTACT_ROLE = 256  # Qt.UserRole


class Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(self.fn())
        except (DavError, updater.UpdateError) as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"Error inesperado: {e}")


class MainWindow(QMainWindow):
    _invoke = Signal(object, object)

    def __init__(self):
        super().__init__()
        self._invoke.connect(self._do_invoke)
        self.setWindowTitle("CCAccess")
        self.resize(900, 600)
        self.account: Account | None = None
        self.client: CardDavClient | None = None
        self.books: list[AddressBook] = []
        self.contacts: list[Contact] = []
        self._jobs: list[tuple[QThread, Worker]] = []

        self.book_combo = QComboBox()
        self.book_combo.currentIndexChanged.connect(self._load_contacts)
        book_label = QLabel("&Libreta de direcciones:")
        book_label.setBuddy(self.book_combo)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Escribe para filtrar")
        self.search.textChanged.connect(self._refresh_list)
        search_label = QLabel("&Buscar contacto:")
        search_label.setBuddy(self.search)

        self.list = QListWidget()
        self.list.setAccessibleName("Contactos")
        self.list.currentItemChanged.connect(self._show_detail)
        list_label = QLabel("&Contactos:")
        list_label.setBuddy(self.list)

        self.detail = QPlainTextEdit()
        make_readonly_navigable(self.detail)
        self.detail.setAccessibleName("Detalles del contacto")
        detail_label = QLabel("&Detalles:")
        detail_label.setBuddy(self.detail)

        left = QWidget()
        ll = QVBoxLayout(left)
        for w in (book_label, self.book_combo, search_label, self.search, list_label, self.list):
            ll.addWidget(w)
        self.btn_new = EnterButton("N&uevo…")
        self.btn_edit = EnterButton("&Editar…")
        self.btn_del = EnterButton("Eli&minar…")
        self.btn_new.clicked.connect(self.new_contact)
        self.btn_edit.clicked.connect(self.edit_contact)
        self.btn_del.clicked.connect(self.delete_contact)
        self.list.itemActivated.connect(lambda _item: self.edit_contact())
        row = QHBoxLayout()
        for b in (self.btn_new, self.btn_edit, self.btn_del):
            row.addWidget(b)
        ll.addLayout(row)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(detail_label)
        rl.addWidget(self.detail)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        self.calendar_tab = CalendarTab(self._run, self.say, self._run_silent)
        self.tabs = QTabWidget()
        self.tabs.addTab(split, "&Contactos")
        self.tabs.addTab(self.calendar_tab, "C&alendario")
        self.setCentralWidget(self.tabs)

        self.setTabOrder(self.book_combo, self.search)
        self.setTabOrder(self.search, self.list)
        self.setTabOrder(self.list, self.btn_new)
        self.setTabOrder(self.btn_new, self.btn_edit)
        self.setTabOrder(self.btn_edit, self.btn_del)
        self.setTabOrder(self.btn_del, self.detail)

        self._build_menu()
        self.statusBar().showMessage("Listo.")

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&Archivo")
        acc = QAction("&Cuenta…", self)
        acc.setShortcut(QKeySequence("Ctrl+Shift+A"))
        acc.triggered.connect(self.edit_account)
        wipe = QAction("&Borrar datos guardados…", self)
        wipe.triggered.connect(self.wipe_data)
        ref = QAction("&Actualizar", self)
        ref.setShortcut(QKeySequence.StandardKey.Refresh)
        ref.triggered.connect(self.connect_account)
        quit_ = QAction("&Salir", self)
        quit_.setShortcut(QKeySequence.StandardKey.Quit)
        quit_.triggered.connect(self.close)
        self.act_reminders = QAction("Avisos de &eventos", self)
        self.act_reminders.setCheckable(True)
        self.act_reminders.setChecked(bool(QSettings("CCAccess", "CCAccess").value("reminders/enabled", True, type=bool)))
        self.calendar_tab.reminders_enabled = self.act_reminders.isChecked()
        self.act_reminders.toggled.connect(self._toggle_reminders)
        imp = QAction("&Importar…", self)
        imp.setShortcut(QKeySequence("Ctrl+Shift+I"))
        imp.triggered.connect(self.import_items)
        exp = QAction("E&xportar…", self)
        exp.setShortcut(QKeySequence("Ctrl+Shift+E"))
        exp.triggered.connect(self.export_items)
        m.addActions([acc, ref, wipe, self.act_reminders])
        m.addSeparator()
        m.addActions([imp, exp])
        m.addSeparator()
        m.addAction(quit_)

        e = self.menuBar().addMenu("&Elemento")
        for text, key, slot in (
            ("&Nuevo…", "Ctrl+N", self.new_item),
            ("&Editar…", "Ctrl+E", self.edit_item),
            ("E&liminar…", "Del", self.delete_item),
        ):
            act = QAction(text, self)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(slot)
            e.addAction(act)

        s = self.menuBar().addMenu("&Ir a")
        f = QAction("&Buscar contacto", self)
        f.setShortcut(QKeySequence("Ctrl+F"))
        f.triggered.connect(self.search.setFocus)
        lst = QAction("&Lista de contactos", self)
        lst.setShortcut(QKeySequence("Ctrl+L"))
        lst.triggered.connect(self.list.setFocus)
        t1 = QAction("Pestaña de c&ontactos", self)
        t1.setShortcut(QKeySequence("Ctrl+1"))
        t1.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        t2 = QAction("Pestaña de c&alendario", self)
        t2.setShortcut(QKeySequence("Ctrl+2"))
        t2.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        fe = QAction("Buscar e&vento", self)
        fe.setShortcut(QKeySequence("Ctrl+Shift+F"))
        fe.triggered.connect(lambda: self._focus_calendar(self.calendar_tab.search))
        gd = QAction("Ir a &fecha del calendario", self)
        gd.setShortcut(QKeySequence("Ctrl+G"))
        gd.triggered.connect(lambda: self._focus_calendar(self.calendar_tab.goto_date))
        s.addActions([f, lst, fe, gd, t1, t2])

        h = self.menuBar().addMenu("A&yuda")
        upd = QAction("&Buscar actualizaciones…", self)
        upd.triggered.connect(lambda: self.check_updates(manual=True))
        about = QAction("&Acerca de CCAccess", self)
        about.triggered.connect(
            lambda: QMessageBox.information(self, "CCAccess", f"CCAccess {__version__}")
        )
        manual = QAction("Ver &manual", self)
        manual.setShortcut(QKeySequence("F1"))
        manual.triggered.connect(lambda: ManualDialog(self).exec())
        h.addActions([manual, upd, about])

    def _focus_calendar(self, widget) -> None:
        self.tabs.setCurrentIndex(1)
        widget.setFocus()

    def _toggle_reminders(self, on: bool) -> None:
        QSettings("CCAccess", "CCAccess").setValue("reminders/enabled", on)
        self.calendar_tab.reminders_enabled = on
        if on:
            self.calendar_tab.refresh_reminders()
        self.say("Avisos de eventos activados." if on else "Avisos de eventos desactivados.")

    # --- estado -----------------------------------------------------------
    def say(self, text: str) -> None:
        self.statusBar().showMessage(text)
        announce(self.statusBar(), text)

    @Slot(object, object)
    def _do_invoke(self, fn, arg) -> None:
        fn(arg)

    def _start_job(self, fn, on_done, on_fail) -> None:
        """Ejecuta fn en un hilo. on_done/on_fail se llaman SIEMPRE en el hilo principal."""
        thread = QThread(self)
        worker = Worker(fn)
        worker.moveToThread(thread)
        job = (thread, worker)
        thread.started.connect(worker.run)
        # Las lambdas/funciones sueltas se ejecutarían en el hilo del worker;
        # la señal de la ventana las reenvía al hilo principal.
        worker.done.connect(lambda r: self._invoke.emit(on_done, r))
        if on_fail is not None:
            worker.failed.connect(lambda m: self._invoke.emit(on_fail, m))
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._invoke.emit(lambda _r: self._jobs.remove(job), None))
        self._jobs.append(job)
        thread.start()

    def _run(self, fn, on_done) -> None:
        self._start_job(fn, on_done, self._on_error)

    def _on_error(self, msg: str) -> None:
        self.say(f"Error: {msg}")
        QMessageBox.warning(self, "CCAccess", msg)

    # --- actualizaciones --------------------------------------------------
    def check_updates(self, manual: bool = False) -> None:
        if manual:
            self.say("Buscando actualizaciones…")

        def done(update) -> None:
            if update is None:
                if manual:
                    self.say("Ya tienes la última versión.")
                    QMessageBox.information(
                        self, "CCAccess", f"Ya tienes la última versión ({__version__})."
                    )
                return
            self._offer_update(update)

        if manual:
            self._run(updater.check_latest, done)
        else:
            self._run_silent(updater.check_latest, done)

    def _offer_update(self, update) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Actualización disponible")
        box.setText(f"Hay una versión nueva: {update.version} (tienes {__version__}).")
        if update.notes:
            box.setInformativeText(update.notes[:1500])
        auto = updater.can_self_update()
        yes = box.addButton(
            "&Actualizar ahora" if auto else "&Abrir página de descarga",
            QMessageBox.ButtonRole.AcceptRole,
        )
        later = box.addButton("&Más tarde", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(yes)
        box.setEscapeButton(later)
        box.exec()
        if box.clickedButton() is not yes:
            return
        if not auto:
            QDesktopServices.openUrl(QUrl(updater.RELEASES_URL))
            return
        self.say("Descargando actualización…")

        def installed(_r) -> None:
            self.say("Actualización lista. La aplicación se reiniciará.")
            QApplication.quit()

        self._run(lambda: updater.install_and_restart(update), installed)

    def _run_silent(self, fn, on_done) -> None:
        """Como _run pero sin avisar si falla (comprobación automática al arrancar)."""
        self._start_job(fn, on_done, None)

    # --- cuenta -----------------------------------------------------------
    def start(self) -> None:
        if updater.is_frozen():
            QTimer.singleShot(3000, self.check_updates)
        self.account = load_account()
        if self.account and self.account.password:
            self.connect_account()
        else:
            self.edit_account()

    def edit_account(self) -> None:
        dlg = AccountDialog(self, self.account)
        if dlg.exec():
            self.account = dlg.account()
            save_account(self.account)
            self.connect_account()

    def wipe_data(self) -> None:
        if not confirm(
            self,
            "Borrar datos guardados",
            "Se borrarán del disco la URL, el usuario y la contraseña guardados. "
            "Tus contactos y eventos en el servidor no se tocan. ¿Continuar?",
            "&Borrar",
        ):
            return
        clear_account()
        self.account = None
        self.client = None
        self.books = []
        self.contacts = []
        self.book_combo.clear()
        self.list.clear()
        self.detail.clear()
        ct = self.calendar_tab
        ct.client, ct.calendars, ct.events = None, [], []
        ct.reset_reminders()
        ct.cal_combo.clear()
        ct.tree.clear()
        ct.detail.clear()
        self.say("Datos guardados borrados.")
        QMessageBox.information(self, "CCAccess", "Datos guardados borrados.")

    def connect_account(self) -> None:
        if not self.account:
            return self.edit_account()
        a = self.account
        client = CardDavClient(a.url, a.username, a.password)
        self.client = client
        self.say("Conectando con el servidor…")
        self.detail.setPlainText("Conectando con el servidor…")
        self._run(client.discover_addressbooks, self._on_books)

        cal_client = CalDavClient(a.caldav_url or caldav_url_from(a.url), a.username, a.password)
        # Un fallo del calendario no debe tapar los contactos (ni al revés): va a la barra de estado.
        self._start_job(
            cal_client.discover_calendars,
            lambda cals: self._on_calendars(cal_client, cals),
            lambda msg: self.say(f"Calendarios: {msg} Si usas iCloud u otro proveedor con otra dirección "
                                 "para calendarios, indícala en Cuenta."),
        )

    def _on_calendars(self, client: CalDavClient, cals: list[Calendar]) -> None:
        if not cals:
            self.say("No se encontraron calendarios en esta cuenta.")
            return
        self.calendar_tab.set_calendars(client, cals)

    def _on_books(self, books: list[AddressBook]) -> None:
        self.books = books
        self.book_combo.blockSignals(True)
        self.book_combo.clear()
        for b in books:
            self.book_combo.addItem(b.name, b.url)
        self.book_combo.blockSignals(False)
        if not books:
            self.say("No se encontraron libretas de direcciones.")
            QMessageBox.information(
                self,
                "CCAccess",
                "Conexión correcta, pero no se encontraron libretas de direcciones. "
                "Prueba con otra URL, por ejemplo https://dav.mailbox.org/carddav/",
            )
            return
        self.say(f"{len(books)} libretas encontradas.")
        self._load_contacts()

    # --- CRUD ---------------------------------------------------------------
    def new_item(self) -> None:
        (self.new_contact if self.tabs.currentIndex() == 0 else self.calendar_tab.new_event)()

    def edit_item(self) -> None:
        (self.edit_contact if self.tabs.currentIndex() == 0 else self.calendar_tab.edit_event)()

    def delete_item(self) -> None:
        (self.delete_contact if self.tabs.currentIndex() == 0 else self.calendar_tab.delete_event)()

    def _current_contact(self) -> Contact | None:
        item = self.list.currentItem()
        if item is None:
            QMessageBox.information(self, "CCAccess", "Selecciona primero un contacto.")
            return None
        return item.data(CONTACT_ROLE)

    def _write_contact(self, fn, done_msg: str) -> None:
        def finished(_result) -> None:
            self.say(done_msg)
            self._load_contacts()

        self.say("Guardando…")
        self._run(fn, finished)

    def new_contact(self) -> None:
        client, book = self.client, self.book_combo.currentData()
        if client is None or not book:
            QMessageBox.information(self, "CCAccess", "Conecta primero con una libreta de direcciones.")
            return
        dlg = ContactDialog(self)
        if dlg.exec():
            c = dlg.contact()
            self._write_contact(lambda: client.save_contact(book, c), f"Contacto {c.name} creado.")

    def edit_contact(self) -> None:
        client, book = self.client, self.book_combo.currentData()
        current = self._current_contact()
        if client is None or current is None:
            return
        dlg = ContactDialog(self, current)
        if dlg.exec():
            c = dlg.contact()
            self._write_contact(lambda: client.save_contact(book, c), f"Contacto {c.name} guardado.")

    def delete_contact(self) -> None:
        client = self.client
        current = self._current_contact()
        if client is None or current is None:
            return
        if confirm(self, "Eliminar contacto", f"¿Eliminar a {current.name} del servidor? No se puede deshacer.", "&Eliminar"):
            self._write_contact(lambda: client.delete_contact(current), f"Contacto {current.name} eliminado.")

    # --- importar y exportar -----------------------------------------------
    def import_items(self) -> None:
        (self.import_contacts if self.tabs.currentIndex() == 0 else self.calendar_tab.import_events)()

    def export_items(self) -> None:
        (self.export_contacts if self.tabs.currentIndex() == 0 else self.calendar_tab.export_events)()

    def import_contacts(self) -> None:
        client, book = self.client, self.book_combo.currentData()
        if client is None or not book:
            QMessageBox.information(self, "CCAccess", "Conecta primero con una libreta de direcciones.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar contactos", "", "Contactos vCard (*.vcf);;Todos los archivos (*)"
        )
        if not path:
            return
        try:
            items, bad = exchange.split_vcards(exchange.read_text(path))
        except OSError as e:
            QMessageBox.warning(self, "CCAccess", f"No se pudo leer el archivo: {e}")
            return
        if not items:
            QMessageBox.warning(self, "CCAccess", "No se encontró ningún contacto válido en el archivo.")
            return
        if not confirm(
            self,
            "Importar contactos",
            f"Se van a añadir {len(items)} contactos a la libreta {self.book_combo.currentText()}. "
            "Los que ya existan se omitirán. ¿Continuar?",
            "&Importar",
        ):
            return
        self.say(f"Importando {len(items)} contactos…")

        def done(result) -> None:
            report_import(self, self.say, result, "contacto", "contactos")
            self._load_contacts()

        self._run(lambda: exchange.import_contacts(client, book, items, bad), done)

    def export_contacts(self) -> None:
        if not self.contacts:
            self.say("No hay contactos que exportar.")
            return
        item = self.list.currentItem()
        current = item.data(CONTACT_ROLE) if item else None
        contacts = self.contacts
        if current is not None:
            choice = ask_choice(
                self,
                "Exportar contactos",
                "¿Qué quieres exportar?",
                [("&Contacto seleccionado", "one"), ("&Toda la libreta", "all")],
            )
            if choice is None:
                return
            if choice == "one":
                contacts = [current]
        stem = exchange.file_stem(current.name, "contacto") if len(contacts) == 1 else "contactos"
        path, _ = QFileDialog.getSaveFileName(self, "Exportar contactos", f"{stem}.vcf", "Contactos vCard (*.vcf)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(exchange.join_vcards([c.raw for c in contacts if c.raw]))
        except OSError as e:
            QMessageBox.warning(self, "CCAccess", f"No se pudo guardar el archivo: {e}")
            return
        self.say(f"{len(contacts)} contacto{'s' if len(contacts) != 1 else ''} exportado{'s' if len(contacts) != 1 else ''} a {path}.")

    # --- contactos --------------------------------------------------------
    def _load_contacts(self) -> None:
        client = self.client
        if client is None or self.book_combo.currentIndex() < 0:
            return
        url = self.book_combo.currentData()
        self.say("Cargando contactos…")
        self._run(lambda: client.fetch_contacts(url), self._on_contacts)

    def _on_contacts(self, contacts: list[Contact]) -> None:
        self.contacts = contacts
        self._refresh_list()
        self.say(f"{len(contacts)} contactos cargados." if contacts else "Esta libreta no tiene contactos.")
        if self.list.count():
            self.list.setFocus()

    def _refresh_list(self) -> None:
        q = fold(self.search.text().strip())
        self.list.clear()
        for c in self.contacts:
            hay = fold(" ".join([c.name, c.org, *c.emails, *c.phones]))
            if q in hay:
                item = QListWidgetItem(c.name)
                item.setData(CONTACT_ROLE, c)
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.detail.clear()
        if q:
            announce(self.list, f"{self.list.count()} resultados")

    def _show_detail(self, item: QListWidgetItem | None) -> None:
        if item is None:
            self.detail.clear()
            return
        c: Contact = item.data(CONTACT_ROLE)
        lines = describe_vcard(c.raw) if c.raw else []
        if not lines:
            lines = [f"Nombre: {c.name}"]
            if c.org:
                lines.append(f"Organización: {c.org}")
            lines += [f"Teléfono: {p}" for p in c.phones]
            lines += [f"Correo: {e}" for e in c.emails]
            if c.note:
                lines.append(f"Nota: {c.note}")
        self.detail.setPlainText("\n".join(lines))
