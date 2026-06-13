"""Tests for LLM usage storage and aggregation."""
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.llm.usage_store import LLMUsageStore


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
    # No pricing data for these models -> no per-currency cost, breakdown carries NULL currency.
    assert summary["totals"]["cost_by_currency"] == []
    assert summary["providers"][0]["cost_currency"] is None
    assert summary["providers"][0]["provider"] == "openai"
    assert len(timeseries) == 1
    assert timeseries[0]["prompt_tokens"] == 160
    assert timeseries[0]["completion_tokens"] == 70
