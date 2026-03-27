"""Runtime topology status helpers for health and readiness endpoints."""

from __future__ import annotations

import time
from typing import Any

from ...core.runtime_bindings import require_runtime_command_queue, require_runtime_trace_store

RUNTIME_HEARTBEAT_ROLE = "runtime_worker"
DEFAULT_RUNTIME_HEARTBEAT_STALE_AFTER_MS = 15_000
DEFAULT_PENDING_COMMAND_WARNING_THRESHOLD = 100


async def get_runtime_system_status(app: Any) -> dict[str, Any]:
    """Return a topology-aware runtime status payload for transport endpoints."""
    api_ready = bool(getattr(app.state, "backend_ready", False))
    process_role = str(getattr(app.state, "process_role", "api") or "api")
    pending_commands = await _get_pending_commands()
    queue_backlog_healthy = (
        pending_commands is None or pending_commands <= DEFAULT_PENDING_COMMAND_WARNING_THRESHOLD
    )
    runtime_ready, runtime_status, heartbeat_age_ms = await _get_runtime_worker_status()

    if not api_ready:
        status = "starting"
    elif runtime_ready and queue_backlog_healthy:
        status = "ready"
    else:
        status = "degraded"

    return {
        "status": status,
        "api_ready": api_ready,
        "runtime_ready": runtime_ready,
        "runtime_status": runtime_status,
        "runtime_heartbeat_age_ms": heartbeat_age_ms,
        "queue_backlog_healthy": queue_backlog_healthy,
        "pending_commands": pending_commands,
        "process_role": process_role,
    }


async def _get_pending_commands() -> int | None:
    try:
        queue = require_runtime_command_queue()
        stats = await queue.get_stats()
    except Exception:
        return None
    return int(stats.get("pending_count", 0) or 0)


async def _get_runtime_worker_status() -> tuple[bool, str, int | None]:
    try:
        store = require_runtime_trace_store()
        heartbeat = await store.get_runtime_heartbeat(role=RUNTIME_HEARTBEAT_ROLE)
    except Exception:
        return False, "offline", None

    if heartbeat is None:
        return False, "offline", None

    now_ms = int(time.time() * 1000)
    heartbeat_age_ms = max(0, now_ms - int(heartbeat.last_seen_at_ms or 0))
    if heartbeat_age_ms > DEFAULT_RUNTIME_HEARTBEAT_STALE_AFTER_MS:
        return False, "stale", heartbeat_age_ms

    runtime_status = str(heartbeat.status or "offline").strip() or "offline"
    runtime_ready = runtime_status == "ready"
    return runtime_ready, runtime_status, heartbeat_age_ms
