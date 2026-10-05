"""Tests for SessionCache snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache.contracts import SnapshotRef
from magi_plugin_sdk.workspace_cache.errors import SnapshotIntegrityError
from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot
from magi_plugin_sdk.workspace_cache.session import SessionCache


def _sc(tmp_path: Path) -> SessionCache:
    return SessionCache(root=WorkspaceCacheRoot.ensure(tmp_path), session_id="s1")


@pytest.mark.parametrize("payload", [b"", b"hello", b"\x00\x01\xfftext"])
def test_snapshot_roundtrip_uses_content_digest_and_preserves_binary_bytes(tmp_path, payload):
    sc = _sc(tmp_path)
    ref = sc.write_snapshot(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert ref.sha256 == digest
    assert (sc.snapshots_dir / f"{digest}.bin").read_bytes() == payload
    assert _sc(tmp_path).read_snapshot(ref) == payload


def test_write_snapshot_dedupes_identical_content(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    sc.write_snapshot(b"same")
    sc.write_snapshot(b"same")
    snap_dir = tmp_path / ".magi" / "sessions" / "s1" / "snapshots"
    files = list(snap_dir.iterdir())
    assert len(files) == 1


def test_read_snapshot_detects_corruption(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    ref = sc.write_snapshot(b"data")
    snap_path = tmp_path / ".magi" / "sessions" / "s1" / "snapshots" / f"{ref.sha256}.bin"
    snap_path.write_bytes(b"tampered")
    from magi_plugin_sdk.workspace_cache.errors import WorkspaceCacheError

    with pytest.raises(WorkspaceCacheError, match="bytes do not match expected hash") as error:
        sc.read_snapshot(ref)

    assert type(error.value) is SnapshotIntegrityError


def test_read_snapshot_missing_raises_file_not_found(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    with pytest.raises(FileNotFoundError):
        sc.read_snapshot(SnapshotRef(sha256="0" * 64))
