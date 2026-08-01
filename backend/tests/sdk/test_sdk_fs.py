import os
from pathlib import Path

import pytest


def test_sdk_exposes_atomic_io():
    from magi_plugin_sdk.fs import (  # noqa: F401
        append_jsonl,
        append_jsonl_many,
        atomic_write_bytes,
        atomic_write_managed_bytes,
        atomic_write_managed_text,
        atomic_write_text,
        remove_managed_file,
    )


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


def test_host_atomic_io_reexports_sdk():
    from magi.agent.workspace_cache.atomic_io import atomic_write_text as host_fn
    from magi_plugin_sdk.fs import atomic_write_text as sdk_fn

    assert host_fn is sdk_fn


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


@pytest.mark.parametrize("operation", ["write", "remove"])
def test_managed_file_operations_reject_linked_parent(
    tmp_path: Path,
    operation: str,
) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        atomic_write_managed_text,
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
        else:
            remove_managed_file(target)

    assert external_target.read_text(encoding="utf-8") == "external"


@pytest.mark.parametrize("operation", ["write", "remove"])
def test_managed_file_operations_reject_linked_ancestor(
    tmp_path: Path,
    operation: str,
) -> None:
    from magi_plugin_sdk.fs import (
        UnsafeManagedPathError,
        atomic_write_managed_text,
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
        else:
            remove_managed_file(target)

    assert external_target.read_text(encoding="utf-8") == "external"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor test")
@pytest.mark.parametrize("operation", ["write", "remove"])
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
        else:
            sdk_fs.remove_managed_file(managed_target)

    assert external_target.read_text(encoding="utf-8") == "external"
    assert (parked_root / "nested" / "state.json").read_text(encoding="utf-8") == "managed"


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
