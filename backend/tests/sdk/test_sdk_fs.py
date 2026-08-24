import os
import stat
from pathlib import Path
from typing import Any

import pytest


def test_sdk_exposes_atomic_io():
    from magi_plugin_sdk import (
        list_managed_directory_names as public_list_managed_directory_names,
    )
    from magi_plugin_sdk import path_is_link as public_path_is_link
    from magi_plugin_sdk.fs import (  # noqa: F401
        append_jsonl,
        append_jsonl_many,
        atomic_write_bytes,
        atomic_write_managed_bytes,
        atomic_write_managed_text,
        atomic_write_text,
        list_managed_directory_names,
        read_managed_bytes,
        read_managed_text,
        path_is_link,
        remove_managed_file,
    )

    assert public_path_is_link is path_is_link
    assert public_list_managed_directory_names is list_managed_directory_names


def test_atomic_write_text_roundtrip(tmp_path: Path):
    from magi_plugin_sdk.fs import atomic_write_text

    target = tmp_path / "nested" / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_append_jsonl(tmp_path: Path):
    from magi_plugin_sdk.fs import append_jsonl

    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"a": 1})
    append_jsonl(target, {"b": 2})
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_append_jsonl_many_restores_file_when_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi_plugin_sdk.fs import append_jsonl, append_jsonl_many

    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"existing": True})
    original = target.read_bytes()
    original_fsync = os.fsync
    calls = 0

    def fail_first_sync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected sync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_first_sync)

    with pytest.raises(OSError, match="injected sync failure"):
        append_jsonl_many(target, ({"new": 1}, {"new": 2}))

    assert target.read_bytes() == original


def test_managed_write_replaces_target_link_without_touching_source(
    tmp_path: Path,
) -> None:
    from magi_plugin_sdk.fs import atomic_write_managed_text

    managed = tmp_path / "managed"
    managed.mkdir()
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    target = managed / "state.json"
    target.symlink_to(external)

    atomic_write_managed_text(target, "managed")

    assert target.is_symlink() is False
    assert target.read_text(encoding="utf-8") == "managed"
    assert external.read_text(encoding="utf-8") == "external"


def test_managed_write_replaces_hard_link_without_touching_source(
    tmp_path: Path,
) -> None:
    from magi_plugin_sdk.fs import atomic_write_managed_text

    managed = tmp_path / "managed"
    managed.mkdir()
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    target = managed / "state.json"
    os.link(external, target)

    atomic_write_managed_text(target, "managed")

    assert target.read_text(encoding="utf-8") == "managed"
    assert external.read_text(encoding="utf-8") == "external"


def test_managed_remove_unlinks_target_link_without_touching_source(
    tmp_path: Path,
) -> None:
    from magi_plugin_sdk.fs import remove_managed_file

    managed = tmp_path / "managed"
    managed.mkdir()
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    target = managed / "state.json"
    target.symlink_to(external)

    assert remove_managed_file(target) is True
    assert target.exists() is False
    assert target.is_symlink() is False
    assert external.read_text(encoding="utf-8") == "external"
    assert remove_managed_file(target) is False


def test_path_link_detection_falls_back_to_windows_reparse_attribute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import magi_plugin_sdk.fs as sdk_fs

    class WindowsStat:
        st_file_attributes = 0x0400

    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.delattr(Path, "is_junction", raising=False)
    monkeypatch.setattr(
        sdk_fs.stat,
        "FILE_ATTRIBUTE_REPARSE_POINT",
        0x0400,
        raising=False,
    )

    assert sdk_fs.path_is_link(tmp_path / "junction", path_stat=WindowsStat()) is True


def _install_windows_junction_simulation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Any, Path, Path, list[Path]]:
    import magi_plugin_sdk.fs as sdk_fs

    managed = tmp_path / "managed"
    managed.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "private.txt").write_text("external", encoding="utf-8")
    target = managed / "state.json"
    try:
        target.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    original_lstat = os.lstat
    original_rmdir = os.rmdir
    original_unlink = os.unlink
    junction_present = True
    rmdir_calls: list[Path] = []

    class WindowsJunctionStat:
        st_mode = stat.S_IFDIR | 0o700
        st_file_attributes = 0x0400
        st_dev = 17
        st_ino = 23
        st_nlink = 1
        st_size = 0

    def fake_lstat(path: os.PathLike[str] | str, *args, **kwargs):
        if Path(path) == target and junction_present:
            return WindowsJunctionStat()
        return original_lstat(path, *args, **kwargs)

    def fake_rmdir(path: os.PathLike[str] | str, *args, **kwargs) -> None:
        nonlocal junction_present
        normalized = Path(path)
        if normalized == target and junction_present:
            rmdir_calls.append(normalized)
            junction_present = False
            original_unlink(path)
            return
        original_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(sdk_fs, "_IS_WINDOWS", True)
    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os, "rmdir", fake_rmdir)
    return sdk_fs, external, target, rmdir_calls


