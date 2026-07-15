from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite
from dependency_injector import providers

from magi.config.memory_models import MemoryL2Settings
from magi.core.container import get_container
from magi.memory.l2.corrections.derivations import CorrectionDerivationRunner
from magi.memory.l2.corrections.models import (
    ApplyAssertionCorrectionCommand,
    CorrectionKind,
)
from magi.memory.l2.corrections.repository import MemoryCorrectionRepository
from magi.memory.l2.corrections.service import MemoryCorrectionService
from magi.memory.l2.derive_schedule import L2DeriveScheduleContrib
from magi.scheduler.service import SchedulerService


async def _seed_assertion(
    store,  # type: ignore[no-untyped-def]
    *,
    entity_id: str = "user:u1",
    trait_name: str = "location.home",
) -> str:
    now = time.time() - 60
    return await store.upsert_assertion_candidate(
        {
            "entity_id": entity_id,
            "entity_type": "user",
            "trait_family": "identity_profile",
            "trait_name": trait_name,
            "trait_value": "Hangzhou",
            "confidence_score": 0.8,
            "evidence_events": [f"event:{entity_id}:{trait_name}"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )


async def _enqueue_correction(
    store,  # type: ignore[no-untyped-def]
    *,
    request_id: str,
    entity_id: str = "user:u1",
    trait_name: str = "location.home",
) -> str:
    assertion_id = await _seed_assertion(
        store,
        entity_id=entity_id,
        trait_name=trait_name,
    )
    result = await MemoryCorrectionService(store.db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id=request_id,
            actor_id=entity_id,
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
        )
    )
    assert result is not None
    return result.correction.correction_id


async def _isolate_snapshot_job(db_path: str, correction_id: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'completed'
            WHERE correction_id = ? AND job_kind != 'snapshot'
            """,
            (correction_id,),
        )
        await db.commit()


async def _snapshot_job(db_path: str, correction_id: str) -> tuple:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT status, attempt_count, next_retry_at, last_error
            FROM memory_derivation_jobs
            WHERE correction_id = ? AND job_kind = 'snapshot'
            """,
            (correction_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return row


async def test_derivation_job_stops_after_maximum_attempts(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    correction_id = await _enqueue_correction(store, request_id="retry-limit")
    await _isolate_snapshot_job(store.db_path, correction_id)

    async def always_fail(_job) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("persistent failure")

    runner = CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
        handlers={"snapshot": always_fail},
    )
    for attempt in range(1, 6):
        stats = await runner.run_pending(limit=1, max_attempts=5)
        assert stats["failed"] == 1
        status, attempt_count, next_retry_at, _ = await _snapshot_job(
            store.db_path,
            correction_id,
        )
        assert status == ("failed" if attempt == 5 else "pending")
        assert attempt_count == attempt
        if attempt < 5:
            assert next_retry_at is not None
            assert (
                await store.get_memory_correction_derivation_state(correction_id)
                == "pending"
            )
            async with aiosqlite.connect(store.db_path) as db:
                await db.execute(
                    """
                    UPDATE memory_derivation_jobs
                    SET next_retry_at = 0
                    WHERE correction_id = ? AND job_kind = 'snapshot'
                    """,
                    (correction_id,),
                )
                await db.commit()
        else:
            assert next_retry_at is None
            assert (
                await store.get_memory_correction_derivation_state(correction_id)
                == "failed"
            )

    assert await runner.run_pending(limit=1, max_attempts=5) == {
        "completed": 0,
        "failed": 0,
        "superseded": 0,
    }


async def test_portrait_waits_for_profile_retry_before_rebuilding(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    correction_id = await _enqueue_correction(store, request_id="profile-before-portrait")
    calls: list[str] = []
    profile_attempt = 0

    async def snapshot(_job) -> None:  # type: ignore[no-untyped-def]
        calls.append("snapshot")

    async def profile(_job) -> None:  # type: ignore[no-untyped-def]
        nonlocal profile_attempt
        profile_attempt += 1
        calls.append(f"profile-{profile_attempt}")
        if profile_attempt == 1:
            raise RuntimeError("temporary profile failure")

    async def portrait(_job) -> None:  # type: ignore[no-untyped-def]
        calls.append("portrait")
        assert profile_attempt == 2

    runner = CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
        handlers={
            "snapshot": snapshot,
            "profile": profile,
            "portrait": portrait,
        },
    )

    first = await runner.run_pending(limit=10)
    assert first == {"completed": 1, "failed": 1, "superseded": 0}
    assert calls == ["snapshot", "profile-1"]
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT job_kind, status
            FROM memory_derivation_jobs
            WHERE correction_id = ? AND job_kind IN ('profile', 'portrait')
            ORDER BY job_kind
            """,
            (correction_id,),
        ) as cursor:
            assert await cursor.fetchall() == [
                ("portrait", "pending"),
                ("profile", "pending"),
            ]
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET next_retry_at = 0
            WHERE correction_id = ? AND job_kind = 'profile'
            """,
            (correction_id,),
        )
        await db.commit()

    second = await runner.run_pending(limit=10)
    assert second == {"completed": 2, "failed": 0, "superseded": 0}
    assert calls == ["snapshot", "profile-1", "profile-2", "portrait"]


async def test_terminal_profile_failure_marks_portrait_blocked(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    correction_id = await _enqueue_correction(store, request_id="profile-blocks-portrait")

    async def profile(_job) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("profile cannot be rebuilt")

    portrait = AsyncMock()
    runner = CorrectionDerivationRunner(
        db_path=store.db_path,
        l2_store=store,
        handlers={"profile": profile, "portrait": portrait},
    )

    stats = await runner.run_pending(limit=10, max_attempts=1)
    assert stats == {"completed": 1, "failed": 1, "superseded": 0}
    portrait.assert_not_awaited()
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT status, next_retry_at, last_error
            FROM memory_derivation_jobs
            WHERE correction_id = ? AND job_kind = 'portrait'
            """,
            (correction_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert row == ("failed", None, "Blocked by failed profile derivation")
    assert await store.get_memory_correction_derivation_state(correction_id) == "failed"


async def test_stale_running_job_is_recovered_but_exhausted_job_is_terminal(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    correction_id = await _enqueue_correction(store, request_id="stale-running")
    await _isolate_snapshot_job(store.db_path, correction_id)
    old = time.time() - 600
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'running', attempt_count = 2, updated_at = ?
            WHERE correction_id = ? AND job_kind = 'snapshot'
            """,
            (old, correction_id),
        )
        await db.commit()

    recovery = await MemoryCorrectionRepository(store.db_path).recover_stale_running_jobs(
        stale_after_seconds=300,
        max_attempts=5,
    )
    assert recovery == {"requeued": 1, "terminal_failed": 0}
    assert (await _snapshot_job(store.db_path, correction_id))[:2] == ("pending", 2)

    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'running', attempt_count = 5, updated_at = ?
            WHERE correction_id = ? AND job_kind = 'snapshot'
            """,
            (old, correction_id),
        )
        await db.commit()
    recovery = await MemoryCorrectionRepository(store.db_path).recover_stale_running_jobs(
        stale_after_seconds=300,
        max_attempts=5,
    )
    status, attempt_count, next_retry_at, last_error = await _snapshot_job(
        store.db_path,
        correction_id,
    )
    assert recovery == {"requeued": 0, "terminal_failed": 1}
    assert (status, attempt_count, next_retry_at) == ("failed", 5, None)
    assert last_error == "Interrupted after maximum attempts"


async def test_user_correction_only_wakes_scheduler_and_leaves_backlog_pending(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await _enqueue_correction(
        store,
        request_id="existing-backlog",
        entity_id="user:u1",
    )
    assertion_id = await _seed_assertion(
        store,
        entity_id="user:u2",
        trait_name="location.current",
    )
    wakeup = AsyncMock()
    store.set_memory_correction_job_wakeup(wakeup)

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="new-user-correction",
        actor_id="user:u2",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Beijing",
    )

    assert result is not None
    wakeup.assert_awaited_once_with()
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            "SELECT DISTINCT status FROM memory_derivation_jobs"
        ) as cursor:
            statuses = {str(row[0]) for row in await cursor.fetchall()}
    assert statuses == {"pending"}


async def test_store_serializes_concurrent_derivation_drains(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await _enqueue_correction(store, request_id="serialized-drain")
    handler_started = asyncio.Event()
    release_handler = asyncio.Event()

    async def pause_snapshot(_job) -> None:  # type: ignore[no-untyped-def]
        handler_started.set()
        await release_handler.wait()

    store.register_memory_correction_job_handler("snapshot", pause_snapshot)
    first = asyncio.create_task(store.process_memory_correction_jobs(limit=1))
    await asyncio.wait_for(handler_started.wait(), timeout=2)
    second = asyncio.create_task(store.process_memory_correction_jobs(limit=1))
    await asyncio.sleep(0.05)
    assert not second.done()

    release_handler.set()
    first_stats, second_stats = await asyncio.gather(first, second)
    assert first_stats["completed"] == 1
    assert second_stats["completed"] == 1


async def test_runtime_scheduler_retries_failed_derivation_when_due(
    l2_store_with_schema,
    tmp_path,
) -> None:
    store = l2_store_with_schema
    correction_id = await _enqueue_correction(store, request_id="scheduled-retry")
    await _isolate_snapshot_job(store.db_path, correction_id)
    attempts = 0

    async def fail_once(_job) -> None:  # type: ignore[no-untyped-def]
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")

    store.register_memory_correction_job_handler("snapshot", fail_once)
    unified = SimpleNamespace(
        l2=store,
        l2_pipeline=SimpleNamespace(_cognition_store=store),
    )
    l2_cfg = MemoryL2Settings(derive_schedule_interval_seconds=21_600.0)
    config = SimpleNamespace(agent=SimpleNamespace(memory=SimpleNamespace(l2=l2_cfg)))
    scheduler = SchedulerService(
        db_path=tmp_path / "scheduler.db",
        runtime_dir=tmp_path,
    )
    contrib = L2DeriveScheduleContrib()
    container = get_container()
    container.scheduler_service.override(providers.Object(scheduler))
    await scheduler.start()
    try:
        with (
            patch("magi.memory.l2.derive_schedule.get_config", return_value=config),
            patch(
                "magi.memory.l2.derive_schedule.get_unified_memory",
                return_value=unified,
            ),
        ):
            await contrib.register_schedules(scheduler)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status, attempt_count, _, _ = await _snapshot_job(
                    store.db_path,
                    correction_id,
                )
                if status == "completed":
                    break
                await asyncio.sleep(0.05)
            assert (status, attempt_count) == ("completed", 2)
            assert attempts == 2
            await contrib.unregister_schedules(scheduler)
    finally:
        await scheduler.stop()
        container.scheduler_service.reset_override()
