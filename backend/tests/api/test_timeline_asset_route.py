"""Tests for the timeline asset serving (GET /api/timeline/asset/{ref:path})."""

from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.timeline import timeline_router
from magi.memory.manual_entries.asset_store import ManualEntryAssetStore
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


@pytest.mark.asyncio
async def test_serve_asset_streams_apple_photos_metadata_file(tmp_path):
    fake_file = tmp_path / "IMG.heic"
    fake_file.write_bytes(b"apple-photo-bytes")

    class _FakeL1:
        async def query_events(self, **kwargs):
            assert kwargs["source_filters"] == [
                "photo_library",
                "photo_library_apple_photos",
                "photo_library_directory",
            ]
            return [
                {
                    "event_id": "evt-apple-photo",
                    "source": "photo_library_apple_photos",
                    "timestamp": 1782300426.499,
                    "metadata_json": {
                        "representative_photos": [
                            {
                                "asset_local_id": (
                                    "apple-photos:"
                                    "9456A1CD-8623-4061-88F0-13BA88023FAA"
                                ),
                                "path": str(fake_file),
                            }
                        ]
                    },
                }
            ]

    unified = type("Unified", (), {"l1": _FakeL1()})()
    service = TimelineService(unified)

    result = await service.serve_asset(
        asset_ref="photo-library://apple-photos:9456A1CD-8623-4061-88F0-13BA88023FAA"
    )

    assert result == (b"apple-photo-bytes", "image/heic")


@pytest.mark.asyncio
async def test_serve_asset_streams_encoded_manual_entry_asset(
    unified_memory_for_tests, tmp_path,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"cover-bytes", content_type="image/jpeg")

    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )

    result = await service.serve_asset(asset_ref=quote(asset_ref, safe=""))

    assert result == (b"cover-bytes", "image/jpeg")


def test_public_timeline_asset_route_streams_manual_entry_asset(
    tmp_path, monkeypatch,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"cover-route-bytes", content_type="image/png")
    app = FastAPI()
    app.include_router(
        _build_public_router(timeline_router, _PUBLIC_ROUTE_METHODS["timeline"]),
        prefix="/api/timeline",
    )

    monkeypatch.setattr("magi.api.routers.timeline.get_unified_memory", lambda: object())
    monkeypatch.setattr(
        "magi.api.routers.timeline.get_manual_entry_asset_store",
        lambda: asset_store,
    )

    response = TestClient(app).get(f"/api/timeline/asset/{quote(asset_ref, safe='')}")

    assert response.status_code == 200
    assert response.content == b"cover-route-bytes"
    assert response.headers["content-type"] == "image/png"
