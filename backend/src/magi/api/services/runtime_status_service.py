"""Runtime topology status helpers for health and readiness endpoints."""

from __future__ import annotations

from typing import Any

from ...bootstrap.runtime_startup_state import get_runtime_startup_snapshot
from ...core.container import get_container
from ...core.runtime_bindings import require_runtime_command_queue

DEFAULT_PENDING_COMMAND_WARNING_THRESHOLD = 100
INFRASTRUCTURE_PROVIDER_NAMES = (
    "runtime_command_queue",
    "chat_store",
    "message_bus",
    "runtime_trace_store",
)


async def get_runtime_system_status(app: Any) -> dict[str, Any]:
    """Return a topology-aware runtime status payload for transport endpoints."""
    api_ready = bool(getattr(getattr(app, "state", None), "backend_ready", True))
    pending_commands = await _get_pending_commands()
    queue_backlog_healthy = (
        pending_commands is None or pending_commands <= DEFAULT_PENDING_COMMAND_WARNING_THRESHOLD
    )
    startup_snapshot = get_runtime_startup_snapshot()
    worker_ready, runtime_status = _get_local_worker_status(startup_snapshot)
    infrastructure_ready = all(
        _resolve_binding(name) is not None for name in INFRASTRUCTURE_PROVIDER_NAMES
    )
    llm_ready = _resolve_binding("scenario_llm_pool") is not None
    agent_runtime_ready = _resolve_binding("agent_runtime") is not None
    runtime_ready = worker_ready and infrastructure_ready and llm_ready and agent_runtime_ready

    startup_state = startup_snapshot.startup_state
    deferred_reason = startup_snapshot.reason
    startup_detail = startup_snapshot.detail

    if startup_state == "offline" and runtime_status != "offline":
        startup_state = runtime_status

    if runtime_ready and queue_backlog_healthy:
        status = "ready"
    else:
        status = "degraded"

    return {
        "api_ready": api_ready,
        "status": status,
        "runtime_ready": runtime_ready,
        "worker_ready": worker_ready,
        "infrastructure_ready": infrastructure_ready,
        "llm_ready": llm_ready,
        "agent_runtime_ready": agent_runtime_ready,
        "runtime_status": runtime_status,
        "startup_state": startup_state,
        "deferred_reason": deferred_reason,
        "startup_detail": startup_detail,
        "queue_backlog_healthy": queue_backlog_healthy,
        "pending_commands": pending_commands,
    }


async def _get_pending_commands() -> int | None:
    try:
        queue = require_runtime_command_queue()
        stats = await queue.get_stats()
    except Exception:
        return None
    return int(stats.get("pending_count", 0) or 0)


def _resolve_binding(provider_name: str):
    try:
        container = get_container()
        provider = getattr(container, provider_name)
        instance = provider()
    except Exception:
        return None

    if instance is None:
        return None
    if type(instance).__name__ == "object" and not provider.overridden:
        return None
    return instance


def _get_local_worker_status(startup_snapshot: Any) -> tuple[bool, str]:
    runtime_status = (
        str(getattr(startup_snapshot, "startup_state", None) or "offline").strip()
        or "offline"
    )
    worker_ready = runtime_status in {"ready", "deferred", "starting", "stopping"}
    return worker_ready, runtime_status
