from __future__ import annotations

import asyncio
import time

import aiosqlite
import pytest

from magi.context.user_profile_service import UserProfileService
from magi.memory.derivation_revision import DerivationRevisionChangedError
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
            "UPDATE memory_derivation_jobs SET next_retry_at = 0 WHERE next_retry_at IS NOT NULL"
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


async def test_portrait_read_failure_remains_retryable(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    correction = await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="portrait-read-retry",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="New name",
        )
    )
    assert correction is not None

    prerequisites = await CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
    ).run_pending(limit=2)
    assert prerequisites == {"completed": 2, "failed": 0, "superseded": 0}

    original_list_assertions = store.list_current_assertions

    async def _fail_assertion_read(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("temporary portrait source failure")

    monkeypatch.setattr(store, "list_current_assertions", _fail_assertion_read)
    failed = await CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
    ).run_pending(limit=1)
    assert failed == {"completed": 0, "failed": 1, "superseded": 0}

    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT status, attempt_count, next_retry_at, last_error
            FROM memory_derivation_jobs
            WHERE correction_id = ? AND job_kind = 'portrait'
            """,
            (correction.correction.correction_id,),
        ) as cursor:
            job = await cursor.fetchone()
    assert job is not None
    assert job[0] == "pending"
    assert job[1] == 1
    assert job[2] is not None
    assert "temporary portrait source failure" in str(job[3])
    assert await UserPortraitProjectionRepository(store.db_path).get("u1") is None

    monkeypatch.setattr(store, "list_current_assertions", original_list_assertions)
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET next_retry_at = 0
            WHERE correction_id = ? AND job_kind = 'portrait'
            """,
            (correction.correction.correction_id,),
        )
        await db.commit()
    retried = await CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
    ).run_pending(limit=1)
    assert retried == {"completed": 1, "failed": 0, "superseded": 0}
    portrait = await UserPortraitProjectionRepository(store.db_path).get("u1")
    assert portrait is not None
    assert "New name" in str(portrait.model_dump())


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


async def test_snapshot_refresh_discards_sources_superseded_during_build(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    original_list_assertions = store.list_current_assertions
    sources_read = asyncio.Event()
    continue_build = asyncio.Event()

    async def paused_list_assertions(**kwargs):  # type: ignore[no-untyped-def]
        assertions = await original_list_assertions(**kwargs)
        if kwargs.get("entity_id") == "user:u1":
            sources_read.set()
            await continue_build.wait()
        return assertions

    monkeypatch.setattr(store, "list_current_assertions", paused_list_assertions)
    refresh = asyncio.create_task(
        store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    )
    await asyncio.wait_for(sources_read.wait(), timeout=2)

    await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="snapshot-concurrent-revision",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="New name",
        )
    )
    continue_build.set()

    with pytest.raises(DerivationRevisionChangedError):
        await refresh
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user") is None
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM tom_snapshots") as cursor:
            assert int((await cursor.fetchone())[0]) == 0

    monkeypatch.setattr(store, "list_current_assertions", original_list_assertions)
    rebuilt = await store.refresh_entity_snapshot(
        entity_id="user:u1",
        entity_type="user",
    )
    assert rebuilt is not None
    assert rebuilt["source_revision"] == 1
    assert "New name" in str(rebuilt)
    assert "Old name" not in str(rebuilt)