def test_windows_managed_read_ignores_directory_junction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sdk_fs, external, target, rmdir_calls = _install_windows_junction_simulation(
        monkeypatch,
        tmp_path,
    )

    assert sdk_fs.read_managed_text(target) is None
    assert rmdir_calls == []
    assert (external / "private.txt").read_text(encoding="utf-8") == "external"


def test_windows_managed_remove_unlinks_directory_junction_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sdk_fs, external, target, rmdir_calls = _install_windows_junction_simulation(
        monkeypatch,
        tmp_path,
    )

    assert sdk_fs.remove_managed_file(target) is True
    assert rmdir_calls == [target]
    assert target.exists() is False
    assert (external / "private.txt").read_text(encoding="utf-8") == "external"


def test_windows_managed_write_replaces_directory_junction_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sdk_fs, external, target, rmdir_calls = _install_windows_junction_simulation(
        monkeypatch,
        tmp_path,
    )

    sdk_fs.atomic_write_managed_text(target, "managed")

    assert rmdir_calls == [target]
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "managed"
    assert (external / "private.txt").read_text(encoding="utf-8") == "external"


def test_managed_directory_listing_returns_sorted_names_and_missing_is_empty(
    tmp_path: Path,
) -> None:
    from magi_plugin_sdk.fs import list_managed_directory_names

    directory = tmp_path / "accounts"
    directory.mkdir()
    (directory / "zeta.json").write_text("z", encoding="utf-8")
    (directory / "alpha.json").write_text("a", encoding="utf-8")
    (directory / "nested").mkdir()

    assert list_managed_directory_names(directory) == [
        "alpha.json",
        "nested",
        "zeta.json",
    ]
    assert list_managed_directory_names(tmp_path / "missing") == []
    assert list_managed_directory_names(tmp_path / "missing-parent" / "missing") == []


@pytest.mark.parametrize("link_location", ["root", "ancestor"])
def test_managed_directory_listing_rejects_linked_path_chain(
    tmp_path: Path,
    link_location: str,
) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        list_managed_directory_names,
    )

    external = tmp_path / "external"
    external.mkdir()
    (external / "private.json").write_text("private", encoding="utf-8")
    if link_location == "root":
        target = tmp_path / "accounts"
        link_target = external
    else:
        linked_parent = tmp_path / "linked"
        target = linked_parent / "accounts"
        link_target = external
        (external / "accounts").mkdir()
    try:
        (target if link_location == "root" else linked_parent).symlink_to(
            link_target,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    with pytest.raises(UnsafeManagedPathError):
        list_managed_directory_names(target)

    assert (external / "private.json").read_text(encoding="utf-8") == "private"


def test_managed_directory_listing_rejects_non_directory(tmp_path: Path) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        list_managed_directory_names,
    )

    target = tmp_path / "accounts"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(UnsafeManagedPathError):
        list_managed_directory_names(target)


