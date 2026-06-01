"""Tests for PhotoLibraryMediaSource (L1-event-backed)."""

from __future__ import annotations

from typing import List

import pytest


class _FakeL1Store:
    """Stub L1 store that lets us inject events for specific source_filters."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.last_call: dict | None = None

    async def query_events(self, **kwargs) -> list[dict]:
        self.last_call = kwargs
        source_filters = kwargs.get("source_filters") or []
        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        out = []
        for e in self.events:
            if source_filters and e.get("source") not in source_filters:
                continue
            ts = float(e.get("timestamp") or 0.0)
            if start_time is not None and ts < start_time:
                continue
            if end_time is not None and ts > end_time:
                continue
            out.append(e)
        return out


def test_source_id_matches_protocol():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    src = PhotoLibraryMediaSource(l1_store=_FakeL1Store())
    assert src.source_id == "photo-library"


@pytest.mark.asyncio
async def test_list_assets_returns_empty_when_no_events():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    src = PhotoLibraryMediaSource(l1_store=_FakeL1Store())
    out = await src.list_assets(start=0.0, end=1000.0)
    assert out == []


@pytest.mark.asyncio
async def test_list_assets_maps_photo_events_to_asset_dicts():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    l1 = _FakeL1Store()
    # Top-level asset_ref
    l1.events.append({
        "event_id": "evt-1",
        "source": "photo_library",
        "timestamp": 500.0,
        "asset_ref": "photo-library://2026-05-17/IMG_4423.HEIC",
        "mime_type": "image/heic",
        "metadata": {"location": "家", "people": ["alice"]},
    })
    # Asset ref inside content_blocks
    l1.events.append({
        "event_id": "evt-2",
        "source": "photo_library",
        "timestamp": 800.0,
        "content_blocks": [{"kind": "image", "ref": "photo-library://2026-05-17/IMG_4424.HEIC"}],
    })

    src = PhotoLibraryMediaSource(l1_store=l1)
    out = await src.list_assets(start=0.0, end=1000.0)
    refs = sorted(a["ref"] for a in out)
    assert len(out) == 2
    assert refs == [
        "photo-library://2026-05-17/IMG_4423.HEIC",
        "photo-library://2026-05-17/IMG_4424.HEIC",
    ]
    # Each item has timestamp + extra metadata for the selector
    first = next(a for a in out if a["ref"].endswith("IMG_4423.HEIC"))
    assert first["timestamp"] == 500.0
    assert first.get("mime_type") == "image/heic"
    assert first.get("location") == "家"

    # Verify the adapter called the L1 store with the expected source_filters
    assert l1.last_call["source_filters"] == ["photo_library"]
    assert l1.last_call["start_time"] == 0.0
    assert l1.last_call["end_time"] == 1000.0


@pytest.mark.asyncio
async def test_list_assets_skips_events_missing_asset_ref():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    l1 = _FakeL1Store()
    l1.events.append({"event_id": "evt-x", "source": "photo_library", "timestamp": 100.0})
    # No asset_ref — must be skipped, not crash
    src = PhotoLibraryMediaSource(l1_store=l1)
    out = await src.list_assets(start=0.0, end=1000.0)
    assert out == []


@pytest.mark.asyncio
async def test_list_assets_swallows_l1_errors():
    """If the L1 store raises, the adapter returns [] rather than propagating
    (so MediaSourceRegistry.collect_assets fan-out is not derailed)."""
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    class _ErroringL1:
        async def query_events(self, **kwargs):
            raise RuntimeError("L1 dead")

    src = PhotoLibraryMediaSource(l1_store=_ErroringL1())
    out = await src.list_assets(start=0.0, end=1000.0)
    assert out == []
