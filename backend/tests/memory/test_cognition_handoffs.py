"""Fault-injection coverage for durable L1-to-cognition delivery."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from unittest.mock import AsyncMock

import pytest

from magi.memory.unified_store import UnifiedMemoryStore


def _memory(paths):
    return UnifiedMemoryStore(
        l1_db_path=str(paths.l1_memory_db_path),
        memory_db_path=str(paths.memory_db_path),
        persist_dir=str(paths.memory_dir),
        enable_l0=False, enable_l1=True, enable_l2=True,
        enable_l3=False, enable_l4=False, scenario_llm_pool=None,
    )


def _event(event_id="handoff-event"):
    return {
        "id": event_id, "type": "USER_MESSAGE", "source": "chat",
        "timestamp": time.time(),
        "data": {"user_id": "local_user", "session_id": "handoff-session", "content": "I love jazz."},
    }


def _ready(paths):
    with sqlite3.connect(paths.l1_memory_db_path) as db:
        db.execute("UPDATE l1_cognition_handoffs SET available_at = 0")


@pytest.mark.asyncio
async def test_handoff_survives_enqueue_failure_restart_and_duplicate(runtime_paths_with_schema, monkeypatch):
    paths = runtime_paths_with_schema
    memory = _memory(paths)
    await memory.initialize(start_projection_workers=False)
    failing = AsyncMock(side_effect=RuntimeError("temporary queue failure"))
    monkeypatch.setattr(memory.l2, "enqueue_projection_job", failing)
    result = await memory.ingest_event(_event())
    assert result["l1_confirmed"] is True
    assert result["l2_job_enqueued"] is False
    assert failing.await_count == 1
    assert await memory.l1.list_ready_cognition_handoffs() == [result["event_id"]]
    assert await memory.drain_l1_cognition_handoffs() == 0
    assert await memory.l1.list_ready_cognition_handoffs() == []
    with sqlite3.connect(paths.l1_memory_db_path) as db:
        assert db.execute("SELECT attempt_count, last_error FROM l1_cognition_handoffs").fetchone() == (1, "RuntimeError")
    await memory.shutdown()
    memory = _memory(paths)
    await memory.initialize(start_projection_workers=False)
    try:
        _ready(paths)
        assert await memory.drain_l1_cognition_handoffs() == 1
        assert await memory.l2.has_projection_job(event_id=result["event_id"])
        await memory.ingest_event(_event())
        assert await memory.drain_l1_cognition_handoffs() == 0
        with sqlite3.connect(paths.memory_db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM l2_projection_jobs").fetchone() == (1,)
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_handoff_ack_failure_does_not_duplicate_projection(runtime_paths_with_schema, monkeypatch):
    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    try:
        result = await memory.ingest_event(_event())
        complete = memory.l1.complete_cognition_handoff
        monkeypatch.setattr(memory.l1, "complete_cognition_handoff", AsyncMock(side_effect=RuntimeError("ack interrupted")))
        assert await memory.drain_l1_cognition_handoffs() == 0
        monkeypatch.setattr(memory.l1, "complete_cognition_handoff", complete)
        _ready(runtime_paths_with_schema)
        assert await memory.drain_l1_cognition_handoffs() == 1
        with sqlite3.connect(runtime_paths_with_schema.memory_db_path) as db:
            rows = db.execute("SELECT event_id, status, attempt_count FROM l2_projection_jobs").fetchall()
        assert rows == [(result["event_id"], "pending", 0)]
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_forget_removes_pending_handoff_without_recreating_l2(runtime_paths_with_schema, monkeypatch):
    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    try:
        enqueue = memory.l2.enqueue_projection_job
        monkeypatch.setattr(memory.l2, "enqueue_projection_job", AsyncMock(side_effect=RuntimeError("unavailable")))
        result = await memory.ingest_event(_event())
        await memory.forget_source_events([result["event_id"]], reason="user_request")
        monkeypatch.setattr(memory.l2, "enqueue_projection_job", enqueue)
        assert await memory.drain_l1_cognition_handoffs() == 0
        assert not await memory.l2.has_projection_job(event_id=result["event_id"])
        replay = await memory.ingest_event(_event())
        assert replay["skip_reason"] == "source_event_forgotten"
        assert await memory.l1.list_ready_cognition_handoffs() == []
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_clear_fences_inflight_handoff_and_prevents_replay(runtime_paths_with_schema, monkeypatch):
    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    original = memory.l2.enqueue_projection_job
    monkeypatch.setattr(memory.l2, "enqueue_projection_job", AsyncMock(side_effect=RuntimeError("unavailable")))
    await memory.ingest_event(_event())
    started, release = asyncio.Event(), asyncio.Event()

    async def paused_enqueue(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(memory.l2, "enqueue_projection_job", paused_enqueue)
    draining = asyncio.create_task(memory.drain_l1_cognition_handoffs())
    clearing = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        clearing = asyncio.create_task(memory.clear_all_memory())
        await asyncio.sleep(0)
        assert not clearing.done()
        release.set()
        await asyncio.wait_for(draining, 5)
        await asyncio.wait_for(clearing, 5)
        assert await memory.drain_l1_cognition_handoffs() == 0
        assert await memory.l1.count_events() == 0
        assert not await memory.l2.has_projection_job(event_id="handoff-event")
    finally:
        release.set()
        await asyncio.gather(draining, *( [clearing] if clearing else [] ), return_exceptions=True)
        await memory.shutdown()


@pytest.mark.asyncio
async def test_policy_error_retries_but_intentional_skip_completes(runtime_paths_with_schema, monkeypatch):
    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    try:
        from magi.memory.layers.l2_layer import L2ProjectionLayer
        monkeypatch.setattr(memory.l2, "enqueue_projection_job", AsyncMock(side_effect=RuntimeError("unavailable")))
        result = await memory.ingest_event(_event())
        monkeypatch.setattr(L2ProjectionLayer, "_resolve_policy_markers", lambda *_: {"l2_policy_allows_projection": False, "l2_evidence_class": "unknown", "l2_skip_reason": "classification_error"})
        assert await memory.drain_l1_cognition_handoffs() == 0
        _ready(runtime_paths_with_schema)
        monkeypatch.setattr(L2ProjectionLayer, "_resolve_policy_markers", lambda *_: {"l2_policy_allows_projection": False, "l2_evidence_class": "system_runtime", "l2_skip_reason": "system_runtime"})
        assert await memory.drain_l1_cognition_handoffs() == 1
        assert not await memory.l2.has_projection_job(event_id=result["event_id"])
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_fact_and_handoff_commit_atomically(runtime_paths_with_schema):
    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    try:
        with sqlite3.connect(runtime_paths_with_schema.l1_memory_db_path) as db:
            db.execute("""
                CREATE TRIGGER reject_handoff BEFORE INSERT ON l1_cognition_handoffs
                BEGIN SELECT RAISE(ABORT, 'handoff unavailable'); END
            """)
        with pytest.raises(sqlite3.IntegrityError, match="handoff unavailable"):
            await memory.ingest_event(_event())
        assert await memory.l1.count_events() == 0
        assert await memory.l1.list_ready_cognition_handoffs() == []
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_migration_backfill_does_not_replay_completed_jobs(runtime_paths_with_schema, monkeypatch):
    from types import SimpleNamespace
    from magi.db.migrations.l1.versions import v6_cognition_handoffs as migration

    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    try:
        result = await memory.ingest_event(_event())
        with sqlite3.connect(runtime_paths_with_schema.memory_db_path) as db:
            db.execute("UPDATE l2_projection_jobs SET status = 'completed', attempt_count = 2, completed_at = 123")
        with sqlite3.connect(runtime_paths_with_schema.l1_memory_db_path) as db:
            db.execute("DELETE FROM l1_cognition_handoffs")
            monkeypatch.setattr(migration.op, "get_bind", lambda: SimpleNamespace(connection=db))
            monkeypatch.setattr(migration.op, "execute", db.execute)
            migration.upgrade()
            migration.upgrade()
        assert await memory.l1.list_ready_cognition_handoffs() == [result["event_id"]]
        assert await memory.drain_l1_cognition_handoffs() == 1
        assert await memory.drain_l1_cognition_handoffs() == 0
        with sqlite3.connect(runtime_paths_with_schema.memory_db_path) as db:
            assert db.execute("SELECT event_id, status, attempt_count, completed_at FROM l2_projection_jobs").fetchall() == [(result["event_id"], "completed", 2, 123)]
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_flush_worker_nested_handoff_guard_allows_waiting_clear(runtime_paths_with_schema, monkeypatch):
    memory = _memory(runtime_paths_with_schema)
    await memory.initialize(start_projection_workers=False)
    await memory.ingest_event(_event())
    pipeline = memory.l2_pipeline
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_handoff():
        entered.set()
        await release.wait()
        return await memory.drain_l1_cognition_handoffs()

    monkeypatch.setattr(pipeline, "_projection_handoff_callback", paused_handoff)
    pipeline._stats.is_running = True
    worker = asyncio.create_task(pipeline._run_flush_worker())
    pipeline._flush_worker = worker
    clearing = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        clearing = asyncio.create_task(memory.clear_all_memory())
        # Wait until exclusive admission is queued while the outer worker guard is held.
        for _ in range(100):
            if memory._clear_barrier._exclusive_waiters:
                break
            await asyncio.sleep(0)
        assert memory._clear_barrier._exclusive_waiters == 1
        pipeline._stats.is_running = False
        release.set()
        await asyncio.wait_for(clearing, 5)
        await asyncio.wait_for(worker, 5)
        assert await memory.l1.count_events() == 0
        assert await memory.l1.list_ready_cognition_handoffs() == []
    finally:
        pipeline._stats.is_running = False
        release.set()
        await asyncio.gather(worker, *([clearing] if clearing else []), return_exceptions=True)
        await memory.shutdown()
