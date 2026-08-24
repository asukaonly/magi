"""Tests for SessionCache read recording."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache.root import WorkspaceCacheRoot
from magi_plugin_sdk.workspace_cache.session import SessionCache


def _make_session(tmp_path: Path) -> SessionCache:
    root = WorkspaceCacheRoot.ensure(tmp_path)
    return SessionCache(root=root, session_id="s1")


def test_record_read_writes_jsonl_line(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    target = tmp_path / "src" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('hi')\n")
    rec = sc.record_read(target)
    assert rec.path == "src/a.py"
    assert rec.size_bytes == target.stat().st_size
    assert rec.line_count == 1
    assert len(rec.sha256) == 64
    log_path = tmp_path / ".magi" / "sessions" / "s1" / "reads.jsonl"
    assert log_path.exists()
    assert log_path.read_text().count("\n") == 1


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


def test_has_read_returns_false_when_content_changed(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("hello")
    sc.record_read(target)
    target.write_text("hello world")
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
    time.sleep(0.005)
    sc.record_read(b)
    paths = [rec.path for rec in sc.iter_reads()]
    assert paths == ["a.txt", "b.txt"]


def test_record_read_relative_path_is_posix_style(tmp_path: Path) -> None:
    sc = _make_session(tmp_path)
    nested = tmp_path / "a" / "b" / "c.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x")
    rec = sc.record_read(nested)
    assert rec.path == "a/b/c.txt"
