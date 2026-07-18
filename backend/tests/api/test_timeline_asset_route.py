"""Tests for the timeline asset serving (GET /api/timeline/asset/{ref:path})."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.timeline import timeline_router
from magi.memory.manual_entries.models import ManualEntry
from magi.memory.manual_entries.asset_store import ManualEntryAssetStore
from magi.memory.manual_entries.store import ManualEntryStore
from magi.timeline.service import TimelineService
from magi.timeline.cover_store import TimelineCoverPreferenceStore
from _shared.memory_schema import apply_memory_shared_schema


async def _delete_manual_entry(store: ManualEntryStore, entry_id: str) -> None:
    assert await store.request_delete(entry_id, requested_at=time.time())
    assert await store.finalize_delete(entry_id, deleted_at=time.time())


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
    unified_memory_for_tests,
    monkeypatch,
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
    unified_memory_for_tests,
    tmp_path,
    monkeypatch,
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
                                    "apple-photos:9456A1CD-8623-4061-88F0-13BA88023FAA"
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
    unified_memory_for_tests,
    tmp_path,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"cover-bytes", content_type="image/jpeg")
    entry_store = ManualEntryStore(db_path=unified_memory_for_tests.memory_db_path)
    await entry_store.create(
        ManualEntry(
            entry_id="entry-active-asset",
            created_at=time.time(),
            event_at=time.time(),
            body="active",
            attachments=[asset_ref],
        )
    )

    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )

    result = await service.serve_asset(asset_ref=quote(asset_ref, safe=""))

    assert result == (b"cover-bytes", "image/jpeg")


@pytest.mark.asyncio
async def test_serve_asset_requires_a_live_reference(unified_memory_for_tests, tmp_path):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"shared-bytes", content_type="image/png")
    entry_store = ManualEntryStore(db_path=unified_memory_for_tests.memory_db_path)
    for entry_id in ("entry-deleted", "entry-shared"):
        await entry_store.create(
            ManualEntry(
                entry_id=entry_id,
                created_at=time.time(),
                event_at=time.time(),
                body=entry_id,
                attachments=[asset_ref],
            )
        )

    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )
    await _delete_manual_entry(entry_store, "entry-deleted")
    assert await service.serve_asset(asset_ref=asset_ref) == (
        b"shared-bytes",
        "image/png",
    )

    await _delete_manual_entry(entry_store, "entry-shared")
    assert await service.serve_asset(asset_ref=asset_ref) is None


@pytest.mark.asyncio
async def test_serve_asset_rejects_a_delete_gated_manual_entry(
    unified_memory_for_tests,
    tmp_path,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"private-bytes", content_type="image/png")
    entry_store = ManualEntryStore(db_path=unified_memory_for_tests.memory_db_path)
    await entry_store.create(
        ManualEntry(
            entry_id="entry-delete-gated",
            created_at=time.time(),
            event_at=time.time(),
            body="private",
            attachments=[asset_ref],
        )
    )
    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )
    assert await service.serve_asset(asset_ref=asset_ref) == (
        b"private-bytes",
        "image/png",
    )

    assert await entry_store.request_delete(
        "entry-delete-gated",
        requested_at=time.time(),
    )

    assert await service.serve_asset(asset_ref=asset_ref) is None


@pytest.mark.asyncio
async def test_serve_asset_rejects_an_incomplete_manual_entry_replacement(
    unified_memory_for_tests,
    tmp_path,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    old_asset_ref = asset_store.store_bytes(b"old-bytes", content_type="image/png")
    new_asset_ref = asset_store.store_bytes(b"new-bytes", content_type="image/png")
    entry_store = ManualEntryStore(db_path=unified_memory_for_tests.memory_db_path)
    entry = ManualEntry(
        entry_id="entry-replacement-pending",
        created_at=time.time(),
        event_at=time.time(),
        body="before",
        attachments=[old_asset_ref],
        l1_event_id="event-old",
    )
    await entry_store.create(entry)
    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )
    assert await service.serve_asset(asset_ref=old_asset_ref) == (
        b"old-bytes",
        "image/png",
    )

    entry.body = "after"
    entry.attachments = [new_asset_ref]
    assert await entry_store.replace_and_reserve_l1_projection(
        entry,
        "event-new",
        expected_previous_event_id="event-old",
    )

    assert await service.serve_asset(asset_ref=old_asset_ref) is None
    assert await service.serve_asset(asset_ref=new_asset_ref) is None


@pytest.mark.asyncio
async def test_serve_asset_honors_other_user_visible_owners(
    unified_memory_for_tests,
    tmp_path,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"cover-owner", content_type="image/webp")
    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )
    db_path = unified_memory_for_tests.memory_db_path

    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO experiences(
                experience_id, status, time_start, time_end,
                user_cover_asset_ref, created_at, updated_at
            ) VALUES ('experience-cover', 'active', 1, 2, ?, 1, 1)
            """,
            (asset_ref,),
        )
    assert await service.serve_asset(asset_ref=asset_ref) == (
        b"cover-owner",
        "image/webp",
    )

    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE experiences SET status = 'invalidated' WHERE experience_id = 'experience-cover'"
        )
        db.execute(
            """
            INSERT INTO experience_drafts(
                draft_id, status, query_text, title, one_sentence_review,
                time_start, time_end, user_cover_asset_ref, created_at, updated_at
            ) VALUES ('draft-cover', 'editing', '', '', '', 1, 2, ?, 1, 1)
            """,
            (asset_ref,),
        )
    assert await service.serve_asset(asset_ref=asset_ref) == (
        b"cover-owner",
        "image/webp",
    )

    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM experience_drafts WHERE draft_id = 'draft-cover'")
    cover_store = TimelineCoverPreferenceStore(db_path=db_path)
    await cover_store.set_preference(
        scale="month",
        period_start=1,
        period_end=2,
        mode="asset",
        asset_ref=asset_ref,
    )
    assert await service.serve_asset(asset_ref=asset_ref) == (
        b"cover-owner",
        "image/webp",
    )

    await cover_store.clear_preference(scale="month", period_start=1, period_end=2)
    assert await service.serve_asset(asset_ref=asset_ref) is None


