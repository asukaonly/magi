"""Tests for the snapshot-and-record helper used by file_edit / file_write."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from magi_plugin_sdk.workspace_cache import resolve_session_cache
from magi.tools.builtin._edit_journal import (
    SnapshotContext,
    record_edit_after,
    snapshot_before_edit,
)


def _ctx(workspace: Path, session_id: str | None = "s1") -> SimpleNamespace:
    return SimpleNamespace(
        workspace=str(workspace),
        env_vars={"session_id": session_id} if session_id else {},
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_snapshot_before_edit_returns_none_without_session(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old")
    assert snapshot_before_edit(_ctx(tmp_path, session_id=None), str(target)) is None


def test_snapshot_before_edit_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert snapshot_before_edit(_ctx(tmp_path), str(tmp_path / "nope.txt")) is None


def test_snapshot_before_edit_captures_existing_bytes(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"old payload")
    snap = snapshot_before_edit(_ctx(tmp_path), str(target))
    assert isinstance(snap, SnapshotContext)
    assert snap.sha256_before == _sha256_bytes(b"old payload")
    sc = resolve_session_cache(tmp_path, "s1")
    assert sc.read_snapshot(snap.snapshot_ref) == b"old payload"


def test_snapshot_then_record_writes_edit_record(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"v1")
    ctx = _ctx(tmp_path)
    snap = snapshot_before_edit(ctx, str(target))
    assert snap is not None
    target.write_bytes(b"v2")
    record_edit_after(ctx, str(target), snap, op="replace")
    sc = resolve_session_cache(tmp_path, "s1")
    edits = list(sc.iter_edits())
    assert len(edits) == 1
    rec = edits[0]
    assert rec.op == "replace"
    assert rec.path == "f.txt"
    assert rec.sha256_before == snap.sha256_before
    assert rec.sha256_after == _sha256_bytes(b"v2")
    assert rec.snapshot_ref == snap.snapshot_ref.sha256


def test_snapshot_outside_workspace_returns_none(tmp_path: Path) -> None:
    inside = tmp_path / "ws"
    inside.mkdir()
    outside = tmp_path / "elsewhere.txt"
    outside.write_bytes(b"old")
    ctx = _ctx(inside)
    assert snapshot_before_edit(ctx, str(outside)) is None


def test_record_edit_after_no_snapshot_is_silent(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"v1")
    ctx = _ctx(tmp_path, session_id=None)
    record_edit_after(ctx, str(target), None, op="replace")
