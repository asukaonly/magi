from __future__ import annotations

import time

import aiosqlite

from magi.context.user_profile_service import UserProfileService
from magi.memory.l2.corrections.derivations import CorrectionDerivationRunner
from magi.memory.l2.corrections.models import (
    ApplyAssertionCorrectionCommand,
    CorrectionKind,
)
from magi.memory.l2.corrections.service import MemoryCorrectionService
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import (
    UserPortraitProjectionRepository,
)
from magi.user_profile.projection_builder import UserProfileProjectionBuilder
from magi.user_profile.projection_repository import UserProfileProjectionRepository


class _UnifiedMemory:
    def __init__(self, l2_store):  # type: ignore[no-untyped-def]
        self.l2 = l2_store
        self.l2_entity_catalog = None


async def _seed_profile_assertion(
    store,  # type: ignore[no-untyped-def]
    *,
    trait_family: str = "communication_profile",
    trait_name: str = "communication.address.preferred",
) -> str:
    now = time.time() - 60
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": trait_family,
            "trait_name": trait_name,
            "trait_value": "Old name",
            "confidence_score": 0.8,
            "evidence_events": ["event-old"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )


async def _seed_derived_views(store) -> None:  # type: ignore[no-untyped-def]
    await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    profile = await UserProfileProjectionBuilder(store).build("u1")
    await UserProfileProjectionRepository(store.db_path).upsert(profile)
    portrait = await UserPortraitProjectionBuilder(
        store,
        profile_projection=profile,
    ).build("u1")
    await UserPortraitProjectionRepository(store.db_path).upsert(portrait)


async def test_stale_views_fail_closed_then_rebuild_after_retry(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    await _seed_derived_views(store)
    profile_repository = UserProfileProjectionRepository(store.db_path)
    portrait_repository = UserPortraitProjectionRepository(store.db_path)
    assert (await profile_repository.get("u1")).display_name == "Old name"
    assert await portrait_repository.get("u1") is not None
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")

    result = await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="derive-retry",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="New name",
        )
    )

    assert result is not None
    assert await profile_repository.get("u1") is None
    assert await portrait_repository.get("u1") is None
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user") is None

    async def fail_snapshot(_job) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("temporary rebuild failure")

    failed = await CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
        handlers={"snapshot": fail_snapshot},
    ).run_pending(limit=1)
    assert failed == {"completed": 0, "failed": 1, "superseded": 0}
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user") is None

    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE memory_derivation_jobs SET next_retry_at = 0 WHERE status = 'failed'"
        )
        await db.commit()

    rebuilt = await CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
    ).run_pending(limit=10, recover_interrupted=True)

    assert rebuilt["failed"] == 0
    profile = await profile_repository.get("u1")
    portrait = await portrait_repository.get("u1")
    snapshot = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
    assert profile is not None and profile.display_name == "New name"
    assert portrait is not None and "Old name" not in str(portrait.model_dump())
    assert snapshot is not None and "Old name" not in str(snapshot)
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("SELECT DISTINCT status FROM memory_derivation_jobs") as cursor:
            statuses = {str(row[0]) for row in await cursor.fetchall()}
        async with db.execute(
            "SELECT COUNT(*) FROM memory_derivation_dependencies WHERE source_revision = 1"
        ) as cursor:
            dependency_count = int((await cursor.fetchone())[0])
    assert statuses == {"completed"}
    assert dependency_count > 0


async def test_chat_profile_cache_observes_correction_signal(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(
        store,
        trait_family="preference_profile",
        trait_name="address.preferred",
    )
    service = UserProfileService(
        unified_memory=_UnifiedMemory(store),
        cache_ttl=3600,
    )
    assert await service.get_preference_summary("u1") == {"address.preferred": "Old name"}

    await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="cache-signal",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="New name",
        )
    )

    assert await service.get_preference_summary("u1") == {"address.preferred": "New name"}
