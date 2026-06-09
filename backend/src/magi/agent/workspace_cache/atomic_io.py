"""Atomic file IO — re-exported from magi_plugin_sdk.fs (the canonical home)."""
from magi_plugin_sdk.fs import (  # noqa: F401
    append_jsonl,
    atomic_write_bytes,
    atomic_write_text,
)

__all__ = ["atomic_write_text", "atomic_write_bytes", "append_jsonl"]
