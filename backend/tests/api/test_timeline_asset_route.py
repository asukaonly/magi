"""Tests for the timeline asset serving (GET /api/timeline/asset/{ref:path})."""

from __future__ import annotations

from pathlib import Path

import pytest

from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_serve_asset_returns_none_for_empty_ref(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    result = await service.serve_asset(asset_ref="")
    assert result is None


@pytest.mark.asyncio
async def test_serve_asset_returns_none_for_unknown_scheme(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    result = await service.serve_asset(asset_ref="unknown://nope.jpg")
    assert result is None


@pytest.mark.asyncio
async def test_serve_asset_returns_none_when_resolver_returns_no_path(
    unified_memory_for_tests, monkeypatch,
):
    """When the photo-library scheme is recognized but the resolver returns no path,
    the route should be a clean 404 (None) rather than crashing."""

    async def fake_resolver(asset_ref: str):
        return None, None

    monkeypatch.setattr(
        "magi.timeline.service._resolve_photo_library_asset",
        fake_resolver,
    )

    service = TimelineService(unified_memory_for_tests)
    result = await service.serve_asset(asset_ref="photo-library://2026-05-17/missing.HEIC")
    assert result is None


@pytest.mark.asyncio
async def test_serve_asset_streams_existing_file(
    unified_memory_for_tests, tmp_path, monkeypatch,
):
    """When the resolver returns a real path, the route reads the bytes and
    returns them along with the content_type."""
    fake_file = tmp_path / "IMG.heic"
    fake_file.write_bytes(b"\x00\x01\x02\x03")

    async def fake_resolver(asset_ref: str):
        if asset_ref == "photo-library://2026-05-17/IMG.HEIC":
            return str(fake_file), "image/heic"
        return None, None

    monkeypatch.setattr(
        "magi.timeline.service._resolve_photo_library_asset",
        fake_resolver,
    )

    service = TimelineService(unified_memory_for_tests)
    result = await service.serve_asset(asset_ref="photo-library://2026-05-17/IMG.HEIC")
    assert result is not None
    body_bytes, content_type = result
    assert body_bytes == b"\x00\x01\x02\x03"
    assert content_type == "image/heic"