def test_managed_directory_listing_detects_reparse_root_without_is_junction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import magi_plugin_sdk.fs as sdk_fs

    external = tmp_path / "external"
    external.mkdir()
    (external / "private.json").write_text("private", encoding="utf-8")
    target = tmp_path / "accounts"
    try:
        target.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")
    original_lstat = os.lstat

    class WindowsJunctionStat:
        st_mode = stat.S_IFDIR | 0o700
        st_file_attributes = 0x0400
        st_dev = 17
        st_ino = 29

    def fake_lstat(path: os.PathLike[str] | str, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        if Path(path) == target and stat.S_ISLNK(result.st_mode):
            return WindowsJunctionStat()
        return result

    monkeypatch.delattr(Path, "is_junction", raising=False)
    monkeypatch.setattr(os, "lstat", fake_lstat)

    with pytest.raises(sdk_fs.UnsafeManagedPathError):
        sdk_fs.list_managed_directory_names(target)

    assert (external / "private.json").read_text(encoding="utf-8") == "private"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor test")
def test_managed_directory_listing_rejects_ancestor_replaced_before_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import magi_plugin_sdk.fs as sdk_fs

    managed_root = tmp_path / "managed"
    target = managed_root / "accounts"
    target.mkdir(parents=True)
    (target / "managed.json").write_text("managed", encoding="utf-8")
    external_root = tmp_path / "external"
    external_target = external_root / "accounts"
    external_target.mkdir(parents=True)
    (external_target / "private.json").write_text("private", encoding="utf-8")
    parked_root = tmp_path / "parked-managed"
    original_open = os.open
    swapped = False

    def swap_ancestor_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and Path(path) == target and dir_fd is None:
            swapped = True
            managed_root.rename(parked_root)
            managed_root.symlink_to(external_root, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_ancestor_before_open)

    with pytest.raises(sdk_fs.UnsafeManagedPathError):
        sdk_fs.list_managed_directory_names(target)

    assert (external_target / "private.json").read_text(encoding="utf-8") == "private"
    assert (parked_root / "accounts" / "managed.json").read_text(
        encoding="utf-8"
    ) == "managed"


def test_windows_managed_directory_listing_rejects_replacement_during_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import magi_plugin_sdk.fs as sdk_fs

    target = tmp_path / "accounts"
    target.mkdir()
    (target / "managed.json").write_text("managed", encoding="utf-8")
    parked = tmp_path / "parked-accounts"
    original_scandir = os.scandir
    swapped = False

    def swap_before_scan(path):
        nonlocal swapped
        if not swapped and Path(path) == target:
            swapped = True
            target.rename(parked)
            target.mkdir()
            (target / "replacement.json").write_text("replacement", encoding="utf-8")
        return original_scandir(path)

    monkeypatch.setattr(sdk_fs, "_IS_WINDOWS", True)
    monkeypatch.setattr(os, "scandir", swap_before_scan)

    with pytest.raises(sdk_fs.UnsafeManagedPathError):
        sdk_fs.list_managed_directory_names(target)

    assert (parked / "managed.json").read_text(encoding="utf-8") == "managed"


def test_managed_read_roundtrip_and_size_limit(tmp_path: Path) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        read_managed_bytes,
        read_managed_text,
    )

    managed = tmp_path / "managed"
    managed.mkdir()
    target = managed / "state.json"
    target.write_text("managed", encoding="utf-8")

    assert read_managed_text(target) == "managed"
    assert read_managed_bytes(target) == b"managed"
    with pytest.raises(UnsafeManagedPathError, match="safe read limit"):
        read_managed_bytes(target, max_bytes=3)


@pytest.mark.parametrize("entry_kind", ["symlink", "hardlink"])
def test_managed_read_ignores_linked_target(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    from magi_plugin_sdk.fs import read_managed_text

    managed = tmp_path / "managed"
    managed.mkdir()
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    target = managed / "state.json"
    if entry_kind == "symlink":
        target.symlink_to(external)
    else:
        os.link(external, target)

    assert read_managed_text(target) is None
    assert external.read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_managed_read_ignores_fifo_without_blocking(tmp_path: Path) -> None:
    from magi_plugin_sdk.fs import read_managed_text

    managed = tmp_path / "managed"
    managed.mkdir()
    target = managed / "state.json"
    os.mkfifo(target)

    assert read_managed_text(target) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow race test")
@pytest.mark.parametrize("replacement", ["symlink", "fifo"])
def test_managed_read_rejects_target_replaced_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    from magi_plugin_sdk.fs import read_managed_text

    managed = tmp_path / "managed"
    managed.mkdir()
    target = managed / "state.json"
    target.write_text("managed", encoding="utf-8")
    external = tmp_path / "external.json"
    external.write_text("external", encoding="utf-8")
    original_open = os.open
    swapped = False

    def replace_target_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and path == target.name and dir_fd is not None:
            swapped = True
            target.unlink()
            if replacement == "symlink":
                target.symlink_to(external)
            else:
                os.mkfifo(target)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", replace_target_before_open)

    assert read_managed_text(target) is None
    assert external.read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_managed_write_replaces_fifo_without_opening_it(tmp_path: Path) -> None:
    from magi_plugin_sdk.fs import atomic_write_managed_text

    managed = tmp_path / "managed"
    managed.mkdir()
    target = managed / "state.json"
    os.mkfifo(target)

    atomic_write_managed_text(target, "managed")

    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "managed"


@pytest.mark.parametrize("operation", ["write", "remove", "read"])
def test_managed_file_operations_reject_linked_parent(
    tmp_path: Path,
    operation: str,
) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        atomic_write_managed_text,
        read_managed_text,
        remove_managed_file,
    )

    external = tmp_path / "external"
    external.mkdir()
    external_target = external / "state.json"
    external_target.write_text("external", encoding="utf-8")
    linked_parent = tmp_path / "managed"
    linked_parent.symlink_to(external, target_is_directory=True)
    target = linked_parent / "state.json"

    with pytest.raises(UnsafeManagedPathError):
        if operation == "write":
            atomic_write_managed_text(target, "changed")
        elif operation == "read":
            read_managed_text(target)
        else:
            remove_managed_file(target)

    assert external_target.read_text(encoding="utf-8") == "external"


