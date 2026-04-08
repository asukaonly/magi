"""IPC worker entry point — runs agent runtime with IPC server, no HTTP.

Used by Tauri desktop host when the management plane runs in Rust.
Python only handles IPC commands and the agent runtime.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import uuid

from .core.container import get_container, wire_container
from .core.logger import configure_logging, get_logger
from .core.runtime_bindings import require_runtime_command_queue, require_runtime_trace_store
from .bootstrap import initialize_agent_runtime, shutdown_agent_runtime
from .runtime_trace import RuntimeHeartbeatRecord
from .utils.runtime import get_runtime_paths

logger = get_logger(__name__, category="WORKER")

DEFAULT_RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 2.0
DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS = 5.0
RUNTIME_HEARTBEAT_ROLE = "ipc_worker"


async def _run_worker() -> None:
    """Main async worker loop."""
    runtime_paths = get_runtime_paths()
    log_file = runtime_paths.logs_dir / "magi.log"
    configure_logging(str(log_file))

    logger.info("IPC worker starting")

    # Wire DI container
    wire_container()
    logger.info("DI container wired")

    # Initialize agent runtime
    await initialize_agent_runtime()
    logger.info("Agent runtime initialized")

    # Build FastAPI app for IPC api.forward dispatch (no HTTP server)
    from .transport.http_app import create_transport_app
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from fastapi import FastAPI

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield

    app = create_transport_app(lifespan=_noop_lifespan)

    # Start IPC server
    ipc_server = None
    ipc_socket = os.environ.get("MAGI_IPC_SOCKET")
    if ipc_socket:
        from .ipc import IpcServer
        ipc_server = IpcServer(asgi_app=app)
        await ipc_server.start()
        logger.info("IPC server started on %s", ipc_socket)
    else:
        logger.warning("MAGI_IPC_SOCKET not set — worker has no IPC transport")

    # Heartbeat
    instance_id = uuid.uuid4().hex
    started_at_ms = int(time.time() * 1000)
    heartbeat_status = {"value": "ready"}
    heartbeat_stop = asyncio.Event()

    await _publish_runtime_heartbeat(
        instance_id=instance_id,
        started_at_ms=started_at_ms,
        status="ready",
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            stop_event=heartbeat_stop,
            instance_id=instance_id,
            started_at_ms=started_at_ms,
            status_ref=heartbeat_status,
        )
    )

    # Signal readiness via health file (Tauri can check this)
    health_file = runtime_paths.base_dir / "runtime" / "worker.ready"
    health_file.parent.mkdir(parents=True, exist_ok=True)
    health_file.write_text(str(os.getpid()))
    logger.info("IPC worker ready (pid=%d)", os.getpid())

    # Wait for shutdown signal
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    if sys.platform == "win32":
        def _signal_handler(signum, frame):
            loop.call_soon_threadsafe(shutdown_event.set)

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    else:
        def _signal_handler() -> None:
            shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

    await shutdown_event.wait()
    logger.info("IPC worker shutting down")

    # Cleanup
    heartbeat_status["value"] = "draining"
    await _begin_runtime_drain(timeout_seconds=DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS)
    await _publish_runtime_heartbeat(
        instance_id=instance_id,
        started_at_ms=started_at_ms,
        status="stopping",
    )
    heartbeat_stop.set()
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    if ipc_server is not None:
        await ipc_server.stop()

    await shutdown_agent_runtime()

    # Remove health file
    try:
        health_file.unlink(missing_ok=True)
    except Exception:
        pass

    logger.info("IPC worker stopped")


def main() -> None:
    """Entry point for IPC worker process."""
    asyncio.run(_run_worker())


# ---------------------------------------------------------------------------
# Heartbeat / drain helpers
# ---------------------------------------------------------------------------

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
        if not getattr(_publish_runtime_heartbeat, "_warned", False):
            logger.warning("Failed to publish runtime heartbeat", error=str(exc))
            _publish_runtime_heartbeat._warned = True


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
