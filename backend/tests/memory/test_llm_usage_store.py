"""Tests for LLM usage storage and aggregation."""

import asyncio
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.llm.usage_store import LLMUsageStore
from magi.core.sqlite import sqlite_connection_async


def _install_llm_usage_schema(db_path: Path) -> None:
    # Apply the real migration chain (0001 + later revisions) so the test schema
    # never drifts from production as columns are added.
    target = next(t for t in MIGRATION_TARGETS if t.name == "llm_usage")
    command.upgrade(_build_config(target, db_path), "head")


@pytest.mark.asyncio
async def test_llm_usage_store_summarizes_prompt_and_completion_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "llm_usage.db"
    _install_llm_usage_schema(db_path)
    store = LLMUsageStore(db_path=db_path)

    await store.record_call(
        {
            "request_id": "req-1",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "request_kind": "task_agent:chat",
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "cache_read_tokens": 80,
            "cache_write_tokens": 10,
            "cache_write_1h_tokens": 4,
            "usage_available": True,
            "latency_ms": 120,
            "success": True,
        }
    )
    await store.record_call(
        {
            "request_id": "req-2",
            "provider": "anthropic",
            "model": "claude-sonnet",
            "request_kind": "function_calling:tools",
            "prompt_tokens": 60,
            "completion_tokens": 30,
            "total_tokens": 90,
            "cache_read_tokens": 20,
            "cache_write_tokens": 5,
            "usage_available": True,
            "latency_ms": 180,
            "success": False,
            "error": "timeout",
        }
    )

    summary = await store.get_summary(days=30)
    timeseries = await store.get_timeseries(days=30)

    assert summary["totals"]["total_calls"] == 2
    assert summary["totals"]["successful_calls"] == 1
    assert summary["totals"]["failed_calls"] == 1
    assert summary["totals"]["prompt_tokens"] == 160
    assert summary["totals"]["completion_tokens"] == 70
    assert summary["totals"]["total_tokens"] == 230
    assert summary["totals"]["cache_read_tokens"] == 100
    assert summary["totals"]["cache_write_tokens"] == 15
    assert summary["totals"]["cache_write_1h_tokens"] == 4
    assert summary["totals"]["cache_hit_rate"] == 62.5
    # No pricing data for these models -> no per-currency cost, breakdown carries NULL currency.
    assert summary["totals"]["cost_by_currency"] == []
    assert summary["providers"][0]["cost_currency"] is None
    assert summary["providers"][0]["provider"] == "openai"
    assert summary["providers"][0]["cache_read_tokens"] == 80
    assert summary["providers"][0]["cache_write_tokens"] == 10
    assert summary["providers"][0]["cache_hit_rate"] == 80.0
    assert len(timeseries) == 1
    assert timeseries[0]["prompt_tokens"] == 160
    assert timeseries[0]["completion_tokens"] == 70
    assert timeseries[0]["cache_read_tokens"] == 100
    assert timeseries[0]["cache_write_tokens"] == 15
    assert timeseries[0]["cache_hit_rate"] == 62.5


