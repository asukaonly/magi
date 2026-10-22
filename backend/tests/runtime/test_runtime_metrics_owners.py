"""Operational diagnostics query each domain's storage representation."""

from _shared.memory_stores import build_l1_store, build_memory_store
import time
from contextlib import closing
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.ipc import metrics_handler
from magi.llm.usage_store import LLMUsageStore
from magi.scheduler.repository import ScheduleRepository


@pytest.mark.asyncio
async def test_llm_runtime_metrics_use_recent_chat_calls(tmp_path, ensure_db_schema):
    path = tmp_path / "usage.db"
    ensure_db_schema("llm_usage", str(path))
    store = LLMUsageStore(path)
    now = time.time()
    for index, (kind, success, ttft, timestamp) in enumerate([
        ("chat", True, 200, now), ("chat", False, 0, now),
        ("embedding", False, 400, now), ("chat", False, 600, now-7200),
    ]):
        await store.record_call({"request_id": str(index), "request_kind": kind, "success": success, "ttft_ms": ttft, "created_at": timestamp})
    assert await store.get_runtime_metrics(since=now-3600) == {
        "avg_ttft_ms": 300.0, "ttft_available": True,
        "core_model_success_rate": 50.0, "core_model_success_rate_available": True,
    }


@pytest.mark.asyncio
async def test_scheduler_next_run_comes_from_jobstore(tmp_path, ensure_db_schema):
    path = tmp_path / "scheduler.db"
    ensure_db_schema("scheduler", str(path))
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE apscheduler_jobs (id TEXT PRIMARY KEY, next_run_time REAL, job_state BLOB)")
        conn.execute("INSERT INTO schedules(schedule_id,target_type,target_key,trigger_type,trigger_config,target_payload,metadata,enabled,created_at,updated_at,job_id) VALUES('one','source_sync','source','interval','{}','{}','{}',1,1,1,'job-one')")
        conn.execute("INSERT INTO target_state(target_type,target_key,running,updated_at) VALUES('source_sync','source',0,1)")
        conn.execute("INSERT INTO apscheduler_jobs(id,next_run_time) VALUES('job-one',123)")
        conn.commit()
    result = await ScheduleRepository(path).get_runtime_metrics()
    assert result["enabled_schedule_count"] == 1
    assert result["upcoming_target_count"] == 1
    assert result["recent_targets"][0]["next_run_at"] == 123


@pytest.mark.asyncio
async def test_l1_pending_reads_numeric_embedding_state_and_excludes_orphans(tmp_path, ensure_db_schema):
    path = tmp_path / "l1.db"
    ensure_db_schema("l1", str(path))
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO fact_events(event_id,event_type,source,timestamp,created_at,memory_domain,content,author_type,content_type) VALUES('event','test','test',1,1,1,'test',1,1)")
        conn.execute("INSERT INTO l1_event_embedding_state(event_id,embedding_status,updated_at) VALUES('event',2,1)")
        conn.execute("INSERT INTO l1_event_embedding_state(event_id,embedding_status,updated_at) VALUES('orphan',2,1)")
        conn.commit()
    store = build_l1_store(db_path=str(path))
    assert await store.count_pending_embeddings() == 1


@pytest.mark.asyncio
async def test_metrics_failure_is_section_local_and_does_not_invent_zeros(monkeypatch):
    usage = SimpleNamespace(get_runtime_metrics=AsyncMock(side_effect=RuntimeError("unavailable")))
    memory = SimpleNamespace(get_runtime_metrics=AsyncMock(return_value={"total_pending": 3}))
    scheduler = SimpleNamespace(repository=SimpleNamespace(get_runtime_metrics=AsyncMock(return_value={"running_target_count": 1})))
    monkeypatch.setattr(metrics_handler, "get_api_runtime_dependencies", lambda: SimpleNamespace(llm_usage_store=usage))
    monkeypatch.setattr(metrics_handler, "get_unified_memory", lambda: memory)
    monkeypatch.setattr(metrics_handler, "require_scheduler_service", lambda: scheduler)
    result = await metrics_handler.runtime_metrics(None)
    assert result == {"model_execution": None, "memory": {"total_pending": 3}, "scheduler": {"running_target_count": 1}}


@pytest.mark.asyncio
async def test_memory_runtime_snapshot_uses_all_layer_owners(tmp_path, ensure_db_schema):
    l1_path = tmp_path / "l1.db"
    memory_path = tmp_path / "memory.db"
    ensure_db_schema("l1", str(l1_path))
    ensure_db_schema("memory_shared", str(memory_path))
    store = build_memory_store(l1_db_path=str(l1_path), memory_db_path=str(memory_path), enable_l0=False)
    snapshot = await store.get_runtime_metrics()
    assert snapshot["total_pending"] == 0
    assert set(snapshot["embeddings"]) == {"total_pending", "l1", "l3", "l4"}
    assert snapshot["l2"]["is_running"] is False
