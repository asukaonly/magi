"""ManualEntryStore CRUD + soft-delete coverage."""

from __future__ import annotations

import time

import pytest

from magi.memory.manual_entries import ManualEntry, ManualEntryStore


def _entry(**overrides) -> ManualEntry:
    """Build a default entry; tests override only the fields they care about."""
    now = time.time()
    defaults = dict(
        entry_id="",
        created_at=now,
        event_at=now,
        kind="quick",
        body="hello world",
        mood=None,
        location_label=None,
        attachments=[],
    )
    defaults.update(overrides)
    return ManualEntry(**defaults)


@pytest.mark.asyncio
async def test_create_and_get_roundtrip(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="一念之间"))
    assert entry_id.startswith("me-")

    fetched = await store.get(entry_id)
    assert fetched is not None
    assert fetched.body == "一念之间"
    assert fetched.deleted_at is None
    assert fetched.kind == "quick"


@pytest.mark.asyncio
async def test_create_with_attachments_and_mood(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    refs = [
        "manual-entry-asset://aaa.png",
        "manual-entry-asset://bbb.jpg",
    ]
    entry_id = await store.create(_entry(
        body="带图的一条",
        mood="warm",
        attachments=refs,
        location_label="杭州",
        location_lat=30.27,
        location_lng=120.15,
    ))
    fetched = await store.get(entry_id)
    assert fetched.mood == "warm"
    assert fetched.attachments == refs
    assert fetched.location_label == "杭州"
    assert fetched.location_lat == pytest.approx(30.27)


@pytest.mark.asyncio
async def test_list_window_filters_by_event_at_and_excludes_deleted(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    id_a = await store.create(_entry(event_at=100.0, body="A"))
    id_b = await store.create(_entry(event_at=200.0, body="B"))
    id_c = await store.create(_entry(event_at=350.0, body="C"))
    await store.soft_delete(id_b)

    in_window = await store.list_window(time_start=50.0, time_end=300.0)
    bodies = [e.body for e in in_window]
    assert "A" in bodies
    assert "B" not in bodies  # soft-deleted
    assert "C" not in bodies  # out of window

    with_deleted = await store.list_window(
        time_start=50.0, time_end=300.0, include_deleted=True,
    )
    assert {e.body for e in with_deleted} == {"A", "B"}


@pytest.mark.asyncio
async def test_update_only_touches_provided_fields(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="原文", mood="cool"))

    ok = await store.update(entry_id, body="改动后的正文")
    assert ok
    fetched = await store.get(entry_id)
    assert fetched.body == "改动后的正文"
    # mood untouched
    assert fetched.mood == "cool"


@pytest.mark.asyncio
async def test_update_with_no_fields_is_noop(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    ok = await store.update(entry_id)
    assert ok is False


@pytest.mark.asyncio
async def test_update_mood_empty_string_clears_to_null(manual_entry_db: str):
    """Allowing mood='' to clear lets the UI distinguish 'not changed' from
    'explicitly clear it' (since None means 'don't touch')."""
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(mood="warm"))
    await store.update(entry_id, mood="")
    fetched = await store.get(entry_id)
    assert fetched.mood is None


@pytest.mark.asyncio
async def test_soft_delete_idempotent(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    first = await store.soft_delete(entry_id)
    second = await store.soft_delete(entry_id)
    assert first is True
    # Second time the WHERE clause excludes already-deleted rows → no row changed
    assert second is False


@pytest.mark.asyncio
async def test_link_l1_event(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    await store.link_l1_event(entry_id, "01HXYZ123")
    fetched = await store.get(entry_id)
    assert fetched.l1_event_id == "01HXYZ123"