@pytest.mark.asyncio
async def test_serve_asset_ignores_legacy_cover_with_unknown_source(
    unified_memory_for_tests,
    tmp_path,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"private upload", content_type="image/png")
    db_path = unified_memory_for_tests.memory_db_path
    cover_store = TimelineCoverPreferenceStore(db_path=db_path)
    await cover_store.initialize()
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO timeline_cover_preferences(
                scope_key, scale, period_start, period_end, mode,
                asset_ref, source, updated_at
            ) VALUES ('day:1:2', 'day', 1, 2, 'asset', ?, 'untrusted', 1)
            """,
            (asset_ref,),
        )

    service = TimelineService(
        unified_memory_for_tests,
        manual_entry_asset_store=asset_store,
    )

    assert await service.serve_asset(asset_ref=asset_ref) is None


def test_public_timeline_asset_route_streams_manual_entry_asset(
    tmp_path,
    monkeypatch,
):
    memory_db_path = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(memory_db_path)))
    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"cover-route-bytes", content_type="image/png")
    entry_store = ManualEntryStore(db_path=str(memory_db_path))
    asyncio.run(
        entry_store.create(
            ManualEntry(
                entry_id="entry-route-asset",
                created_at=time.time(),
                event_at=time.time(),
                body="route asset",
                attachments=[asset_ref],
            )
        )
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(timeline_router, _PUBLIC_ROUTE_METHODS["timeline"]),
        prefix="/api/timeline",
    )

    monkeypatch.setattr(
        "magi.api.routers.timeline.get_unified_memory",
        lambda: SimpleNamespace(memory_db_path=str(memory_db_path)),
    )
    monkeypatch.setattr(
        "magi.api.routers.timeline.get_manual_entry_asset_store",
        lambda: asset_store,
    )

    response = TestClient(app).get(f"/api/timeline/asset/{quote(asset_ref, safe='')}")

    assert response.status_code == 200
    assert response.content == b"cover-route-bytes"
    assert response.headers["content-type"] == "image/png"

    assert asyncio.run(
        entry_store.request_delete(
            "entry-route-asset",
            requested_at=time.time(),
        )
    )
    hidden = TestClient(app).get(f"/api/timeline/asset/{quote(asset_ref, safe='')}")
    assert hidden.status_code == 404
    assert asyncio.run(
        entry_store.finalize_delete(
            "entry-route-asset",
            deleted_at=time.time(),
        )
    )

    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"private-file")
    forged_ref = f"manual-entry-asset://{outside}"
    asyncio.run(
        entry_store.create(
            ManualEntry(
                entry_id="entry-forged-asset",
                created_at=time.time(),
                event_at=time.time(),
                body="forged asset",
                attachments=[forged_ref],
            )
        )
    )

    forged = TestClient(app).get(f"/api/timeline/asset/{quote(forged_ref, safe='')}")
    assert forged.status_code == 404
    assert outside.read_bytes() == b"private-file"
