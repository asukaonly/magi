"""Aggregation helpers for settings-facing runtime metrics."""

from __future__ import annotations

import time
from typing import Any

import psutil

from ...core.runtime_bindings import require_scheduler_service, require_unified_memory
from ...llm import get_llm_usage_store
from .runtime_status_service import get_runtime_system_status


def _build_l2_pending_breakdown(
    pipeline_stats: dict[str, Any],
    projection_backlog: dict[str, Any] | None = None,
) -> dict[str, int]:
    durable_projection = dict(projection_backlog or {})
    return {
        "extract_pending": max(
            int(durable_projection.get("pending", 0)) + int(durable_projection.get("claimed", 0)),
            0,
        ),
        "reconcile_pending": max(
            int(pipeline_stats.get("reconcile_enqueued", 0))
            - int(pipeline_stats.get("reconcile_completed", 0))
            - int(pipeline_stats.get("reconcile_failed", 0)),
            0,
        ),
        "snapshot_pending": max(
            int(pipeline_stats.get("snapshot_enqueued", 0))
            - int(pipeline_stats.get("snapshot_completed", 0))
            - int(pipeline_stats.get("snapshot_failed", 0)),
            0,
        ),
    }


def _build_embedding_pending(stats: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(stats or {})
    pending = int(payload.get("embedding_queue_size", 0) or 0)
    return {
        "pending": max(pending, 0),
        "worker_running": bool(payload.get("embedding_worker_running", False)),
        "vector_enabled": bool(payload.get("vector_enabled", False)),
        "async_embeddings": bool(payload.get("async_embeddings", False)),
    }


async def build_runtime_overview(app: Any) -> dict[str, Any]:
    """Return a settings-facing runtime overview payload."""
    runtime_status = await get_runtime_system_status(app)
    memory = psutil.virtual_memory()

    return {
        "captured_at_ms": int(time.time() * 1000),
        "system": {
            "cpu_percent": float(psutil.cpu_percent(interval=0.1)),
            "memory_percent": float(memory.percent),
            "memory_used_gb": round(float(memory.used) / (1024**3), 2),
            "memory_total_gb": round(float(memory.total) / (1024**3), 2),
        },
        "runtime": runtime_status,
        "model_execution": await _build_model_execution_summary(),
        "memory": await _build_memory_summary(),
        "scheduler": await _build_scheduler_summary(),
    }


async def _build_model_execution_summary() -> dict[str, Any]:
    try:
        summary = await get_llm_usage_store().get_summary(days=1, model_limit=5)
    except Exception:
        summary = None

    totals = summary.get("totals", {}) if isinstance(summary, dict) else {}
    total_calls = int(totals.get("total_calls", 0) or 0)
    successful_calls = int(totals.get("successful_calls", 0) or 0)
    avg_ttft_ms = totals.get("avg_ttft_ms")
    success_rate = None
    if total_calls > 0:
        success_rate = round((successful_calls / total_calls) * 100, 2)

    return {
        "avg_ttft_ms": avg_ttft_ms,
        "ttft_available": avg_ttft_ms is not None,
        "core_model_success_rate": success_rate,
        "core_model_success_rate_available": success_rate is not None,
        "intent_success_rate": None,
        "intent_success_rate_available": False,
    }


async def _build_memory_summary() -> dict[str, Any]:
    try:
        unified_memory = require_unified_memory()
    except Exception:
        return {
            "total_pending": 0,
            "l2": {
                "is_running": False,
                "extract_pending": 0,
                "reconcile_pending": 0,
                "snapshot_pending": 0,
                "total_pending": 0,
            },
            "embeddings": {
                "l1": {"pending": 0, "worker_running": False, "vector_enabled": False, "async_embeddings": False},
                "l3": {"pending": 0, "worker_running": False, "vector_enabled": False, "async_embeddings": False},
                "l4": {"pending": 0, "worker_running": False, "vector_enabled": False, "async_embeddings": False},
                "total_pending": 0,
            },
        }

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else {"pending": 0, "claimed": 0, "completed": 0, "failed": 0}
    )
    l2_pending = _build_l2_pending_breakdown(pipeline_stats, projection_backlog)
    l1_pending = _build_embedding_pending(
        unified_memory.l1.get_statistics() if getattr(unified_memory, "l1", None) and hasattr(unified_memory.l1, "get_statistics") else None
    )
    l3_pending = _build_embedding_pending(
        unified_memory.l3.get_statistics() if getattr(unified_memory, "l3", None) and hasattr(unified_memory.l3, "get_statistics") else None
    )
    l4_pending = _build_embedding_pending(
        unified_memory.l4.get_statistics() if getattr(unified_memory, "l4", None) and hasattr(unified_memory.l4, "get_statistics") else None
    )

    l2_total_pending = sum(l2_pending.values())
    embedding_total_pending = int(l1_pending["pending"]) + int(l3_pending["pending"]) + int(l4_pending["pending"])

    return {
        "total_pending": l2_total_pending + embedding_total_pending,
        "l2": {
            "is_running": bool(pipeline_stats.get("is_running", False)),
            **l2_pending,
            "total_pending": l2_total_pending,
        },
        "embeddings": {
            "l1": l1_pending,
            "l3": l3_pending,
            "l4": l4_pending,
            "total_pending": embedding_total_pending,
        },
    }


async def _build_scheduler_summary() -> dict[str, Any]:
    try:
        scheduler_service = require_scheduler_service()
        schedules = await scheduler_service.repository.list_schedules(enabled_only=True)
    except Exception:
        return {
            "enabled_schedule_count": 0,
            "running_target_count": 0,
            "errored_target_count": 0,
            "upcoming_target_count": 0,
            "recent_targets": [],
        }

    recent_targets: list[dict[str, Any]] = []
    running_target_count = 0
    errored_target_count = 0
    upcoming_target_count = 0

    for schedule in schedules:
        state = await scheduler_service.get_target_state(schedule.target_type, schedule.target_key)
        running_target_count += 1 if state.running else 0
        errored_target_count += 1 if state.last_error else 0
        upcoming_target_count += 1 if state.next_run_at else 0
        recent_targets.append(
            {
                "target_type": schedule.target_type.value,
                "target_key": schedule.target_key,
                "running": bool(state.running),
                "last_error": state.last_error,
                "next_run_at": state.next_run_at,
                "updated_at": state.updated_at,
            }
        )

    recent_targets.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)

    return {
        "enabled_schedule_count": len(schedules),
        "running_target_count": running_target_count,
        "errored_target_count": errored_target_count,
        "upcoming_target_count": upcoming_target_count,
        "recent_targets": recent_targets[:5],
    }
