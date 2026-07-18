"""ManualEntryStore CRUD + soft-delete coverage."""

from __future__ import annotations

import time

import pytest

from magi.core.sqlite import sqlite_connection_async
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
    entry_id = await store.create(
        _entry(
            body="带图的一条",
            mood="warm",
            attachments=refs,
            location_label="杭州",
            location_lat=30.27,
            location_lng=120.15,
        )
    )
    fetched = await store.get(entry_id)
    assert fetched.mood == "warm"
    assert fetched.attachments == refs
    assert fetched.location_label == "杭州"
    assert fetched.location_lat == pytest.approx(30.27)


@pytest.mark.asyncio
async def test_list_window_filters_by_event_at_and_excludes_deleted(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    await store.create(_entry(event_at=100.0, body="A"))
    id_b = await store.create(_entry(event_at=200.0, body="B"))
    await store.create(_entry(event_at=350.0, body="C"))
    assert await store.request_delete(id_b, requested_at=1.0)
    assert await store.finalize_delete(id_b, deleted_at=2.0)

    in_window = await store.list_window(time_start=50.0, time_end=300.0)
    bodies = [e.body for e in in_window]
    assert "A" in bodies
    assert "B" not in bodies  # soft-deleted
    assert "C" not in bodies  # out of window

    with_deleted = await store.list_window(
        time_start=50.0,
        time_end=300.0,
        include_deleted=True,
    )
    assert {e.body for e in with_deleted} == {"A", "B"}


@pytest.mark.asyncio
async def test_list_window_hides_delete_gated_row_before_finalization(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(event_at=100.0, body="private"))
    assert await store.request_delete(entry_id, requested_at=1.0)

    visible = await store.list_window(time_start=0.0, time_end=200.0)

    assert visible == []


@pytest.mark.asyncio
async def test_recovery_candidates_are_stably_paginated(manual_entry_db: str) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    for entry_id in ("me-30", "me-10", "me-20"):
        await store.create(_entry(entry_id=entry_id, body=entry_id))
    linked_id = await store.create(
        _entry(entry_id="me-40", body="linked", l1_event_id="event-linked")
    )

    first = await store.list_recovery_candidates(limit=2)
    second = await store.list_recovery_candidates(
        after_entry_id=first[-1].entry_id,
        limit=2,
    )

    assert [entry.entry_id for entry in first] == ["me-10", "me-20"]
    assert [entry.entry_id for entry in second] == ["me-30"]
    assert linked_id not in {entry.entry_id for entry in [*first, *second]}


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
async def test_delete_gate_and_finalize_are_idempotent(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    assert await store.request_delete(entry_id, requested_at=1.0) is True
    assert await store.request_delete(entry_id, requested_at=2.0) is True
    gated = await store.get(entry_id)
    assert gated is not None
    assert gated.delete_requested_at == 1.0

    assert await store.finalize_delete(entry_id, deleted_at=3.0) is True
    assert await store.finalize_delete(entry_id, deleted_at=4.0) is False
    deleted = await store.get(entry_id)
    assert deleted is not None
    assert deleted.deleted_at == 3.0
    assert deleted.delete_requested_at is None


@pytest.mark.asyncio
async def test_projection_reservation_and_completion(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    reserved = await store.reserve_l1_projection(
        entry_id,
        "01HXYZ123",
        expected_previous_event_id=None,
    )
    assert reserved is True
    pending = await store.get(entry_id)
    assert pending is not None
    assert pending.l1_event_id is None
    assert pending.pending_l1_event_id == "01HXYZ123"
    assert pending.pending_l1_predecessor_event_id is None

    linked = await store.complete_l1_projection(
        entry_id,
        "01HXYZ123",
        expected_previous_event_id=None,
    )
    assert linked is True
    fetched = await store.get(entry_id)
    assert fetched is not None
    assert fetched.l1_event_id == "01HXYZ123"
    assert fetched.pending_l1_event_id is None


@pytest.mark.asyncio
async def test_replacement_snapshot_and_projection_intent_are_atomic_and_hidden(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(
        _entry(
            entry_id="me-replacement",
            body="before",
            l1_event_id="event-old",
        )
    )
    replacement = await store.get(entry_id)
    assert replacement is not None
    replacement.body = "after"
    replacement.body_doc = {}

    assert await store.replace_and_reserve_l1_projection(
        replacement,
        "event-new",
        expected_previous_event_id="event-old",
    )

    pending = await store.get(entry_id)
    assert pending is not None
    assert pending.body == "after"
    assert pending.body_doc == {}
    assert pending.l1_event_id == "event-old"
    assert pending.pending_l1_event_id == "event-new"
    assert pending.pending_l1_predecessor_event_id == "event-old"
    assert await store.list_window(time_start=0.0, time_end=time.time() + 1) == []

    assert await store.complete_l1_projection(
        entry_id,
        "event-new",
        expected_previous_event_id="event-old",
    )
    visible = await store.list_window(time_start=0.0, time_end=time.time() + 1)
    assert [entry.body for entry in visible] == ["after"]


@pytest.mark.asyncio
async def test_mutations_and_projection_reject_wrong_or_delete_gated_state(
    manual_entry_db: str,
):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="before", l1_event_id="event-old"))

    assert (
        await store.update(
            entry_id,
            body="wrong predecessor",
            expected_l1_event_id="event-other",
        )
        is False
    )
    assert (
        await store.reserve_l1_projection(
            entry_id,
            "event-new",
            expected_previous_event_id="event-other",
        )
        is False
    )

    assert await store.request_delete(entry_id, requested_at=1.0)
    assert (
        await store.update(
            entry_id,
            body="after delete",
            expected_l1_event_id="event-old",
        )
        is False
    )
    assert (
        await store.reserve_l1_projection(
            entry_id,
            "event-new",
            expected_previous_event_id="event-old",
        )
        is False
    )

    fetched = await store.get(entry_id)
    assert fetched is not None
    assert fetched.body == "before"
    assert fetched.l1_event_id == "event-old"


@pytest.mark.asyncio
async def test_pending_projection_blocks_source_mutation_until_completed(
    manual_entry_db: str,
):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="before", l1_event_id="event-old"))

    assert await store.reserve_l1_projection(
        entry_id,
        "event-new",
        expected_previous_event_id="event-old",
    )
    assert (
        await store.update(
            entry_id,
            body="must not overtake pending projection",
            expected_l1_event_id="event-old",
        )
        is False
    )
    assert await store.set_weather(entry_id, {"code": 1}) is False

    assert await store.complete_l1_projection(
        entry_id,
        "event-new",
        expected_previous_event_id="event-old",
    )
    assert (
        await store.update(
            entry_id,
            body="after completion",
            expected_l1_event_id="event-new",
        )
        is True
    )


