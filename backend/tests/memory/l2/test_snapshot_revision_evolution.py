"""Snapshot evolution must compare against the last materialized revision."""

from __future__ import annotations

import time

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_snapshot_refresh_keeps_older_revision_as_evolution_baseline(
    l2_store_with_schema,
) -> None:
    await l2_store_with_schema.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="place:shanghai",
        object_type="place",
        fact_kind="stable_preference",
        evidence_event_ids=["evt-like"],
        confidence=0.9,
        observed_at=1_710_000_000.0,
        source_type="chat",
    )
    first = await l2_store_with_schema.refresh_entity_snapshot(
        entity_id="user:u1",
        entity_type="user",
    )
    assert first is not None
    assert first["preferences"]["place:shanghai"]["value"] == "like"

    async with aiosqlite.connect(l2_store_with_schema.db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
            VALUES ('user:u1', 1, ?)
            ON CONFLICT(subject_key) DO UPDATE SET
                revision = memory_subject_revisions.revision + 1,
                updated_at = excluded.updated_at
            """,
            (time.time(),),
        )
        await db.commit()

    await l2_store_with_schema.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="place:shanghai",
        object_type="place",
        fact_kind="stable_preference",
        evidence_event_ids=["evt-dislike"],
        confidence=0.94,
        observed_at=1_720_000_000.0,
        source_type="chat",
    )
    second = await l2_store_with_schema.refresh_entity_snapshot(
        entity_id="user:u1",
        entity_type="user",
    )

    assert second is not None
    assert second["source_revision"] > first["source_revision"]
    assert second["preferences"]["place:shanghai"]["value"] == "dislike"
    assert len(second["preferences_history"]) == 1
    history = second["preferences_history"][0]
    assert history["field"] == "place:shanghai"
    assert history["from"] == first["preferences"]["place:shanghai"]
    assert history["to"] == second["preferences"]["place:shanghai"]
    assert len(history["supporting_record_ids"]) == 1
    assert len(history["superseded_record_ids"]) == 1
