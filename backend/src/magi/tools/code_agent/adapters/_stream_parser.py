"""Tiny JSONL parser used by both adapters.

Each line of stdout that is valid JSON becomes a dict; invalid / blank lines
are silently skipped. Adapters wrap these dicts into typed ``RunEvent`` based
on their tool's specific schema.
"""
from __future__ import annotations

import json
from typing import Iterator


def parse_jsonl_lines(raw: bytes) -> Iterator[dict]:
    for line in raw.splitlines():
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


__all__ = ["parse_jsonl_lines"]
