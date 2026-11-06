import zipfile

import pytest

from ccaccess import updater


def test_is_newer():
    assert updater.is_newer("v0.2.0", "0.1.0")
    assert updater.is_newer("0.1.1", "0.1.0")
    assert updater.is_newer("1.0", "0.9.9")
    assert not updater.is_newer("v0.1.0", "0.1.0")
    assert not updater.is_newer("0.1", "0.1.0")
    assert not updater.is_newer("0.0.9", "0.1.0")


def test_parse_version_invalid():
    with pytest.raises(updater.UpdateError):
        updater.parse_version("latest")


def test_parse_sums():
    text = "ABC123  CCAccess-0.2.0-windows.zip\ndef456 *other.zip\n"
    assert updater._parse_sums(text) == {
        "CCAccess-0.2.0-windows.zip": "abc123",
        "other.zip": "def456",
    }


def test_safe_extract_rejects_traversal(tmp_path):
    zp = tmp_path / "a.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(updater.UpdateError):
        updater._safe_extract(zp, tmp_path / "out")


def test_safe_extract_finds_exe(tmp_path):
    zp = tmp_path / "a.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("CCAccess/CCAccess.exe", "x")
    assert updater._safe_extract(zp, tmp_path / "out").name == "CCAccess"
