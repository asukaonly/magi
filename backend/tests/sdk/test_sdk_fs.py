from pathlib import Path


def test_sdk_exposes_atomic_io():
    from magi_plugin_sdk.fs import atomic_write_text, atomic_write_bytes, append_jsonl  # noqa: F401


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


def test_host_atomic_io_reexports_sdk():
    from magi.agent.workspace_cache.atomic_io import atomic_write_text as host_fn
    from magi_plugin_sdk.fs import atomic_write_text as sdk_fn

    assert host_fn is sdk_fn
