"""Tests for MediaSelector — period → representative asset_ref."""

from __future__ import annotations

from typing import List

import pytest


class _StubSource:
    def __init__(self, source_id: str, assets: List[dict]) -> None:
        self.source_id = source_id
        self._assets = assets

    async def list_assets(self, *, start: float, end: float) -> List[dict]:
        return [a for a in self._assets if start <= a["timestamp"] <= end]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sources",
    [[], [("photo-library", [])], [("photo-library", [{"ref": "p://outside", "timestamp": 50.0}])]],
)
async def test_selection_without_assets_in_window(sources):
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    registry = MediaSourceRegistry()
    for source_id, assets in sources:
        registry.register(_StubSource(source_id, assets))
    assert await MediaSelector(registry=registry).pick_representative(start=1000, end=2000) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "priority,expected",
    [
        (("photo-library", "chat-attachments"), "p://earliest"),
        (("chat-attachments", "photo-library"), "c://chat"),
    ],
)
async def test_selection_uses_configured_priority_then_timestamp(priority, expected):
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    registry = MediaSourceRegistry()
    registry.register(_StubSource("chat-attachments", [{"ref": "c://chat", "timestamp": 50.0}]))
    registry.register(
        _StubSource(
            "photo-library",
            [
                {"ref": "p://later", "timestamp": 200.0},
                {"ref": "p://earliest", "timestamp": 100.0},
            ],
        )
    )
    selector = MediaSelector(registry=registry, source_priority=priority)
    assert await selector.pick_representative(start=0, end=300) == expected


@pytest.mark.asyncio
async def test_pick_representative_falls_through_priority_when_first_empty():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", []))
    reg.register(_StubSource("chat-attachments", [
        {"ref": "c://x", "timestamp": 50.0},
    ]))
    sel = MediaSelector(
        registry=reg,
        source_priority=("photo-library", "chat-attachments"),
    )
    ref = await sel.pick_representative(start=0.0, end=100.0, hint="hero")
    assert ref == "c://x"