@pytest.mark.asyncio
async def test_llm_usage_store_records_cache_observation_diagnostics(tmp_path: Path) -> None:
    db_path = tmp_path / "llm_usage.db"
    _install_llm_usage_schema(db_path)
    store = LLMUsageStore(db_path=db_path)

    await store.record_cache_observation(
        {
            "request_id": "req-1",
            "provider": "openai",
            "model": "gpt-5",
            "request_kind": "function_calling:chat_tools",
            "session_id": "s1",
            "turn_id": "t1",
            "agent_id": "chat",
            "cache_strategy": "prompt_cache_key",
            "cache_eligible": True,
            "system_head_hash": "system-hash",
            "system_head_chars": 1000,
            "dynamic_context_hash": "tail-a",
            "dynamic_context_chars": 200,
            "tools_hash": "tools-a",
            "tool_count": 2,
            "tool_names": ["weather", "web-search"],
            "cache_fields_seen": True,
            "cache_read_tokens": 0,
            "cache_write_tokens": 120,
            "cache_write_1h_tokens": 0,
            "created_at": 1000.0,
        }
    )
    await store.record_cache_observation(
        {
            "request_id": "req-2",
            "provider": "openai",
            "model": "gpt-5",
            "request_kind": "function_calling:chat_tools",
            "session_id": "s1",
            "turn_id": "t2",
            "agent_id": "chat",
            "cache_strategy": "prompt_cache_key",
            "cache_eligible": True,
            "system_head_hash": "system-hash",
            "system_head_chars": 1000,
            "dynamic_context_hash": "tail-b",
            "dynamic_context_chars": 250,
            "tools_hash": "tools-b",
            "tool_count": 3,
            "tool_names": ["file_read", "grep", "find-relevant-tools"],
            "cache_fields_seen": True,
            "cache_read_tokens": 700,
            "cache_write_tokens": 0,
            "cache_write_1h_tokens": 0,
            "created_at": 1010.0,
        }
    )

    rows = await store.list_cache_observations(days=36500)

    assert len(rows) == 2
    latest = rows[0]
    assert latest["request_id"] == "req-2"
    assert latest["system_head_reused"] is True
    assert latest["tools_reused"] is False
    assert latest["predicted_miss_reasons"] == ["tools_changed"]
    assert latest["tool_names"] == ["file_read", "grep", "find-relevant-tools"]
    assert latest["cache_read_tokens"] == 700
    assert "Persona Turn Steer" not in str(latest)


@pytest.mark.asyncio
async def test_clear_user_content_erases_usage_diagnostics_and_rollups(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "llm_usage.db"
    _install_llm_usage_schema(db_path)
    store = LLMUsageStore(db_path=db_path)
    private_marker = "private-usage-error-marker"

    await store.record_call(
        {
            "request_id": "private-request",
            "provider": "private-provider",
            "model": "private-model",
            "request_kind": "chat",
            "success": False,
            "error": private_marker,
        }
    )
    await store.record_cache_observation(
        {
            "request_id": "private-cache-request",
            "provider": "private-provider",
            "model": "private-model",
            "request_kind": "chat",
            "session_id": "private-session",
            "cache_strategy": "none",
            "created_at": 1000.0,
        }
    )
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            """
            INSERT INTO llm_usage_rollups (
                granularity, bucket_start, provider, model, request_kind,
                success, last_rolled_up_at
            ) VALUES ('day', '2026-01-01', ?, ?, 'chat', 0, 1000.0)
            """,
            ("private-provider", "private-model"),
        )
        await db.commit()

    deleted = await store.clear_user_content()

    assert deleted == 3
    assert (await store.get_summary(days=36500))["totals"]["total_calls"] == 0
    assert await store.list_cache_observations(days=36500) == []
    async with sqlite_connection_async(db_path) as db:
        for table_name in (
            "llm_usage",
            "llm_usage_rollups",
            "llm_cache_observations",
        ):
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table_name}")
            assert int((await cursor.fetchone())[0]) == 0
    for candidate in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ):
        if candidate.exists():
            assert private_marker.encode() not in candidate.read_bytes()


@pytest.mark.asyncio
async def test_clear_user_content_waits_for_active_usage_operations(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "llm_usage.db"
    _install_llm_usage_schema(db_path)
    store = LLMUsageStore(db_path=db_path)
    operation_entered = asyncio.Event()
    allow_operation_exit = asyncio.Event()

    async def hold_operation() -> None:
        async with store.user_content_operation():
            operation_entered.set()
            await allow_operation_exit.wait()

    operation_task = asyncio.create_task(hold_operation())
    await operation_entered.wait()
    clear_task = asyncio.create_task(store.clear_user_content())
    await asyncio.sleep(0)

    assert clear_task.done() is False
    allow_operation_exit.set()
    await operation_task
    assert await clear_task == 0
