"""Replay-barrier boundaries for explicit source-event replacement."""

from __future__ import annotations

import time

import aiosqlite
import pytest


async def _seed_assertion_and_projection(store, *, event_id: str) -> None:  # type: ignore[no-untyped-def]
    now = time.time() - 60
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "favorite_activity",
            "trait_value": event_id,
            "confidence_score": 0.8,
            "evidence_events": [event_id],
            "volatility_index": 0.1,
            "source_domain": "history_import",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )
    assert await store.enqueue_projection_job(
        event_id=event_id,
        source="history_import",
        event_type="history_import.document",
    )


async def _projection_status(store, *, event_id: str) -> str | None:  # type: ignore[no-untyped-def]
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            "SELECT status FROM l2_projection_jobs WHERE event_id = ?",
            (event_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return str(row[0]) if row is not None else None


async def _event_rule_count(store, *, event_id: str) -> int:  # type: ignore[no-untyped-def]
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT COUNT(*)
            FROM memory_forget_claim_rules AS rules
            JOIN memory_forget_evidence_events AS evidence
              ON evidence.rule_id = rules.rule_id
            WHERE rules.forget_kind = 'event' AND evidence.event_id = ?
            """,
            (event_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return int(row[0]) if row is not None else 0


@pytest.mark.asyncio
async def test_explicit_reimport_releases_stale_l2_replay_state(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    event_id = "evt-history-reimport"
    await _seed_assertion_and_projection(store, event_id=event_id)

    await store.forget_source_events(
        [event_id],
        reason="history_import_deleted",
        persist_barrier=False,
    )
    assert await _projection_status(store, event_id=event_id) == "completed"
    assert await _event_rule_count(store, event_id=event_id) > 0

    await store.forget_source_events(
        [event_id],
        reason="history_import_deleted",
        persist_barrier=False,
        retain_replay_barriers=False,
    )

    assert await _projection_status(store, event_id=event_id) is None
    assert await _event_rule_count(store, event_id=event_id) == 0


@pytest.mark.asyncio
async def test_ordinary_forget_keeps_l2_replay_state(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    event_id = "evt-ordinary-forget"
    await _seed_assertion_and_projection(store, event_id=event_id)

    await store.forget_source_events(
        [event_id],
        reason="user_delete_event",
        persist_barrier=True,
    )

    assert await _projection_status(store, event_id=event_id) == "completed"
    assert await _event_rule_count(store, event_id=event_id) > 0

    await store.forget_source_events(
        [event_id],
        reason="history_import_deleted",
        persist_barrier=False,
        retain_replay_barriers=False,
    )

    assert await _projection_status(store, event_id=event_id) == "completed"
    assert await _event_rule_count(store, event_id=event_id) > 0
