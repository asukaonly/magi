"""Tests for SessionCache read recording."""

from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot
from magi_plugin_sdk.workspace_cache.session import SessionCache


def _make_session(tmp_path: Path) -> SessionCache:
    root = WorkspaceCacheRoot.ensure(tmp_path)
    return SessionCache(root=root, session_id="s1")


def test_read_journal_preserves_exact_file_evidence_in_portable_path(tmp_path, monkeypatch):
    import hashlib
    import json
    import os

    monkeypatch.setattr("magi_plugin_sdk.workspace_cache.session._now_ms", lambda: 123456)
    sc = _make_session(tmp_path)
    target = tmp_path / "src" / "nested" / "a.py"
    target.parent.mkdir(parents=True)
    data = b"first line\nsecond line\nlast"
    target.write_bytes(data)
    os.utime(target, (100, 100))
    rec = sc.record_read(target)
    expected = {
        "path": "src/nested/a.py",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "line_count": 2,
        "mtime_ms": 100000,
        "ts_ms": 123456,
    }
    assert rec.model_dump() == expected
    assert [json.loads(line) for line in sc.reads_log.read_text().splitlines()] == [expected]
    reloaded = _make_session(tmp_path)
    assert list(reloaded.iter_reads()) == [rec]
    assert reloaded.has_read(target) is True


def test_record_read_rejects_path_outside_workspace(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    outside = tmp_path.parent / "elsewhere.txt"
    outside.write_text("x")
    with pytest.raises(ValueError):
        sc.record_read(outside)


def test_record_read_rejects_missing_file(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    with pytest.raises(FileNotFoundError):
        sc.record_read(tmp_path / "nope.txt")


def test_has_read_returns_true_when_unchanged(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("hello")
    sc.record_read(target)
    assert sc.has_read(target) is True


def test_read_freshness_uses_digest_when_size_and_mtime_are_unchanged(tmp_path):
    import os

    sc = _make_session(tmp_path)
    target = tmp_path / "f.txt"
    target.write_bytes(b"hello")
    rec = sc.record_read(target)
    original_stat = target.stat()
    assert sc.has_read(target) is True
    target.write_bytes(b"world")
    os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert target.stat().st_size == rec.size_bytes
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert sc.has_read(target) is False


def test_has_read_returns_false_when_never_read(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("x")
    assert sc.has_read(target) is False


def test_has_read_returns_false_when_file_deleted(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("x")
    sc.record_read(target)
    target.unlink()
    assert sc.has_read(target) is False


def test_iter_reads_returns_records_in_order(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("aa")
    b.write_text("bb")
    sc.record_read(a)
    sc.record_read(b)
    paths = [rec.path for rec in sc.iter_reads()]
    assert paths == ["a.txt", "b.txt"]


@pytest.mark.parametrize(
    "field,bad_value", [("sha256", "abc"), ("sha256", "g" * 64), ("size_bytes", -1)]
)
def test_loading_read_journal_rejects_corrupt_record_fields(tmp_path, field, bad_value):
    import json
    from pydantic import ValidationError

    sc = _make_session(tmp_path)
    target = tmp_path / "file.txt"
    target.write_text("ok")
    original = sc.record_read(target).model_dump()
    corrupted = {**original, field: bad_value}
    sc.reads_log.write_text(json.dumps(original) + "\n" + json.dumps(corrupted) + "\n")
    records = sc.iter_reads()
    assert next(records).model_dump() == original
    with pytest.raises(ValidationError) as error:
        next(records)
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("journal", ["reads", "edits"])
def test_invalid_json_journal_reports_cache_error_at_the_corrupt_line(tmp_path, journal):
    from magi_plugin_sdk.workspace_cache.errors import WorkspaceCacheError, SessionCacheCorruptError

    sc = _make_session(tmp_path)
    log = getattr(sc, f"{journal}_log")
    log.write_text("\n{invalid-json}\n")
    with pytest.raises(
        WorkspaceCacheError, match=rf"{journal}.jsonl line 2 is not valid JSON"
    ) as error:
        list(getattr(sc, f"iter_{journal}")())
    assert type(error.value) is SessionCacheCorruptError
