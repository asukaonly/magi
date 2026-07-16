from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from magi.memory.l2.corrections.models import CorrectionKind
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import (
    UserPortraitProjectionRepository,
)
from magi.user_profile.projection_builder import UserProfileProjectionBuilder
from magi.user_profile.projection_repository import UserProfileProjectionRepository


async def _seed_profile_assertion(store) -> str:  # type: ignore[no-untyped-def]
    observed_at = time.time() - 60
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "communication_profile",
            "trait_name": "communication.address.preferred",
            "trait_value": "Old name",
            "confidence_score": 0.8,
            "evidence_events": ["event-old"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": observed_at,
            "last_validated_at": observed_at,
            "temporal_scope": "persistent",
        }
    )


async def _seed_profile_views(store) -> None:  # type: ignore[no-untyped-def]
    await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    profile = await UserProfileProjectionBuilder(store).build("u1")
    await UserProfileProjectionRepository(store.db_path).upsert(profile)
    portrait = await UserPortraitProjectionBuilder(
        store,
        profile_projection=profile,
    ).build("u1")
    await UserPortraitProjectionRepository(store.db_path).upsert(portrait)


async def _seed_relationship(store) -> str:  # type: ignore[no-untyped-def]
    return await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["event-old-city"],
        confidence=0.8,
        observed_at=time.time() - 60,
        source_type="conversation",
        extraction_method="explicit",
    )


async def _transition_marker(db_path: str, correction_id: str) -> float | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT transition_applied_at FROM memory_corrections WHERE correction_id = ?",
            (correction_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return float(row[0]) if row[0] is not None else None


@pytest.mark.asyncio
async def test_future_assertion_refreshes_views_only_when_transition_is_due(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    await _seed_profile_views(store)
    profile_repository = UserProfileProjectionRepository(store.db_path)
    portrait_repository = UserPortraitProjectionRepository(store.db_path)
    notify = AsyncMock()
    wakeup = AsyncMock()
    store.set_assertion_change_callback(notify)
    store.set_memory_correction_job_wakeup(wakeup)
    effective_at = time.time() + 600

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-assertion-transition",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=effective_at,
        audit_event_id="audit-future-assertion",
    )

    assert result is not None
    correction_id = result["correction"]["correction_id"]
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'completed'
            WHERE correction_id = ? AND job_kind = 'l1_audit'
            """,
            (correction_id,),
        )
        await db.commit()
    assert result["subject_revision"] is None
    assert await store.current_subject_revision("user:u1") == 0
    assert await store.get_memory_correction_derivation_state(correction_id) == "pending"
    assert await store.next_memory_correction_job_wakeup_at() == pytest.approx(effective_at)
    assert (await profile_repository.get("u1")).display_name == "Old name"
    assert await portrait_repository.get("u1") is not None
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user") is not None
    assert await _transition_marker(store.db_path, correction_id) is None
    notify.assert_not_awaited()
    wakeup.assert_awaited_once_with()

    with patch("time.time", return_value=effective_at + 1):
        stats = await store.process_memory_correction_jobs(limit=10)
        assert stats == {
            "completed": 3,
            "failed": 0,
            "superseded": 0,
            "activated": 1,
        }
        profile = await profile_repository.get("u1")
        portrait = await portrait_repository.get("u1")
        snapshot = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
        assert profile is not None and profile.display_name == "New name"
        assert portrait is not None and "Old name" not in str(portrait.model_dump())
        assert snapshot is not None and "Old name" not in str(snapshot)

    assert await store.current_subject_revision("user:u1") == 1
    assert await store.get_memory_correction_derivation_state(correction_id) == "completed"
    assert await _transition_marker(store.db_path, correction_id) == pytest.approx(
        effective_at + 1
    )


@pytest.mark.asyncio
async def test_future_relationship_transition_is_idempotent(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    triple_id = await _seed_relationship(store)
    original_snapshot = await store.refresh_entity_snapshot(
        entity_id="user:u1",
        entity_type="user",
    )
    assert original_snapshot is not None and "place:hangzhou" in str(original_snapshot)
    effective_at = time.time() + 600

    result = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="future-relationship-transition",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=effective_at,
    )

    assert result is not None
    correction_id = result["correction"]["correction_id"]
    assert result["subject_revision"] is None
    assert await store.current_subject_revision("user:u1") == 0
    assert await store.current_subject_revision("place:hangzhou") == 0
    assert await store.current_subject_revision("place:shanghai") == 0
    assert await store.get_memory_correction_derivation_state(correction_id) == "pending"
    before_due = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
    assert before_due is not None and "place:hangzhou" in str(before_due)

    with patch("time.time", return_value=effective_at + 1):
        first = await store.process_memory_correction_jobs(limit=10)
        assert first["activated"] == 1
        assert first["failed"] == 0
        transitioned = await store.get_tom_snapshot(
            entity_id="user:u1",
            entity_type="user",
        )
        assert transitioned is not None
        assert "place:shanghai" in str(transitioned)
        assert "place:hangzhou" not in str(transitioned)

        second = await store.process_memory_correction_jobs(limit=10)
        assert second == {
            "completed": 0,
            "failed": 0,
            "superseded": 0,
            "activated": 0,
        }

    assert await store.current_subject_revision("user:u1") == 1
    assert await store.current_subject_revision("place:hangzhou") == 1
    assert await store.current_subject_revision("place:shanghai") == 1
    assert await store.get_memory_correction_derivation_state(correction_id) == "completed"


@pytest.mark.asyncio
async def test_reverted_future_transition_never_activates(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    effective_at = time.time() + 600
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-transition-to-revert",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=effective_at,
    )
    assert applied is not None
    correction_id = applied["correction"]["correction_id"]

    reverted = await store.revert_assertion_correction(
        correction_id=correction_id,
        request_id="revert-future-transition",
        actor_id="user:u1",
    )

    assert reverted is not None
    assert reverted["subject_revision"] is None
    assert await store.current_subject_revision("user:u1") == 0
    with patch("time.time", return_value=effective_at + 1):
        stats = await store.process_memory_correction_jobs(limit=10)
    assert stats["activated"] == 0
    assert await store.current_subject_revision("user:u1") == 0
