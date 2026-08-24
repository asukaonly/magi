"""Tests for SessionCache edit recording."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache.contracts import EditRecord
from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot
from magi_plugin_sdk.workspace_cache.session import SessionCache


def _sc(tmp_path: Path) -> SessionCache:
    return SessionCache(root=WorkspaceCacheRoot.ensure(tmp_path), session_id="s1")


def test_record_edit_writes_jsonl_line(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    rec = sc.record_edit(
        path=tmp_path / "f.txt",
        op="replace",
        sha256_before="a" * 64,
        sha256_after="b" * 64,
        snapshot_ref="c" * 64,
    )
    assert isinstance(rec, EditRecord)
    log = tmp_path / ".magi" / "sessions" / "s1" / "edits.jsonl"
    assert log.read_text().count("\n") == 1


def test_record_edit_rejects_outside_workspace(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    with pytest.raises(ValueError):
        sc.record_edit(
            path=tmp_path.parent / "f.txt",
            op="replace",
            sha256_before="a" * 64,
            sha256_after="b" * 64,
            snapshot_ref="c" * 64,
        )


def test_record_edit_rejects_invalid_op(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    with pytest.raises(ValueError):
        sc.record_edit(
            path=tmp_path / "f.txt",
            op="explode",  # type: ignore[arg-type]
            sha256_before="a" * 64,
            sha256_after="b" * 64,
            snapshot_ref="c" * 64,
        )


def test_iter_edits_returns_records_in_order(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    sc.record_edit(
        path=tmp_path / "a.txt",
        op="replace",
        sha256_before="0" * 64,
        sha256_after="1" * 64,
        snapshot_ref="2" * 64,
    )
    sc.record_edit(
        path=tmp_path / "b.txt",
        op="write",
        sha256_before="3" * 64,
        sha256_after="4" * 64,
        snapshot_ref="5" * 64,
    )
    edits = list(sc.iter_edits())
    assert [e.path for e in edits] == ["a.txt", "b.txt"]
    assert [e.op for e in edits] == ["replace", "write"]
