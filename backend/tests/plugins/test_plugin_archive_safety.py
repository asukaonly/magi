from __future__ import annotations

import io
import os
from pathlib import Path
import stat
import tarfile
import warnings
import zipfile

import pytest

from magi.plugins import package_files
from magi.plugins.package_files import (
    InvalidPluginArchiveError,
    extract_plugin_archive,
    find_plugin_manifest_in_tree,
    resolve_plugin_package_root,
)


def _write_tar_files(
    archive: Path,
    entries: list[tuple[str, bytes, int]],
) -> None:
    with tarfile.open(archive, "w:gz") as tf:
        for name, payload, mode in entries:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = mode
            tf.addfile(info, io.BytesIO(payload))


def _write_zip_files(
    archive: Path,
    entries: list[tuple[str, bytes, int]],
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive, "w") as zf:
            for name, payload, mode in entries:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | mode) << 16
                zf.writestr(info, payload)


def _write_archive_files(
    tmp_path: Path,
    archive_format: str,
    entries: list[tuple[str, bytes, int]],
) -> Path:
    if archive_format == "tar":
        archive = tmp_path / "plugin.tar.gz"
        _write_tar_files(archive, entries)
    else:
        archive = tmp_path / "plugin.zip"
        _write_zip_files(archive, entries)
    return archive


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_extracts_regular_files_with_restricted_modes(
    tmp_path: Path,
    archive_format: str,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [
            ("plugin.toml", b"[plugin]\n", 0o666),
            ("bin/helper", b"#!/bin/sh\n", 0o6755),
        ],
    )
    dest = tmp_path / "dest"

    extract_plugin_archive(archive, dest)

    assert (dest / "plugin.toml").read_bytes() == b"[plugin]\n"
    assert (dest / "bin/helper").read_bytes() == b"#!/bin/sh\n"
    if os.name != "nt":
        assert stat.S_IMODE((dest / "plugin.toml").stat().st_mode) == 0o644
        assert stat.S_IMODE((dest / "bin/helper").stat().st_mode) == 0o755


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_extracts_explicit_directories(
    tmp_path: Path,
    archive_format: str,
) -> None:
    if archive_format == "tar":
        archive = tmp_path / "plugin.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            directory = tarfile.TarInfo("assets")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o777
            tf.addfile(directory)
    else:
        archive = tmp_path / "plugin.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            directory = zipfile.ZipInfo("assets/")
            directory.create_system = 3
            directory.external_attr = (stat.S_IFDIR | 0o777) << 16
            zf.writestr(directory, b"")

    extract_plugin_archive(archive, tmp_path / "dest")

    extracted = tmp_path / "dest" / "assets"
    assert extracted.is_dir()
    if os.name != "nt":
        assert stat.S_IMODE(extracted.stat().st_mode) == 0o755