async def test_derivation_runner_marks_mid_build_revision_change_superseded(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    first = await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="runner-concurrent-revision-one",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Intermediate name",
        )
    )
    assert first is not None and first.current_assertion_id is not None

    original_list_assertions = store.list_current_assertions
    sources_read = asyncio.Event()
    continue_build = asyncio.Event()

    async def paused_list_assertions(**kwargs):  # type: ignore[no-untyped-def]
        assertions = await original_list_assertions(**kwargs)
        if kwargs.get("entity_id") == "user:u1":
            sources_read.set()
            await continue_build.wait()
        return assertions

    monkeypatch.setattr(store, "list_current_assertions", paused_list_assertions)
    running = asyncio.create_task(
        CorrectionDerivationRunner(db_path=store.db_path, l2_store=store).run_pending(
            limit=1
        )
    )
    await asyncio.wait_for(sources_read.wait(), timeout=2)

    await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=first.current_assertion_id,
            request_id="runner-concurrent-revision-two",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Current name",
        )
    )
    continue_build.set()

    assert await running == {"completed": 0, "failed": 0, "superseded": 1}
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user") is None
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT status, last_error
            FROM memory_derivation_jobs
            WHERE correction_id = ? AND job_kind = 'snapshot'
            """,
            (first.correction.correction_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert "Superseded by revision 2" in str(row[1])


async def test_empty_snapshot_job_cannot_delete_newer_snapshot(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    correction = await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="empty-snapshot-delete-race",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
        )
    )
    assert correction is not None and correction.subject_revision == 1

    original_refresh = store.refresh_entity_snapshot
    empty_result_ready = asyncio.Event()
    continue_delete = asyncio.Event()

    async def paused_empty_refresh(**kwargs):  # type: ignore[no-untyped-def]
        snapshot = await original_refresh(**kwargs)
        assert snapshot is None
        empty_result_ready.set()
        await continue_delete.wait()
        return None

    monkeypatch.setattr(store, "refresh_entity_snapshot", paused_empty_refresh)
    old_job = asyncio.create_task(
        CorrectionDerivationRunner(db_path=store.db_path, l2_store=store).run_pending(
            limit=1
        )
    )
    await asyncio.wait_for(empty_result_ready.wait(), timeout=2)

    reverted = await MemoryCorrectionService(store.db_path).revert_assertion_correction(
        correction_id=correction.correction.correction_id,
        request_id="restore-for-newer-snapshot",
        actor_id="user:u1",
    )
    assert reverted is not None and reverted.subject_revision == 2
    newer_snapshot = await original_refresh(entity_id="user:u1", entity_type="user")
    assert newer_snapshot is not None and newer_snapshot["source_revision"] == 2

    continue_delete.set()
    assert await old_job == {"completed": 0, "failed": 0, "superseded": 1}
    stored = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
    assert stored is not None
    assert stored["snapshot_id"] == newer_snapshot["snapshot_id"]
    assert stored["source_revision"] == 2


class _PausedProjectionSource:
    def __init__(self) -> None:
        self.revision = 0
        self.sources_read = asyncio.Event()
        self.continue_build = asyncio.Event()

    async def current_subject_revision(self, _subject_key: str) -> int:
        return self.revision

    async def list_current_assertions(self, **_kwargs):  # type: ignore[no-untyped-def]
        assertions = [
            {
                "assertion_id": "assertion-old-name",
                "trait_family": "communication_profile",
                "trait_name": "communication.address.preferred",
                "trait_value": "Old name",
                "source_domain": "user_authored",
                "validation_state": "stable",
                "confidence_score": 1.0,
                "evidence_events": ["event-old"],
                "last_validated_at": time.time(),
                "temporal_scope": "persistent",
            }
        ]
        self.sources_read.set()
        await self.continue_build.wait()
        return assertions


@pytest.mark.parametrize("projection_kind", ["profile", "portrait"])
async def test_projection_builders_discard_sources_superseded_during_build(
    projection_kind: str,
) -> None:
    source = _PausedProjectionSource()
    if projection_kind == "profile":
        build = UserProfileProjectionBuilder(source).build("u1")
    else:
        build = UserPortraitProjectionBuilder(source).build("u1")
    projection_task = asyncio.create_task(build)
    await asyncio.wait_for(source.sources_read.wait(), timeout=2)
    source.revision = 1
    source.continue_build.set()

    with pytest.raises(DerivationRevisionChangedError):
        await projection_task


async def test_projection_repositories_reject_superseded_builds(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    profile = await UserProfileProjectionBuilder(store).build("u1")
    portrait = await UserPortraitProjectionBuilder(
        store,
        profile_projection=profile,
    ).build("u1")
    assert profile.source_revision == portrait.source_revision == 0

    await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="projection-before-save-revision",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="New name",
        )
    )

    with pytest.raises(DerivationRevisionChangedError):
        await UserProfileProjectionRepository(store.db_path).upsert(profile)
    with pytest.raises(DerivationRevisionChangedError):
        await UserPortraitProjectionRepository(store.db_path).upsert(portrait)

    assert await UserProfileProjectionRepository(store.db_path).get("u1") is None
    assert await UserPortraitProjectionRepository(store.db_path).get("u1") is None


async def test_portrait_builder_rejects_superseded_profile_input() -> None:
    class _CurrentProjectionSource:
        async def current_subject_revision(self, _subject_key: str) -> int:
            return 1

        async def list_current_assertions(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    stale_profile = UserProfileProjectionBuilder(None)
    profile = await stale_profile.build("u1")
    assert profile.source_revision == 0

    with pytest.raises(DerivationRevisionChangedError):
        await UserPortraitProjectionBuilder(
            _CurrentProjectionSource(),
            profile_projection=profile,
        ).build("u1")
