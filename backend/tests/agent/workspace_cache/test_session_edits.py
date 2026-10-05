"""Tests for SessionCache edit recording."""

from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot
from magi_plugin_sdk.workspace_cache.session import SessionCache


def _sc(tmp_path: Path) -> SessionCache:
    return SessionCache(root=WorkspaceCacheRoot.ensure(tmp_path), session_id="s1")


@pytest.mark.parametrize("operation", ["replace", "write", "delete"])
def test_edit_journal_preserves_complete_evidence_in_durable_order(
    tmp_path, monkeypatch, operation
):
    import json

    monkeypatch.setattr("magi_plugin_sdk.workspace_cache.session._now_ms", lambda: 123456)
    sc = _sc(tmp_path)
    records = []
    for index in range(2):
        record = sc.record_edit(
            path=tmp_path / "src" / f"file-{index}.txt",
            op=operation,
            sha256_before="a" * 64,
            sha256_after=str(index) * 64,
            snapshot_ref="c" * 64,
        )
        expected = {
            "path": f"src/file-{index}.txt",
            "op": operation,
            "sha256_before": "a" * 64,
            "sha256_after": str(index) * 64,
            "snapshot_ref": "c" * 64,
            "ts_ms": 123456,
        }
        assert record.model_dump() == expected
        records.append(expected)
    assert [json.loads(line) for line in sc.edits_log.read_text().splitlines()] == records
    assert [record.model_dump() for record in _sc(tmp_path).iter_edits()] == records


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


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("op", "explode"),
        ("sha256_before", "bad"),
        ("sha256_after", "g" * 64),
        ("snapshot_ref", "short"),
    ],
)
def test_invalid_edit_evidence_is_rejected_without_appending_to_journal(tmp_path, field, bad_value):
    from pydantic import ValidationError

    sc = _sc(tmp_path)
    values = dict(
        path=tmp_path / "f.txt",
        op="write",
        sha256_before="a" * 64,
        sha256_after="b" * 64,
        snapshot_ref="c" * 64,
    )
    original = sc.record_edit(**values)
    prior_bytes = sc.edits_log.read_bytes()
    with pytest.raises(ValidationError) as error:
        sc.record_edit(**{**values, field: bad_value})
    assert error.value.errors()[0]["loc"] == (field,)
    assert sc.edits_log.read_bytes() == prior_bytes
    assert list(sc.iter_edits()) == [original]
