from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from magi.api.routers import metrics as metrics_router
from magi.scheduler.contracts import (
    ScheduleDefinition,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)

metrics_overview_service = importlib.import_module("magi.api.services.metrics_overview_service")


class _FakeUsageStore:
    async def get_summary(self, *, days: int, model_limit: int) -> dict[str, object]:
        assert days == 30
        assert model_limit == 8
        return {
            "window_days": days,
            "totals": {
                "total_calls": 12,
                "successful_calls": 11,
                "failed_calls": 1,
                "calls_with_usage": 12,
                "prompt_tokens": 1200,
                "completion_tokens": 400,
                "total_tokens": 1600,
                "avg_latency_ms": 980.5,
                "avg_ttft_ms": 420.0,
                "total_cost_usd": 1.245,
            },
            "providers": [
                {
                    "provider": "openai",
                    "calls": 12,
                    "successful_calls": 11,
                    "failed_calls": 1,
                    "prompt_tokens": 1200,
                    "completion_tokens": 400,
                    "total_tokens": 1600,
                    "avg_latency_ms": 980.5,
                    "avg_ttft_ms": 420.0,
                    "cost_usd": 1.245,
                }
            ],
            "models": [],
            "request_kinds": [],
        }

    async def get_timeseries(self, *, days: int) -> list[dict[str, object]]:
        assert days == 30
        return [
            {
                "day": "2026-03-24",
                "calls": 12,
                "prompt_tokens": 1200,
                "completion_tokens": 400,
                "total_tokens": 1600,
                "cost_usd": 1.245,
            }
        ]


class _FakeRuntimeOverviewUsageStore:
    async def get_summary(self, *, days: int, model_limit: int) -> dict[str, object]:
        assert days == 1
        assert model_limit == 5
        return {
            "window_days": days,
            "totals": {
                "total_calls": 12,
                "successful_calls": 11,
                "failed_calls": 1,
                "calls_with_usage": 12,
                "prompt_tokens": 1200,
                "completion_tokens": 400,
                "total_tokens": 1600,
                "avg_latency_ms": 980.5,
                "avg_ttft_ms": 420.0,
                "total_cost_usd": 1.245,
            },
            "providers": [],
            "models": [],
            "request_kinds": [],
        }


class _FakeEmbeddingLayer:
    def __init__(self, pending: int) -> None:
        self._pending = pending

    def get_statistics(self) -> dict[str, object]:
        return {
            "embedding_queue_size": self._pending,
            "embedding_worker_running": self._pending > 0,
            "vector_enabled": True,
            "async_embeddings": True,
        }


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l1 = _FakeEmbeddingLayer(2)
        self.l3 = _FakeEmbeddingLayer(1)
        self.l4 = _FakeEmbeddingLayer(0)

    def get_l2_pipeline_stats(self) -> dict[str, int | bool]:
        return {
            "is_running": True,
            "extract_enqueued": 6,
            "extract_completed": 4,
            "extract_failed": 1,
            "extract_skipped": 0,
            "reconcile_enqueued": 5,
            "reconcile_completed": 4,
            "reconcile_failed": 0,
            "snapshot_enqueued": 3,
            "snapshot_completed": 1,
            "snapshot_failed": 0,
        }


class _FakeSchedulerRepository:
    async def list_schedules(self, *, enabled_only: bool = False) -> list[ScheduleDefinition]:
        assert enabled_only is True
        return [
            ScheduleDefinition(
                schedule_id="timeline-sync:core:history",
                target_type=ScheduledTargetType.TIMELINE_SENSOR_SYNC,
                target_key="core:history",
                trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 60}),
                target_payload={},
                enabled=True,
            )
        ]


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.repository = _FakeSchedulerRepository()

    async def get_target_state(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> ScheduledTargetState:
        assert target_type is ScheduledTargetType.TIMELINE_SENSOR_SYNC
        assert target_key == "core:history"
        return ScheduledTargetState(
            target_type=target_type,
            target_key=target_key,
            running=True,
            last_error=None,
            next_run_at=1711260000.0,
            updated_at=1711259900.0,
        )


@pytest.mark.asyncio
async def test_get_llm_usage_summary_returns_extended_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_router, "get_llm_usage_store", lambda: _FakeUsageStore())

    response = await metrics_router.get_llm_usage_summary(days=30, model_limit=8)

    assert response["success"] is True
    assert response["data"]["totals"]["avg_ttft_ms"] == 420.0
    assert response["data"]["totals"]["total_cost_usd"] == 1.245
    assert response["data"]["providers"][0]["failed_calls"] == 1
    assert response["data"]["providers"][0]["cost_usd"] == 1.245


@pytest.mark.asyncio
async def test_get_llm_usage_timeseries_returns_cost_series(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_router, "get_llm_usage_store", lambda: _FakeUsageStore())

    response = await metrics_router.get_llm_usage_timeseries(days=30)

    assert response["success"] is True
    assert response["data"]["window_days"] == 30
    assert response["data"]["points"][0]["cost_usd"] == 1.245


@pytest.mark.asyncio
async def test_build_runtime_overview_returns_aggregated_runtime_data(monkeypatch: pytest.MonkeyPatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="combined"))
    fake_memory = SimpleNamespace(percent=48.0, used=5 * 1024**3, total=16 * 1024**3)

    async def _fake_runtime_status(_app):
        return {
            "status": "ready",
            "api_ready": True,
            "runtime_ready": True,
            "runtime_status": "ready",
            "runtime_heartbeat_age_ms": 1200,
            "queue_backlog_healthy": True,
            "pending_commands": 3,
            "process_role": "combined",
        }

    monkeypatch.setattr(
        metrics_overview_service,
        "get_runtime_system_status",
        _fake_runtime_status,
    )
    monkeypatch.setattr(metrics_overview_service.psutil, "cpu_percent", lambda interval=0.1: 26.0)
    monkeypatch.setattr(metrics_overview_service.psutil, "virtual_memory", lambda: fake_memory)
    monkeypatch.setattr(metrics_overview_service, "require_unified_memory", lambda: _FakeUnifiedMemory())
    monkeypatch.setattr(metrics_overview_service, "require_scheduler_service", lambda: _FakeSchedulerService())
    monkeypatch.setattr(metrics_overview_service, "get_llm_usage_store", lambda: _FakeRuntimeOverviewUsageStore())

    overview = await metrics_overview_service.build_runtime_overview(app)

    assert overview["system"]["cpu_percent"] == 26.0
    assert overview["runtime"]["pending_commands"] == 3
    assert overview["model_execution"]["avg_ttft_ms"] == 420.0
    assert overview["memory"]["l2"]["extract_pending"] == 1
    assert overview["memory"]["l2"]["total_pending"] == 4
    assert overview["memory"]["embeddings"]["total_pending"] == 3
    assert overview["memory"]["total_pending"] == 7
    assert overview["scheduler"]["enabled_schedule_count"] == 1
    assert overview["scheduler"]["running_target_count"] == 1


@pytest.mark.asyncio
async def test_get_runtime_overview_wraps_service_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {"runtime": {"status": "ready"}}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    async def _fake_build_runtime_overview(app):
        return expected

    monkeypatch.setattr(metrics_router, "build_runtime_overview", _fake_build_runtime_overview)

    response = await metrics_router.get_runtime_overview(request=request)

    assert response["success"] is True
    assert response["data"] == expected
