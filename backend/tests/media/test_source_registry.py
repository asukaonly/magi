"""Tests for the MediaSourceRegistry."""

from __future__ import annotations

from typing import List

import pytest


class _StubSource:
    """Minimal stand-in matching the MediaSource protocol."""

    def __init__(self, source_id: str, assets: List[dict]) -> None:
        self.source_id = source_id
        self._assets = assets

    async def list_assets(self, *, start: float, end: float) -> List[dict]:
        return [a for a in self._assets if start <= a["timestamp"] <= end]


def test_register_and_list_sources():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    a = _StubSource("photo-library", [])
    b = _StubSource("chat-attachments", [])
    reg.register(a)
    reg.register(b)

    ids = sorted(s.source_id for s in reg.iter_sources())
    assert ids == ["chat-attachments", "photo-library"]


def test_register_duplicate_raises():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", []))
    with pytest.raises(ValueError, match="photo-library"):
        reg.register(_StubSource("photo-library", []))


def test_get_source_by_id():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    src = _StubSource("photo-library", [])
    reg.register(src)
    assert reg.get("photo-library") is src
    assert reg.get("missing") is None


@pytest.mark.asyncio
async def test_collect_assets_across_sources():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", [
        {"ref": "p://a", "timestamp": 100.0},
        {"ref": "p://b", "timestamp": 500.0},
    ]))
    reg.register(_StubSource("chat-attachments", [
        {"ref": "c://x", "timestamp": 200.0},
    ]))

    items = await reg.collect_assets(start=50.0, end=300.0)
    refs = sorted(i["ref"] for i in items)
    assert refs == ["c://x", "p://a"]
