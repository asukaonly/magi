import os
from pathlib import Path

import pytest


def test_sdk_exposes_atomic_io():
    from magi_plugin_sdk.fs import (  # noqa: F401
        append_jsonl,
        append_jsonl_many,
        atomic_write_bytes,
        atomic_write_text,
    )


def test_atomic_write_text_roundtrip(tmp_path: Path):
    from magi_plugin_sdk.fs import atomic_write_text

    target = tmp_path / "nested" / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_append_jsonl(tmp_path: Path):
    from magi_plugin_sdk.fs import append_jsonl

    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"a": 1})
    append_jsonl(target, {"b": 2})
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_append_jsonl_many_restores_file_when_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi_plugin_sdk.fs import append_jsonl, append_jsonl_many

    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"existing": True})
    original = target.read_bytes()
    original_fsync = os.fsync
    calls = 0

    def fail_first_sync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected sync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_first_sync)

    with pytest.raises(OSError, match="injected sync failure"):
        append_jsonl_many(target, ({"new": 1}, {"new": 2}))

    assert target.read_bytes() == original


def test_host_atomic_io_reexports_sdk():
    from magi.agent.workspace_cache.atomic_io import atomic_write_text as host_fn
    from magi_plugin_sdk.fs import atomic_write_text as sdk_fn

    assert host_fn is sdk_fn