@pytest.mark.asyncio
async def test_delete_gate_overtakes_pending_projection_without_losing_identity(
    manual_entry_db: str,
):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="before", l1_event_id="event-old"))
    assert await store.reserve_l1_projection(
        entry_id,
        "event-new",
        expected_previous_event_id="event-old",
    )

    assert await store.request_delete(entry_id, requested_at=2.0)
    assert (
        await store.complete_l1_projection(
            entry_id,
            "event-new",
            expected_previous_event_id="event-old",
        )
        is False
    )
    gated = await store.get(entry_id)
    assert gated is not None
    assert gated.pending_l1_event_id == "event-new"
    assert gated.delete_requested_at == 2.0


@pytest.mark.asyncio
async def test_update_clears_weather_atomically_with_event_time(manual_entry_db: str):
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(
        _entry(
            event_at=100.0,
            weather={"code": 1, "temp_c": 20.0},
            l1_event_id="event-old",
        )
    )

    changed = await store.update(
        entry_id,
        event_at=1000.0,
        clear_weather=True,
        expected_l1_event_id="event-old",
    )

    assert changed is True
    fetched = await store.get(entry_id)
    assert fetched is not None
    assert fetched.event_at == 1000.0
    assert fetched.weather is None


@pytest.mark.asyncio
async def test_weather_roundtrip(manual_entry_db: str):
    """set_weather persists a JSON blob; re-read produces an equal dict."""
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    payload = {"code": 2, "temp_c": 22.5, "fetched_at": 1716210000.0}

    changed = await store.set_weather(entry_id, payload)
    assert changed is True

    fetched = await store.get(entry_id)
    assert fetched.weather == payload


@pytest.mark.asyncio
async def test_weather_clear_with_none(manual_entry_db: str):
    """set_weather(None) clears a previously-attached snapshot."""
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x"))
    await store.set_weather(entry_id, {"code": 0, "temp_c": 20.0, "fetched_at": 1.0})
    await store.set_weather(entry_id, None)

    fetched = await store.get(entry_id)
    assert fetched.weather is None


