"""File IO contracts shared by workspace cache and plugin storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi_plugin_sdk.fs import append_jsonl, atomic_write_bytes, atomic_write_text


@pytest.mark.parametrize("kind", ["text", "bytes"])
@pytest.mark.parametrize("existing", [False, True])
def test_atomic_write_creates_or_replaces_nested_file_without_temp_residue(
    tmp_path: Path, kind, existing
):
    target = tmp_path / "nested" / "deeper" / "output"
    if existing:
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old payload that must not survive")
    if kind == "text":
        atomic_write_text(target, "新内容\nsecond line")
        expected = "新内容\nsecond line".encode("utf-8")
    else:
        expected = b"\x00\x01binary\xff"
        atomic_write_bytes(target, expected)
    assert target.read_bytes() == expected
    assert list(target.parent.iterdir()) == [target]


def test_append_jsonl_preserves_records_and_escapes_embedded_newlines(tmp_path: Path):
    target = tmp_path / "deep" / "log.jsonl"
    records = [{"a": 1}, {"a": 2, "text": "中文\nsecond line"}]
    for record in records:
        append_jsonl(target, record)
    raw = target.read_bytes()
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 2
    assert [json.loads(line) for line in raw.splitlines()] == records


@pytest.mark.parametrize("existing", [False, True])
def test_append_jsonl_rejects_non_serializable_without_changing_prior_bytes(
    tmp_path: Path, existing
):
    target = tmp_path / "log.jsonl"
    before = b'{"keep":true}\n' if existing else b""
    if existing:
        target.write_bytes(before)
    with pytest.raises(TypeError):
        append_jsonl(target, {"bad": object()})
    assert (target.read_bytes() if target.exists() else b"") == before