@pytest.mark.parametrize(
    "member_type",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.FIFOTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
    ],
)
def test_rejects_tar_links_and_special_members(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    archive = tmp_path / "plugin.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("unsafe")
        info.type = member_type
        if member_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
            info.linkname = "target"
        tf.addfile(info)

    with pytest.raises(InvalidPluginArchiveError, match="regular file or directory"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_tar_symlink_cannot_redirect_a_later_member(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.tar.gz"
    outside = tmp_path / "outside"
    outside.mkdir()
    with tarfile.open(archive, "w:gz") as tf:
        link = tarfile.TarInfo("redirect")
        link.type = tarfile.SYMTYPE
        link.linkname = str(outside)
        tf.addfile(link)

        payload = b"outside"
        nested = tarfile.TarInfo("redirect/proof.txt")
        nested.size = len(payload)
        tf.addfile(nested, io.BytesIO(payload))

    with pytest.raises(InvalidPluginArchiveError, match="regular file or directory"):
        extract_plugin_archive(archive, tmp_path / "dest")

    assert not (outside / "proof.txt").exists()


@pytest.mark.parametrize(
    "member_type",
    [
        stat.S_IFLNK,
        stat.S_IFIFO,
        stat.S_IFCHR,
        stat.S_IFBLK,
        stat.S_IFSOCK,
    ],
)
def test_rejects_zip_links_and_special_entries(
    tmp_path: Path,
    member_type: int,
) -> None:
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("unsafe")
        info.create_system = 3
        info.external_attr = (member_type | 0o777) << 16
        zf.writestr(info, "target")

    with pytest.raises(InvalidPluginArchiveError, match="regular file or directory"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape",
        "/absolute",
        "C:/escape",
        "folder\\..\\escape",
        "folder/../escape",
        "folder//escape",
        "folder/./escape",
        "NUL.txt",
        "file:stream",
        "trailing. ",
    ],
)
def test_rejects_non_portable_or_escaping_paths(
    tmp_path: Path,
    archive_format: str,
    unsafe_name: str,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [(unsafe_name, b"unsafe", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_member_count_limit(
    tmp_path: Path,
    archive_format: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_MEMBERS", 1)
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("one", b"1", 0o644), ("two", b"2", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError, match="more than 1 members"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_archive_container_size_limit(
    tmp_path: Path,
    archive_format: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("plugin.toml", b"[plugin]\n", 0o644)],
    )
    monkeypatch.setattr(
        package_files,
        "MAX_PLUGIN_ARCHIVE_CONTAINER_BYTES",
        archive.stat().st_size - 1,
    )

    with pytest.raises(InvalidPluginArchiveError, match="container limit"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_rejects_tar_metadata_expansion_before_tarfile_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "plugin.tar.gz"
    with tarfile.open(
        archive,
        "w:gz",
        format=tarfile.PAX_FORMAT,
        pax_headers={"comment": "x" * 10_000},
    ) as tf:
        payload = b"x"
        info = tarfile.TarInfo("plugin.toml")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_TAR_STREAM_BYTES", 2_048)

    with pytest.raises(InvalidPluginArchiveError, match="TAR stream limit"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_rejects_large_tar_metadata_before_it_is_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "plugin.tar.gz"
    with tarfile.open(
        archive,
        "w:gz",
        format=tarfile.PAX_FORMAT,
        pax_headers={"comment": "x" * 10_000},
    ) as tf:
        payload = b"x"
        info = tarfile.TarInfo("plugin.toml")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_METADATA_BYTES", 2_048)

    with pytest.raises(InvalidPluginArchiveError, match="TAR metadata parsing limit"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_rejects_zip_directory_metadata_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        "zip",
        [("plugin.toml", b"[plugin]\n", 0o644)],
    )
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_METADATA_BYTES", 1)

    with pytest.raises(InvalidPluginArchiveError, match="metadata limit"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_rejects_zip_directory_with_false_entry_count(tmp_path: Path) -> None:
    archive = _write_archive_files(
        tmp_path,
        "zip",
        [("one", b"1", 0o644), ("two", b"2", 0o644)],
    )
    archive_bytes = bytearray(archive.read_bytes())
    end_offset = archive_bytes.rfind(b"PK\x05\x06")
    assert end_offset >= 0
    archive_bytes[end_offset + 8 : end_offset + 12] = b"\x01\x00\x01\x00"
    archive.write_bytes(archive_bytes)

    with pytest.raises(InvalidPluginArchiveError, match="entry count is inconsistent"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_per_file_size_limit(
    tmp_path: Path,
    archive_format: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_FILE_BYTES", 3)
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("large", b"1234", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError, match="per-file limit"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_total_expanded_size_limit(
    tmp_path: Path,
    archive_format: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_TOTAL_BYTES", 5)
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("one", b"123", 0o644), ("two", b"456", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError, match="expanded-size limit"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_path_length_and_depth_limits(
    tmp_path: Path,
    archive_format: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_PATH_BYTES", 8)
    too_long = _write_archive_files(
        tmp_path,
        archive_format,
        [("123456789", b"x", 0o644)],
    )
    with pytest.raises(InvalidPluginArchiveError, match="too long"):
        extract_plugin_archive(too_long, tmp_path / "long-dest")

    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_PATH_BYTES", 1024)
    monkeypatch.setattr(package_files, "MAX_PLUGIN_ARCHIVE_PATH_DEPTH", 2)
    too_deep = _write_archive_files(
        tmp_path,
        archive_format,
        [("a/b/c", b"x", 0o644)],
    )
    with pytest.raises(InvalidPluginArchiveError, match="too deep"):
        extract_plugin_archive(too_deep, tmp_path / "deep-dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_exact_duplicate_paths(
    tmp_path: Path,
    archive_format: str,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("plugin.py", b"one", 0o644), ("plugin.py", b"two", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError, match="Duplicate"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_duplicate_and_case_conflicting_paths(
    tmp_path: Path,
    archive_format: str,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("Plugin.py", b"one", 0o644), ("plugin.py", b"two", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError, match="case-conflicting"):
        extract_plugin_archive(archive, tmp_path / "dest")


@pytest.mark.parametrize("archive_format", ["tar", "zip"])
def test_rejects_case_conflicts_in_implicit_parent_directories(
    tmp_path: Path,
    archive_format: str,
) -> None:
    archive = _write_archive_files(
        tmp_path,
        archive_format,
        [("Folder/one", b"one", 0o644), ("folder/two", b"two", 0o644)],
    )

    with pytest.raises(InvalidPluginArchiveError, match="portable spellings"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_rejects_file_directory_conflicts(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        payload = b"file"
        parent = tarfile.TarInfo("parent")
        parent.size = len(payload)
        tf.addfile(parent, io.BytesIO(payload))

        child = tarfile.TarInfo("parent/child")
        child.size = len(payload)
        tf.addfile(child, io.BytesIO(payload))

    with pytest.raises(InvalidPluginArchiveError, match="nested below a file"):
        extract_plugin_archive(archive, tmp_path / "dest")


def test_rejects_non_empty_or_symlinked_destination(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.zip"
    _write_zip_files(archive, [("plugin.toml", b"[plugin]\n", 0o644)])

    non_empty = tmp_path / "non-empty"
    non_empty.mkdir()
    (non_empty / "sentinel").write_text("keep", encoding="utf-8")
    with pytest.raises(InvalidPluginArchiveError, match="must be empty"):
        extract_plugin_archive(archive, non_empty)
    assert (non_empty / "sentinel").read_text(encoding="utf-8") == "keep"

    symlink_dest = tmp_path / "linked-dest"
    try:
        symlink_dest.symlink_to(non_empty, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this platform")
    with pytest.raises(InvalidPluginArchiveError, match="cannot be a symlink"):
        extract_plugin_archive(archive, symlink_dest)


def test_resolves_direct_and_wrapped_plugin_roots(tmp_path: Path) -> None:
    direct = tmp_path / "direct"
    direct.mkdir()
    (direct / "plugin.toml").write_text("[plugin]\n", encoding="utf-8")
    (direct / "plugin.py").write_text("", encoding="utf-8")
    assert resolve_plugin_package_root(direct) == direct
    assert find_plugin_manifest_in_tree(direct) == direct / "plugin.toml"

    wrapped = tmp_path / "wrapped"
    package_root = wrapped / "demo"
    package_root.mkdir(parents=True)
    (package_root / "plugin.toml").write_text("[plugin]\n", encoding="utf-8")
    assert resolve_plugin_package_root(wrapped) == package_root
    assert find_plugin_manifest_in_tree(wrapped) == package_root / "plugin.toml"


def test_manifest_helper_returns_none_when_manifest_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()

    assert resolve_plugin_package_root(root) is None
    assert find_plugin_manifest_in_tree(root) is None


def test_rejects_multiple_or_ambiguous_plugin_roots(tmp_path: Path) -> None:
    multiple = tmp_path / "multiple"
    (multiple / "nested").mkdir(parents=True)
    (multiple / "plugin.toml").write_text("[plugin]\n", encoding="utf-8")
    (multiple / "nested" / "plugin.toml").write_text("[plugin]\n", encoding="utf-8")
    with pytest.raises(InvalidPluginArchiveError, match="exactly one"):
        resolve_plugin_package_root(multiple)

    ambiguous = tmp_path / "ambiguous"
    (ambiguous / "demo").mkdir(parents=True)
    (ambiguous / "demo" / "plugin.toml").write_text("[plugin]\n", encoding="utf-8")
    (ambiguous / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(InvalidPluginArchiveError, match="unambiguous"):
        resolve_plugin_package_root(ambiguous)

    too_deep = tmp_path / "too-deep"
    (too_deep / "outer" / "inner").mkdir(parents=True)
    (too_deep / "outer" / "inner" / "plugin.toml").write_text(
        "[plugin]\n",
        encoding="utf-8",
    )
    with pytest.raises(InvalidPluginArchiveError, match="one directory below"):
        resolve_plugin_package_root(too_deep)
