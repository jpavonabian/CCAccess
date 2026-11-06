"""Comprobación e instalación de actualizaciones desde las Releases de GitHub."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from ccaccess import __version__

REPO = "jpavonabian/CCAccess"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
TIMEOUT = 15


class UpdateError(Exception):
    pass


@dataclass
class Update:
    version: str
    notes: str
    zip_url: str
    zip_name: str
    sha256: str | None


def parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not m:
        raise UpdateError(f"Versión no válida: {text!r}")
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer(remote: str, local: str = __version__) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> bool:
    """Solo el .exe de Windows empaquetado y en una carpeta con permiso de escritura."""
    return sys.platform == "win32" and is_frozen() and os.access(install_dir(), os.W_OK)


def _parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sums[parts[-1].lstrip("*")] = parts[0].lower()
    return sums


def check_latest() -> Update | None:
    """Devuelve la actualización disponible o None si ya estás al día."""
    try:
        r = requests.get(API_URL, timeout=TIMEOUT, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
        tag = data["tag_name"]
        if not is_newer(tag):
            return None
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
        zip_name = next((n for n in assets if n.endswith("-windows.zip")), None)
        if not zip_name:
            raise UpdateError("La versión nueva no incluye el ZIP de Windows.")
        sha = None
        if "SHA256SUMS.txt" in assets:
            s = requests.get(assets["SHA256SUMS.txt"], timeout=TIMEOUT)
            s.raise_for_status()
            sha = _parse_sums(s.text).get(zip_name)
        return Update(tag.lstrip("v"), data.get("body") or "", assets[zip_name], zip_name, sha)
    except requests.RequestException as e:
        raise UpdateError(f"No se pudo consultar GitHub: {e}") from e


def download(update: Update, dest_dir: Path) -> Path:
    dest = dest_dir / update.zip_name
    h = hashlib.sha256()
    try:
        with requests.get(update.zip_url, stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
    except requests.RequestException as e:
        raise UpdateError(f"Fallo al descargar: {e}") from e
    if update.sha256 and h.hexdigest() != update.sha256:
        dest.unlink(missing_ok=True)
        raise UpdateError("La suma SHA-256 no coincide. Descarga descartada.")
    return dest


def _safe_extract(zip_path: Path, target: Path) -> Path:
    with zipfile.ZipFile(zip_path) as z:
        root = target.resolve()
        for name in z.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise UpdateError("ZIP con rutas no válidas.")
        z.extractall(target)
    exes = list(target.rglob("CCAccess.exe"))
    if not exes:
        raise UpdateError("El ZIP no contiene CCAccess.exe.")
    return exes[0].parent


def install_and_restart(update: Update) -> None:
    """Descarga, extrae y lanza un script que sustituye los archivos al cerrar la app."""
    work = Path(tempfile.mkdtemp(prefix="ccaccess-update-"))
    zip_path = download(update, work)
    src = _safe_extract(zip_path, work / "new")
    dst = install_dir()
    exe = dst / "CCAccess.exe"
    bat = work / "update.bat"
    bat.write_text(
        "@echo off\r\n"
        "set tries=0\r\n"
        ":wait\r\n"
        "set /a tries+=1\r\n"
        "if %tries% gtr 60 exit /b 1\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        f'(>>"{exe}" echo.) 2>nul || goto wait\r\n'
        f'robocopy "{src}" "{dst}" /E /NFL /NDL /NJH /NJS /NP >nul\r\n'
        f'start "" "{exe}"\r\n'
        f'rmdir /s /q "{work}"\r\n',
        encoding="mbcs",
    )
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
