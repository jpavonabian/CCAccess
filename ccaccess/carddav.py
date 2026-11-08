"""Cliente CardDAV mínimo, sin dependencias de Qt."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import requests
import vobject

NS = {
    "d": "DAV:",
    "card": "urn:ietf:params:xml:ns:carddav",
    "cal": "urn:ietf:params:xml:ns:caldav",
}
TIMEOUT = 20


class DavError(Exception):
    """Error de comunicación o de protocolo con el servidor."""


class DavConflict(DavError):
    """El elemento cambió en el servidor o ya existe (409/412)."""


@dataclass
class Contact:
    href: str
    uid: str
    name: str
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    org: str = ""
    note: str = ""
    etag: str = ""
    raw: str = ""  # vCard original, para conservar los campos que la app no edita
    form: object | None = None  # ContactForm completo (editor); si existe, manda sobre los campos sueltos


@dataclass
class AddressBook:
    url: str
    name: str


def _split_name(full: str) -> vobject.vcard.Name:
    parts = full.split()
    if len(parts) <= 1:
        return vobject.vcard.Name(given=full)
    return vobject.vcard.Name(family=parts[-1], given=" ".join(parts[:-1]))


def _sync_multi(card, key: str, values: list[str], extra: dict | None = None) -> None:
    """Deja en `card` exactamente `values`, conservando los parámetros (TYPE…) de los que ya estaban."""
    kept = set()
    for comp in list(card.contents.get(key, [])):
        if comp.value in values and comp.value not in kept:
            kept.add(comp.value)
        else:
            card.remove(comp)
    for v in values:
        if v not in kept:
            comp = card.add(key)
            comp.value = v
            kept.add(v)


def build_vcard(contact: Contact, uid: str) -> str:
    """Genera el texto vCard de `contact`. Si tiene `raw`, parte de él y conserva el resto de campos."""
    if contact.form is not None:
        from ccaccess.vcard_form import apply_form

        return apply_form(contact.raw, contact.form, uid)
    if contact.raw:
        card = vobject.readOne(contact.raw)
    else:
        card = vobject.vCard()
    old_fn = card.contents["fn"][0].value if card.contents.get("fn") else None
    if old_fn is None:
        card.add("fn")
    card.fn.value = contact.name
    if old_fn != contact.name or not card.contents.get("n"):
        if card.contents.get("n"):
            card.remove(card.n)
        card.add("n").value = _split_name(contact.name)
    _sync_multi(card, "tel", contact.phones)
    _sync_multi(card, "email", contact.emails)
    for key in ("org", "note"):
        for comp in list(card.contents.get(key, [])):
            card.remove(comp)
    if contact.org:
        card.add("org").value = [contact.org]
    if contact.note:
        card.add("note").value = contact.note
    if not card.contents.get("uid"):
        card.add("uid").value = uid
    return card.serialize()


def parse_vcard(href: str, text: str, etag: str = "") -> Contact | None:
    """Convierte un vCard en Contact. Devuelve None si no se puede leer."""
    try:
        card = vobject.readOne(text)
    except Exception:
        return None
    fn = getattr(card, "fn", None)
    name = fn.value.strip() if fn and fn.value else ""
    emails = [c.value for c in card.contents.get("email", []) if c.value]
    phones = [c.value for c in card.contents.get("tel", []) if c.value]
    org_c = card.contents.get("org", [])
    org = ""
    if org_c:
        v = org_c[0].value
        org = " ".join(v) if isinstance(v, (list, tuple)) else str(v)
    note_c = card.contents.get("note", [])
    note = note_c[0].value if note_c else ""
    uid_c = card.contents.get("uid", [])
    uid = uid_c[0].value if uid_c else href
    if not name:
        name = emails[0] if emails else (phones[0] if phones else org or "(sin nombre)")
    return Contact(href, uid, name, emails, phones, org, note, etag, text)


class CardDavClient:
    def __init__(self, url: str, username: str, password: str):
        self.base = url
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers["User-Agent"] = "CCAccess/0.1"

    def _request(self, method: str, url: str, body: str, depth: str = "0") -> ET.Element:
        try:
            r = self.session.request(
                method,
                url,
                data=body.encode("utf-8"),
                headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise DavError(f"No se pudo conectar: {e}") from e
        if r.status_code == 401:
            raise DavError("Usuario o contraseña incorrectos.")
        if r.status_code not in (200, 207):
            raise DavError(f"El servidor respondió {r.status_code} a {method} {url}")
        try:
            return ET.fromstring(r.content)
        except ET.ParseError as e:
            raise DavError("Respuesta del servidor no válida.") from e

    def _write(self, method: str, url: str, headers: dict, body: str | None = None) -> None:
        try:
            r = self.session.request(
                method,
                url,
                data=body.encode("utf-8") if body is not None else None,
                headers=headers,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise DavError(f"No se pudo conectar: {e}") from e
        if r.status_code in (200, 201, 204):
            return
        if r.status_code == 401:
            raise DavError("Usuario o contraseña incorrectos.")
        if r.status_code in (409, 412):
            raise DavConflict(
                "El elemento cambió en el servidor o ya existe. "
                "Actualiza la lista (F5) y vuelve a intentarlo."
            )
        if r.status_code == 403:
            raise DavError("No tienes permiso para modificar este elemento.")
        raise DavError(f"El servidor respondió {r.status_code} a {method} {url}")

    def _put(self, url: str, body: str, content_type: str, etag: str = "", new: bool = False) -> None:
        headers = {"Content-Type": f"{content_type}; charset=utf-8"}
        if new:
            headers["If-None-Match"] = "*"
        elif etag:
            headers["If-Match"] = etag
        self._write("PUT", url, headers, body)

    def _delete(self, url: str, etag: str = "") -> None:
        self._write("DELETE", url, {"If-Match": etag} if etag else {})

    @staticmethod
    def _href(root: ET.Element, path: str) -> str | None:
        el = root.find(path, NS)
        return el.text.strip() if el is not None and el.text else None

    def _try(self, method: str, url: str, body: str, depth: str = "0") -> ET.Element | None:
        """Como _request, pero devuelve None si el servidor rechaza la petición."""
        try:
            return self._request(method, url, body, depth)
        except DavError as e:
            if "incorrectos" in str(e) or "No se pudo conectar" in str(e):
                raise
            return None

    def _wellknown(self, kind: str) -> str | None:
        """Sigue /.well-known/<kind> (RFC 6764) y devuelve la URL a la que redirige, si la hay."""
        parts = urlsplit(self.base)
        wk = f"{parts.scheme}://{parts.netloc}/.well-known/{kind}"
        try:
            r = self.session.request(
                "PROPFIND", wk, data=b"", headers={"Depth": "0"}, timeout=TIMEOUT, allow_redirects=False
            )
        except requests.RequestException:
            return None
        loc = r.headers.get("Location")
        if r.status_code in (301, 302, 303, 307, 308) and loc:
            return urljoin(wk, loc)
        return None

    def _propfind_start(self, xml: str, kind: str) -> tuple[str, ET.Element]:
        """PROPFIND a la URL base; si el servidor la rechaza, prueba la ruta /.well-known/<kind>."""
        try:
            return self.base, self._request("PROPFIND", self.base, xml)
        except DavError as e:
            if "incorrectos" in str(e) or "No se pudo conectar" in str(e):
                raise
            alt = self._wellknown(kind)
            if not alt or alt == self.base:
                raise
            return alt, self._request("PROPFIND", alt, xml)

    def discover_addressbooks(self) -> list[AddressBook]:
        info_xml = (
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">'
            "<d:prop><d:resourcetype/><d:displayname/>"
            "<d:current-user-principal/><c:addressbook-home-set/>"
            "</d:prop></d:propfind>"
        )
        start, root = self._propfind_start(info_xml, "carddav")

        # 1) La URL ya es una libreta de direcciones.
        for resp in root.findall("d:response", NS):
            if resp.find(".//card:addressbook", NS) is not None:
                dn = resp.find(".//d:displayname", NS)
                name = dn.text.strip() if dn is not None and dn.text else "Contactos"
                return [AddressBook(start, name)]

        # 2) La URL ya indica dónde están las libretas, o hay que ir por el principal.
        home = self._href(root, ".//card:addressbook-home-set/d:href")
        home_url = urljoin(start, home) if home else None
        if not home_url:
            principal = self._href(root, ".//d:current-user-principal/d:href")
            if principal:
                principal_url = urljoin(start, principal)
                home_xml = (
                    '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">'
                    "<d:prop><c:addressbook-home-set/></d:prop></d:propfind>"
                )
                proot = self._try("PROPFIND", principal_url, home_xml)
                h = self._href(proot, ".//card:addressbook-home-set/d:href") if proot is not None else None
                if h:
                    home_url = urljoin(principal_url, h)
        # 3) Último recurso: tratar la URL base como la carpeta que contiene las libretas.
        if not home_url:
            home_url = start

        list_xml = (
            '<d:propfind xmlns:d="DAV:"><d:prop>'
            "<d:resourcetype/><d:displayname/></d:prop></d:propfind>"
        )
        root = self._request("PROPFIND", home_url, list_xml, depth="1")
        books = []
        for resp in root.findall("d:response", NS):
            if resp.find(".//card:addressbook", NS) is None:
                continue
            href = self._href(resp, "d:href")
            if not href:
                continue
            dn = resp.find(".//d:displayname", NS)
            name = dn.text.strip() if dn is not None and dn.text else href.rstrip("/").split("/")[-1]
            books.append(AddressBook(urljoin(home_url, href), name))
        return books

    def fetch_contacts(self, book_url: str) -> list[Contact]:
        query = (
            '<c:addressbook-query xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:carddav">'
            "<d:prop><d:getetag/><c:address-data/></d:prop>"
            "</c:addressbook-query>"
        )
        root = self._request("REPORT", book_url, query, depth="1")
        contacts = []
        for resp in root.findall("d:response", NS):
            data = resp.find(".//card:address-data", NS)
            href = self._href(resp, "d:href") or ""
            if data is None or not data.text:
                continue
            etag_el = resp.find(".//d:getetag", NS)
            etag = etag_el.text.strip() if etag_el is not None and etag_el.text else ""
            c = parse_vcard(urljoin(book_url, href), data.text, etag)
            if c:
                contacts.append(c)
        contacts.sort(key=lambda c: c.name.casefold())
        return contacts

    def save_contact(self, book_url: str, contact: Contact) -> None:
        """Crea el contacto (si no tiene href) o actualiza el existente."""
        if contact.href:
            self._put(contact.href, build_vcard(contact, contact.uid), "text/vcard", etag=contact.etag)
        else:
            uid = str(uuid.uuid4())
            url = urljoin(book_url if book_url.endswith("/") else book_url + "/", f"{uid}.vcf")
            self._put(url, build_vcard(contact, uid), "text/vcard", new=True)

    def import_contact(self, book_url: str, uid: str, vcard: str) -> None:
        """Crea un contacto ya escrito (importación). Falla con DavConflict si ese UID ya existe."""
        from ccaccess.exchange import safe_name

        base = book_url if book_url.endswith("/") else book_url + "/"
        self._put(urljoin(base, safe_name(uid, ".vcf")), vcard, "text/vcard", new=True)

    def delete_contact(self, contact: Contact) -> None:
        self._delete(contact.href, contact.etag)


_LABELS = {
    "FN": "Nombre", "N": "Nombre estructurado", "NICKNAME": "Apodo", "ORG": "Organización",
    "TITLE": "Cargo", "ROLE": "Función", "TEL": "Teléfono", "EMAIL": "Correo",
    "ADR": "Dirección", "URL": "Web", "BDAY": "Cumpleaños", "ANNIVERSARY": "Aniversario",
    "NOTE": "Nota", "CATEGORIES": "Categorías", "IMPP": "Mensajería", "GENDER": "Género",
    "TZ": "Zona horaria", "GEO": "Ubicación", "RELATED": "Relación", "LANG": "Idioma",
}
_SKIP = {"VERSION", "PRODID", "UID", "REV", "PHOTO", "LOGO", "SOUND", "KEY", "BEGIN", "END"}


def _fmt_value(value) -> str:
    if isinstance(value, vobject.vcard.Address):
        parts = [value.street, value.code, value.city, value.region, value.country]
        return ", ".join(p for p in (str(x).strip() for x in parts if x) if p)
    if isinstance(value, vobject.vcard.Name):
        parts = [value.prefix, value.given, value.additional, value.family, value.suffix]
        return " ".join(p for p in (" ".join(x) if isinstance(x, list) else str(x or "") for x in parts) if p)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return str(value).strip()


def describe_vcard(raw: str) -> list[str]:
    """Todas las propiedades del vCard como líneas «Etiqueta (tipo): valor» para mostrarlas."""
    try:
        card = vobject.readOne(raw)
    except Exception:
        return []
    lines: list[str] = []
    for prop in card.getChildren():
        key = prop.name.upper()
        if key in _SKIP:
            if key in ("PHOTO", "LOGO"):
                lines.append("Foto: sí" if key == "PHOTO" else "Logotipo: sí")
            continue
        if key == "N":
            continue  # redundante con FN
        value = _fmt_value(prop.value)
        if not value:
            continue
        label = _LABELS.get(key, key[2:].replace("-", " ").capitalize() if key.startswith("X-") else key.capitalize())
        types = [t.lower() for t in prop.params.get("TYPE", []) if t.lower() != "pref"]
        if types:
            label += f" ({', '.join(types)})"
        lines.append(f"{label}: {value}")
    return lines
