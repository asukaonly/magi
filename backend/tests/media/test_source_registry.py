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


def test_registry_keeps_source_identity_and_rejects_replacement():
    from magi.media.source_registry import MediaSourceRegistry

    registry = MediaSourceRegistry()
    photo = _StubSource("photo-library", [])
    chat = _StubSource("chat-attachments", [])
    registry.register(photo)
    registry.register(chat)
    assert {source.source_id: source for source in registry.iter_sources()} == {
        "photo-library": photo,
        "chat-attachments": chat,
    }
    assert registry.get("photo-library") is photo
    assert registry.get("chat-attachments") is chat
    assert registry.get("missing") is None
    with pytest.raises(ValueError, match="photo-library"):
        registry.register(_StubSource("photo-library", []))
    assert registry.get("photo-library") is photo
    assert list(registry.iter_sources()) == [photo, chat]


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