@pytest.mark.asyncio
async def test_create_with_weather_field(manual_entry_db: str):
    """Weather supplied at creation time persists via the INSERT path."""
    store = ManualEntryStore(db_path=manual_entry_db)
    payload = {"code": 61, "temp_c": 15.0, "fetched_at": 100.0}
    entry_id = await store.create(_entry(body="rainy", weather=payload))
    fetched = await store.get(entry_id)
    assert fetched.weather == payload


@pytest.mark.asyncio
async def test_body_doc_roundtrip_via_create(manual_entry_db: str):
    """A ProseMirror JSON doc supplied at creation survives a get()."""
    store = ManualEntryStore(db_path=manual_entry_db)
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "今天天气"},
                    {"type": "text", "marks": [{"type": "bold"}], "text": "真好"},
                ],
            },
        ],
    }
    entry_id = await store.create(_entry(body="今天天气真好", body_doc=doc))
    fetched = await store.get(entry_id)
    assert fetched.body == "今天天气真好"
    assert fetched.body_doc == doc


@pytest.mark.asyncio
async def test_body_doc_update_set_and_clear(manual_entry_db: str):
    """body_doc uses the two-arg shape: body_doc=dict sets, clear_body_doc=True clears."""
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="hi"))
    doc = {"type": "doc", "content": [{"type": "paragraph"}]}

    await store.update(entry_id, body_doc=doc)
    assert (await store.get(entry_id)).body_doc == doc

    # body_doc=None alone doesn't touch — body stays
    await store.update(entry_id, body="x")
    assert (await store.get(entry_id)).body_doc == doc

    # clear_body_doc=True wipes it
    await store.update(entry_id, clear_body_doc=True)
    assert (await store.get(entry_id)).body_doc is None


@pytest.mark.asyncio
async def test_update_location_label_set_and_clear(manual_entry_db: str):
    """location_label follows the empty-string-clears convention:
    ``None`` = don't touch, ``""`` = clear to NULL, other strings set."""
    store = ManualEntryStore(db_path=manual_entry_db)
    entry_id = await store.create(_entry(body="x", location_label="杭州"))

    # Setting to a new value writes it.
    await store.update(entry_id, location_label="北京")
    assert (await store.get(entry_id)).location_label == "北京"

    # Empty string clears to NULL.
    await store.update(entry_id, location_label="")
    assert (await store.get(entry_id)).location_label is None

    # Untouched on a body-only update.
    await store.update(entry_id, location_label="苏州")
    await store.update(entry_id, body="边改")
    assert (await store.get(entry_id)).location_label == "苏州"


@pytest.mark.asyncio
async def test_source_forget_batches_twenty_thousand_entries(
    manual_entry_db: str,
) -> None:
    store = ManualEntryStore(db_path=manual_entry_db)
    rows = [
        (
            f"me-forget-scale-{index:05d}",
            100.0,
            100.0,
            "quick",
            "private",
            "[]",
            f"event-forget-scale-{index:05d}",
        )
        for index in range(20_000)
    ]
    async with sqlite_connection_async(manual_entry_db) as db:
        await db.executemany(
            """
            INSERT INTO manual_entries(
                entry_id, created_at, event_at, kind, body,
                attachments_json, l1_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await db.commit()

    finalized = 0
    for offset in range(0, len(rows), 500):
        chunk = rows[offset : offset + 500]
        selected = {
            entry_id: (event_id,)
            for entry_id, _, _, _, _, _, event_id in chunk
        }
        gate = await store.gate_source_forget_entries(
            selected,
            requested_at=200.0,
        )
        assert len(gate.gated_entries) == len(chunk)
        assert gate.obsolete_event_ids == ()
        finalized += await store.finalize_source_forget_entries(
            {
                identity.entry_id: (
                    str(identity.l1_event_id),
                )
                for identity in gate.gated_entries
            },
            deleted_at=300.0,
        )

    assert finalized == 20_000
    async with sqlite_connection_async(manual_entry_db) as db:
        async with db.execute(
            """
            SELECT COUNT(*)
            FROM manual_entries
            WHERE deleted_at = 300.0
            """
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert int(row[0]) == 20_000
