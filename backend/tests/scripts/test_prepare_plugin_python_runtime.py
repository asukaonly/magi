from __future__ import annotations

from io import BytesIO
import importlib.util
from pathlib import Path
import stat
import tarfile
import zipfile

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "prepare-plugin-python-runtime.py"
)
SPEC = importlib.util.spec_from_file_location("prepare_plugin_python_runtime", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
runtime_preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_preparer)


def test_find_asset_url_requires_official_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    release = {
        "assets": [
            {
                "name": (
                    "cpython-3.13.5+20260810-x86_64-apple-darwin-"
                    "install_only_stripped.tar.gz"
                ),
                "browser_download_url": "https://github.com/example/runtime.tar.gz",
                "digest": "sha256:" + "a" * 64,
            }
        ]
    }
    monkeypatch.setattr(runtime_preparer, "request_json", lambda _url: release)

    assert runtime_preparer.find_asset_url("3.13", "x86_64-apple-darwin") == (
        "astral-sh/python-build-standalone",
        release["assets"][0]["name"],
        release["assets"][0]["browser_download_url"],
        "a" * 64,
    )


def test_verify_sha256_fails_closed(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(b"trusted runtime")

    runtime_preparer.verify_sha256(
        archive,
        "444c4c42ceae92b98270aad96e62109df06fb682ab89866a2f9ba95bd68d038e",
    )
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        runtime_preparer.verify_sha256(archive, "0" * 64)


def test_zip_extraction_rejects_traversal_and_links(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../outside.txt", "escaped")

    with pytest.raises(SystemExit, match="escapes extraction root"):
        runtime_preparer.extract_archive(traversal, tmp_path / "extract-traversal")
    assert not (tmp_path / "outside.txt").exists()

    symlink = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("python/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink, "w") as archive:
        archive.writestr(link, "../../outside.txt")

    with pytest.raises(SystemExit, match="symbolic link"):
        runtime_preparer.extract_archive(symlink, tmp_path / "extract-symlink")


def test_tar_extraction_preserves_safe_internal_link_and_rejects_escape(
    tmp_path: Path,
) -> None:
    safe_archive = tmp_path / "safe.tar.gz"
    payload = b"python"
    with tarfile.open(safe_archive, "w:gz") as archive:
        executable = tarfile.TarInfo("python/install/bin/python3.13")
        executable.size = len(payload)
        executable.mode = 0o755
        archive.addfile(executable, BytesIO(payload))
        link = tarfile.TarInfo("python/install/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3.13"
        archive.addfile(link)

    extract_dir = tmp_path / "extract-safe"
    runtime_preparer.extract_archive(safe_archive, extract_dir)
    assert (extract_dir / "python/install/bin/python3.13").read_bytes() == payload
    assert (extract_dir / "python/install/bin/python3").is_symlink()

    unsafe_archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(unsafe_archive, "w:gz") as archive:
        link = tarfile.TarInfo("python/install/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../../outside.txt"
        archive.addfile(link)

    with pytest.raises(SystemExit, match="escapes extraction root"):
        runtime_preparer.extract_archive(unsafe_archive, tmp_path / "extract-unsafe")
    assert not (tmp_path / "outside.txt").exists()
