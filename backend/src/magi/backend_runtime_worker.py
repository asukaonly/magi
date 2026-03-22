"""Background runtime worker entrypoint."""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid

from .bootstrap import initialize_agent_runtime, shutdown_agent_runtime
from .core.container import get_container, wire_container
from .core.logger import get_logger
from .core.runtime_bindings import require_runtime_command_queue, require_runtime_trace_store
from .process_roles import ProcessRole
from .runtime_trace import RuntimeHeartbeatRecord

logger = get_logger(__name__)
DEFAULT_RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 2.0
DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS = 5.0
RUNTIME_HEARTBEAT_ROLE = "runtime_worker"


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install signal handlers that stop the runtime worker."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            logger.warning("Signal handler registration is unavailable", signal=sig.name)


async def run_runtime_worker() -> None:
    """Run the background runtime worker until interrupted."""
    wire_container()
    await initialize_agent_runtime(role=ProcessRole.RUNTIME_WORKER)

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    instance_id = uuid.uuid4().hex
    started_at_ms = int(time.time() * 1000)
    status_ref = {"value": "ready"}
    await _publish_runtime_heartbeat(
        instance_id=instance_id,
        started_at_ms=started_at_ms,
        status=status_ref["value"],
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            stop_event=stop_event,
            instance_id=instance_id,
            started_at_ms=started_at_ms,
            status_ref=status_ref,
        )
    )

    try:
        await stop_event.wait()
    finally:
        status_ref["value"] = "draining"
        await _begin_runtime_drain(timeout_seconds=DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS)
        await _publish_runtime_heartbeat(
            instance_id=instance_id,
            started_at_ms=started_at_ms,
            status="stopping",
        )
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await shutdown_agent_runtime()


async def _heartbeat_loop(
    *,
    stop_event: asyncio.Event,
    instance_id: str,
    started_at_ms: int,
    status_ref: dict[str, str],
    interval_seconds: float = DEFAULT_RUNTIME_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    while not stop_event.is_set():
        await _publish_runtime_heartbeat(
            instance_id=instance_id,
            started_at_ms=started_at_ms,
            status=status_ref["value"],
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue


async def _publish_runtime_heartbeat(
    *,
    instance_id: str,
    started_at_ms: int,
    status: str,
    last_error: str | None = None,
) -> None:
    try:
        store = require_runtime_trace_store()
        queue_backlog = await _load_pending_command_count()
        await store.upsert_runtime_heartbeat(
            RuntimeHeartbeatRecord(
                role=RUNTIME_HEARTBEAT_ROLE,
                instance_id=instance_id,
                pid=os.getpid(),
                started_at_ms=started_at_ms,
                last_seen_at_ms=int(time.time() * 1000),
                status=status,
                queue_backlog=queue_backlog,
                active_turns=0,
                active_workers=0,
                last_error=last_error,
            )
        )
    except Exception as exc:
        logger.warning("Failed to publish runtime heartbeat", error=str(exc))


async def _load_pending_command_count() -> int:
    try:
        queue = require_runtime_command_queue()
        stats = await queue.get_stats()
    except Exception:
        return 0
    return int(stats.get("pending_count", 0) or 0)


async def _begin_runtime_drain(*, timeout_seconds: float) -> None:
    processor = _get_runtime_command_processor()
    if processor is None:
        return
    processor.begin_draining()
    try:
        await processor.wait_until_idle(timeout_seconds=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("Runtime drain timed out", timeout_seconds=timeout_seconds)


def _get_runtime_command_processor():
    try:
        container = get_container()
        context = container.runtime_bootstrap_context()
    except Exception:
        return None
    if context is None or type(context).__name__ == "object":
        return None
    return getattr(context.runtime_commands, "runtime_command_processor", None)


def main() -> None:
    """Run the runtime worker entrypoint."""
    asyncio.run(run_runtime_worker())


__all__ = ["main", "run_runtime_worker"]
