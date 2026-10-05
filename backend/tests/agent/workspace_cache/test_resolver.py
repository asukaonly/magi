"""Tests for resolve_session_cache and the public package surface."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache import (
    resolve_session_cache,
)


def test_resolving_existing_session_preserves_journals_and_snapshots(tmp_path):
    first = resolve_session_cache(tmp_path, "session-1")
    target = tmp_path / "file.txt"
    target.write_text("first content")
    read = first.record_read(target)
    snapshot = first.write_snapshot(target.read_bytes())
    edit = first.record_edit(
        path=target,
        op="write",
        sha256_before=snapshot.sha256,
        sha256_after="a" * 64,
        snapshot_ref=snapshot.sha256,
    )
    journals = (first.reads_log.read_bytes(), first.edits_log.read_bytes())
    second = resolve_session_cache(tmp_path, "session-1")
    assert second.session_dir == first.session_dir
    assert second.session_id == "session-1"
    assert second.root.workspace_root == tmp_path.resolve()
    assert (second.reads_log.read_bytes(), second.edits_log.read_bytes()) == journals
    assert list(second.iter_reads()) == [read]
    assert list(second.iter_edits()) == [edit]
    assert second.read_snapshot(snapshot) == b"first content"
    assert second.has_read(target) is True
    other = resolve_session_cache(tmp_path, "session-2")
    assert list(other.iter_reads()) == list(other.iter_edits()) == []
    assert list(other.snapshots_dir.iterdir()) == []


def test_resolve_session_cache_rejects_bad_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_session_cache(tmp_path, "../escape")
