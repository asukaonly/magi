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
async def test_pick_representative_returns_none_when_no_sources():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    sel = MediaSelector(registry=MediaSourceRegistry())
    out = await sel.pick_representative(start=0.0, end=100.0, hint="hero")
    assert out is None


@pytest.mark.asyncio
async def test_pick_representative_returns_none_when_no_assets_in_window():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", [
        {"ref": "p://a", "timestamp": 50.0},
    ]))
    sel = MediaSelector(registry=reg)
    out = await sel.pick_representative(start=1000.0, end=2000.0, hint="hero")
    assert out is None


@pytest.mark.asyncio
async def test_pick_representative_picks_first_from_source_priority():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", [
        {"ref": "p://earliest", "timestamp": 100.0},
        {"ref": "p://later", "timestamp": 200.0},
    ]))
    reg.register(_StubSource("chat-attachments", [
        {"ref": "c://chat", "timestamp": 150.0},
    ]))
    sel = MediaSelector(
        registry=reg,
        source_priority=("photo-library", "chat-attachments"),
    )
    ref = await sel.pick_representative(start=0.0, end=300.0, hint="hero")
    # Default policy: walk source_priority order; within first source with
    # any assets, take the earliest. Plan 2 swaps in a richer scorer.
    assert ref == "p://earliest"


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
