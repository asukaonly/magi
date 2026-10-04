"""Tests for the snapshot-and-record helper used by file_edit / file_write."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from magi.tools.builtin._edit_journal import (
    record_edit_after,
    snapshot_before_edit,
)


def _ctx(workspace: Path, session_id: str | None = "s1") -> SimpleNamespace:
    return SimpleNamespace(
        workspace=str(workspace),
        env_vars={"session_id": session_id} if session_id else {},
    )


def test_snapshot_outside_workspace_returns_none(tmp_path: Path) -> None:
    inside = tmp_path / "ws"
    inside.mkdir()
    outside = tmp_path / "elsewhere.txt"
    outside.write_bytes(b"old")
    ctx = _ctx(inside)
    assert snapshot_before_edit(ctx, str(outside)) is None


def test_record_without_snapshot_leaves_file_and_workspace_cache_untouched(tmp_path, monkeypatch):
    from unittest.mock import Mock

    target = tmp_path / "f.txt"
    target.write_bytes(b"v1")
    cache = Mock(side_effect=AssertionError("Unexpected cache access"))
    monkeypatch.setattr("magi.tools.builtin._edit_journal.resolve_session_cache", cache)
    record_edit_after(_ctx(tmp_path), str(target), None, op="replace")
    cache.assert_not_called()
    assert target.read_bytes() == b"v1"
    assert list(tmp_path.iterdir()) == [target]
