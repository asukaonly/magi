"""Tests for atomic_write_text, atomic_write_bytes, append_jsonl."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi_plugin_sdk.fs import (
    append_jsonl,
    atomic_write_bytes,
    atomic_write_text,
)


def test_atomic_write_text_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_text_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_no_temp_file_left_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "x")
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    atomic_write_text(target, "x")
    assert target.read_text() == "x"


def test_atomic_write_bytes_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    payload = b"\x00\x01binary\xff"
    atomic_write_bytes(target, payload)
    assert target.read_bytes() == payload


def test_append_jsonl_writes_newline_terminated_record(tmp_path: Path) -> None:
    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"a": 1})
    append_jsonl(target, {"a": 2})
    lines = target.read_text().splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"a": 2}]


def test_append_jsonl_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "log.jsonl"
    append_jsonl(target, {"k": "v"})
    assert target.exists()


def test_append_jsonl_rejects_non_serializable(tmp_path: Path) -> None:
    target = tmp_path / "log.jsonl"
    with pytest.raises(TypeError):
        append_jsonl(target, {"bad": object()})
    assert not target.exists() or target.read_text() == ""


def test_append_jsonl_handles_record_with_embedded_newline(tmp_path: Path) -> None:
    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"text": "line1\nline2"})
    lines = target.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"text": "line1\nline2"}
