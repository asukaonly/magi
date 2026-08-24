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


def test_write_snapshot_returns_sha256_ref(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    payload = b"hello"
    ref = sc.write_snapshot(payload)
    assert ref.sha256 == hashlib.sha256(payload).hexdigest()


def test_read_snapshot_round_trips(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    payload = b"\x00\x01\xfftext"
    ref = sc.write_snapshot(payload)
    assert sc.read_snapshot(ref) == payload


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
    with pytest.raises(SnapshotIntegrityError):
        sc.read_snapshot(ref)


def test_read_snapshot_missing_raises_file_not_found(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    with pytest.raises(FileNotFoundError):
        sc.read_snapshot(SnapshotRef(sha256="0" * 64))


def test_write_snapshot_empty_payload(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    ref = sc.write_snapshot(b"")
    assert sc.read_snapshot(ref) == b""