@pytest.mark.parametrize("operation", ["write", "remove", "read"])
def test_managed_file_operations_reject_linked_ancestor(
    tmp_path: Path,
    operation: str,
) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        atomic_write_managed_text,
        read_managed_text,
        remove_managed_file,
    )

    external = tmp_path / "external"
    nested = external / "nested"
    nested.mkdir(parents=True)
    external_target = nested / "state.json"
    external_target.write_text("external", encoding="utf-8")
    linked_ancestor = tmp_path / "linked"
    linked_ancestor.symlink_to(external, target_is_directory=True)
    target = linked_ancestor / "nested" / "state.json"

    with pytest.raises(UnsafeManagedPathError):
        if operation == "write":
            atomic_write_managed_text(target, "changed")
        elif operation == "read":
            read_managed_text(target)
        else:
            remove_managed_file(target)

    assert external_target.read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor test")
@pytest.mark.parametrize("operation", ["write", "remove", "read"])
def test_managed_file_operations_reject_ancestor_replaced_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    import magi_plugin_sdk.fs as sdk_fs

    managed_root = tmp_path / "managed"
    managed_parent = managed_root / "nested"
    managed_parent.mkdir(parents=True)
    managed_target = managed_parent / "state.json"
    managed_target.write_text("managed", encoding="utf-8")
    external_root = tmp_path / "external"
    external_parent = external_root / "nested"
    external_parent.mkdir(parents=True)
    external_target = external_parent / "state.json"
    external_target.write_text("external", encoding="utf-8")
    parked_root = tmp_path / "parked-managed"
    original_open = os.open
    swapped = False

    def swap_ancestor_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and Path(path) == managed_parent and dir_fd is None:
            swapped = True
            managed_root.rename(parked_root)
            managed_root.symlink_to(external_root, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_ancestor_before_open)

    with pytest.raises(sdk_fs.UnsafeManagedPathError):
        if operation == "write":
            sdk_fs.atomic_write_managed_text(managed_target, "changed")
        elif operation == "read":
            sdk_fs.read_managed_text(managed_target)
        else:
            sdk_fs.remove_managed_file(managed_target)

    assert external_target.read_text(encoding="utf-8") == "external"
    assert (parked_root / "nested" / "state.json").read_text(
        encoding="utf-8"
    ) == "managed"


@pytest.mark.parametrize("operation", ["write", "remove"])
def test_managed_file_operations_reject_directory_target(
    tmp_path: Path,
    operation: str,
) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        atomic_write_managed_text,
        remove_managed_file,
    )

    managed = tmp_path / "managed"
    managed.mkdir()
    target = managed / "state.json"
    target.mkdir()

    with pytest.raises(UnsafeManagedPathError):
        if operation == "write":
            atomic_write_managed_text(target, "changed")
        else:
            remove_managed_file(target)

    assert target.is_dir()


def test_managed_read_and_remove_treat_missing_parent_as_empty(
    tmp_path: Path,
) -> None:
    from magi_plugin_sdk.fs import read_managed_text, remove_managed_file

    target = tmp_path / "missing" / "state.json"

    assert read_managed_text(target) is None
    assert remove_managed_file(target) is False
