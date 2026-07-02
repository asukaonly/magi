"""Runtime topology status helpers for health and readiness endpoints."""

from __future__ import annotations

import time
from typing import Any

from ...bootstrap.runtime_startup_state import get_runtime_startup_snapshot
from ...core.container import get_container
from ...core.runtime_bindings import require_runtime_command_queue
from ...runtime_trace.provider import resolve_runtime_trace_store

RUNTIME_HEARTBEAT_ROLE = "ipc_worker"
DEFAULT_RUNTIME_HEARTBEAT_STALE_AFTER_MS = 15_000
DEFAULT_PENDING_COMMAND_WARNING_THRESHOLD = 100
INFRASTRUCTURE_PROVIDER_NAMES = (
    "runtime_command_queue",
    "chat_store",
    "message_bus",
    "runtime_trace_store",
)


async def get_runtime_system_status(
    app: Any,
    *,
    trust_local_worker: bool = False,
) -> dict[str, Any]:
    """Return a topology-aware runtime status payload for transport endpoints."""
    api_ready = bool(getattr(getattr(app, "state", None), "backend_ready", True))
    pending_commands = await _get_pending_commands()
    queue_backlog_healthy = (
        pending_commands is None or pending_commands <= DEFAULT_PENDING_COMMAND_WARNING_THRESHOLD
    )
    startup_snapshot = get_runtime_startup_snapshot()
    if trust_local_worker:
        worker_ready, runtime_status, heartbeat_age_ms, heartbeat_reason = _get_local_worker_status(
            startup_snapshot
        )
    else:
        worker_ready, runtime_status, heartbeat_age_ms, heartbeat_reason = await _get_runtime_worker_status()
    infrastructure_ready = all(_resolve_binding(name) is not None for name in INFRASTRUCTURE_PROVIDER_NAMES)
    llm_ready = _resolve_binding("scenario_llm_pool") is not None
    agent_runtime_ready = _resolve_binding("agent_runtime") is not None
    runtime_ready = worker_ready and infrastructure_ready and llm_ready and agent_runtime_ready

    startup_state = startup_snapshot.startup_state
    deferred_reason = startup_snapshot.reason
    startup_detail = startup_snapshot.detail

    if startup_state == "offline" and runtime_status not in {"offline", "stale"}:
        startup_state = runtime_status
    if deferred_reason is None and runtime_status == "deferred":
        deferred_reason = heartbeat_reason

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
        "runtime_heartbeat_age_ms": heartbeat_age_ms,
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


def _get_local_worker_status(startup_snapshot: Any) -> tuple[bool, str, None, str | None]:
    runtime_status = (
        str(getattr(startup_snapshot, "startup_state", None) or "offline").strip()
        or "offline"
    )
    worker_ready = runtime_status in {"ready", "deferred", "starting", "stopping"}
    heartbeat_reason = getattr(startup_snapshot, "reason", None) or getattr(startup_snapshot, "detail", None)
    return worker_ready, runtime_status, None, heartbeat_reason


async def _get_runtime_worker_status() -> tuple[bool, str, int | None, str | None]:
    try:
        store = resolve_runtime_trace_store()
        heartbeat = await store.get_runtime_heartbeat(role=RUNTIME_HEARTBEAT_ROLE)
    except Exception:
        return False, "offline", None, None

    if heartbeat is None:
        return False, "offline", None, None

    now_ms = int(time.time() * 1000)
    heartbeat_age_ms = max(0, now_ms - int(heartbeat.last_seen_at_ms or 0))
    if heartbeat_age_ms > DEFAULT_RUNTIME_HEARTBEAT_STALE_AFTER_MS:
        return False, "stale", heartbeat_age_ms, heartbeat.last_error

    runtime_status = str(heartbeat.status or "offline").strip() or "offline"
    worker_ready = runtime_status in {"ready", "deferred", "starting", "stopping"}
    return worker_ready, runtime_status, heartbeat_age_ms, heartbeat.last_error
