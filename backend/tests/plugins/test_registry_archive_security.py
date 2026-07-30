from __future__ import annotations

import io
from pathlib import Path
import tarfile

import pytest

from magi.plugins import package_files
from magi.plugins.package_files import InvalidPluginArchiveError
from magi.plugins.registry_client import _extract_subdir_from_tarball

TARGET_PREFIX = "repo-root/plugins/demo"


def _tarball(
    entries: list[tuple[str, bytes | None, bytes | None, int]],
) -> bytes:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        root = tarfile.TarInfo("repo-root")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, data, member_type, mode in entries:
            member = tarfile.TarInfo(name)
            member.type = member_type or tarfile.REGTYPE
            member.mode = mode
            if member.type == tarfile.REGTYPE:
                content = data or b""
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                if member.type == tarfile.SYMTYPE:
                    member.linkname = "../../outside"
                archive.addfile(member)
    return payload.getvalue()


def _extract(payload: bytes, destination: Path) -> None:
    _extract_subdir_from_tarball(
        payload,
        subdir="plugins/demo",
        dest=destination,
    )


def test_registry_tarball_extracts_regular_files_and_executable_bits(
    tmp_path: Path,
) -> None:
    payload = _tarball(
        [
            (f"{TARGET_PREFIX}/plugin.toml", b"[plugin]\n", None, 0o644),
            (f"{TARGET_PREFIX}/bin/helper", b"run", None, 0o755),
        ]
    )

    _extract(payload, tmp_path / "plugin")

    assert (tmp_path / "plugin" / "plugin.toml").read_bytes() == b"[plugin]\n"
    assert (tmp_path / "plugin" / "bin" / "helper").stat().st_mode & 0o111


@pytest.mark.parametrize(
    "member_name",
    [
        f"{TARGET_PREFIX}/../../escape.txt",
        f"{TARGET_PREFIX}//absolute.txt",
    ],
)
def test_registry_tarball_rejects_unsafe_paths(
    member_name: str,
    tmp_path: Path,
) -> None:
    payload = _tarball([(member_name, b"escape", None, 0o644)])

    with pytest.raises(InvalidPluginArchiveError, match="path"):
        _extract(payload, tmp_path / "plugin")

    assert not (tmp_path / "escape.txt").exists()


def test_registry_tarball_rejects_case_conflicting_paths(tmp_path: Path) -> None:
    payload = _tarball(
        [
            (f"{TARGET_PREFIX}/README.md", b"first", None, 0o644),
            (f"{TARGET_PREFIX}/readme.md", b"second", None, 0o644),
        ]
    )

    with pytest.raises(InvalidPluginArchiveError, match="Duplicate or case-conflicting"):
        _extract(payload, tmp_path / "plugin")


def test_registry_tarball_rejects_too_many_members(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_MEMBERS", 2)
    payload = _tarball(
        [
            (f"{TARGET_PREFIX}/one.txt", b"1", None, 0o644),
            (f"{TARGET_PREFIX}/two.txt", b"2", None, 0o644),
        ]
    )

    with pytest.raises(InvalidPluginArchiveError, match="more than 2 members"):
        _extract(payload, tmp_path / "plugin")


def test_registry_tarball_rejects_oversized_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_FILE_BYTES", 3)
    payload = _tarball([(f"{TARGET_PREFIX}/large.bin", b"1234", None, 0o644)])

    with pytest.raises(InvalidPluginArchiveError, match="per-file limit"):
        _extract(payload, tmp_path / "plugin")


def test_registry_tarball_rejects_oversized_expansion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_TOTAL_BYTES", 5)
    payload = _tarball(
        [
            (f"{TARGET_PREFIX}/one.bin", b"123", None, 0o644),
            (f"{TARGET_PREFIX}/two.bin", b"456", None, 0o644),
        ]
    )

    with pytest.raises(InvalidPluginArchiveError, match="total expanded-size"):
        _extract(payload, tmp_path / "plugin")


def test_registry_tarball_rejects_high_expansion_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_TAR_STREAM_BYTES", 1024)
    payload = _tarball([(f"{TARGET_PREFIX}/zeros.bin", b"\0" * 2048, None, 0o644)])

    with pytest.raises(InvalidPluginArchiveError, match="expanded TAR stream"):
        _extract(payload, tmp_path / "plugin")


def test_registry_tarball_rejects_links_and_missing_target(tmp_path: Path) -> None:
    link_payload = _tarball([(f"{TARGET_PREFIX}/link", None, tarfile.SYMTYPE, 0o777)])

    with pytest.raises(InvalidPluginArchiveError, match="not a regular file"):
        _extract(link_payload, tmp_path / "link-plugin")

    missing_payload = _tarball(
        [("repo-root/plugins/other/plugin.toml", b"[plugin]\n", None, 0o644)]
    )
    with pytest.raises(InvalidPluginArchiveError, match="was not found"):
        _extract(missing_payload, tmp_path / "missing-plugin")
