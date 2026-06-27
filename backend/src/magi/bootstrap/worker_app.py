"""IPC worker entry point for the Python runtime sidecar.

Used by the Tauri desktop host when the management plane runs in Rust.
Python only handles IPC commands and the agent runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from pathlib import Path
import signal
import sys
import time
import uuid

from fastapi import FastAPI

from ..core.container import get_container, wire_container
from ..core.logger import configure_logging, get_logger
from ..core.runtime_bindings import require_runtime_command_queue
from ..runtime_trace import RuntimeHeartbeatRecord
from ..runtime_trace.provider import resolve_runtime_trace_store
from ..utils.runtime import get_runtime_paths
from .backend import initialize_agent_runtime, shutdown_agent_runtime
from .runtime_startup_state import get_runtime_startup_snapshot

logger = get_logger(__name__, category="WORKER")

DEFAULT_RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 2.0
DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS = 5.0
RUNTIME_HEARTBEAT_ROLE = "ipc_worker"


def configure_worker_logging() -> Path:
    """Configure file-backed logging for the IPC worker."""
    runtime_paths = get_runtime_paths()
    log_file = runtime_paths.logs_dir / "magi.log"
    configure_logging(
        level="INFO",
        log_file=str(log_file),
        json_logs=False,
    )
    return log_file


async def _run_worker() -> None:
    """Main async worker loop."""
    worker_t0 = time.monotonic()
    runtime_paths = get_runtime_paths()
    configure_worker_logging()

    logger.info("IPC worker starting")

    t0 = time.monotonic()
    wire_container()
    logger.info("DI container wired", elapsed_ms=round((time.monotonic() - t0) * 1000, 1))

    t0 = time.monotonic()
    await initialize_agent_runtime()
    logger.info("Agent runtime initialized", elapsed_ms=round((time.monotonic() - t0) * 1000, 1))

    from ..transport.http_app import create_transport_app

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield

    app = create_transport_app(lifespan=_noop_lifespan)

    ipc_server = None
    ipc_socket = os.environ.get("MAGI_IPC_SOCKET")
    if ipc_socket:
        from ..ipc import IpcServer

        t0 = time.monotonic()
        ipc_server = IpcServer(asgi_app=app)
        await ipc_server.start()
        logger.info(
            "IPC server started on %s",
            ipc_socket,
            elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
        )
    else:
        logger.warning("MAGI_IPC_SOCKET not set — worker has no IPC transport")

    instance_id = uuid.uuid4().hex
    started_at_ms = int(time.time() * 1000)
    heartbeat_stop = asyncio.Event()
    startup_snapshot = get_runtime_startup_snapshot()

    await _publish_runtime_heartbeat(
        instance_id=instance_id,
        started_at_ms=started_at_ms,
        status=startup_snapshot.startup_state,
        last_error=startup_snapshot.reason or startup_snapshot.detail,
    )
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            stop_event=heartbeat_stop,
            instance_id=instance_id,
            started_at_ms=started_at_ms,
        )
    )

    health_file = runtime_paths.base_dir / "runtime" / "worker.ready"
    health_file.parent.mkdir(parents=True, exist_ok=True)
    health_file.write_text(str(os.getpid()))
    total_ms = round((time.monotonic() - worker_t0) * 1000, 1)
    logger.info(
        "IPC worker ready (pid=%d, startup_ms=%.1f, startup_state=%s)",
        os.getpid(),
        total_ms,
        startup_snapshot.startup_state,
    )

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

    await _begin_runtime_drain(timeout_seconds=DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS)
    shutdown_snapshot = get_runtime_startup_snapshot()
    await _publish_runtime_heartbeat(
        instance_id=instance_id,
        started_at_ms=started_at_ms,
        status=shutdown_snapshot.startup_state,
        last_error=shutdown_snapshot.reason or shutdown_snapshot.detail,
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

    try:
        health_file.unlink(missing_ok=True)
    except Exception:
        pass

    logger.info("IPC worker stopped")


def main() -> None:
    """Entry point for IPC worker process."""
    asyncio.run(_run_worker())


async def _heartbeat_loop(
    *,
    stop_event: asyncio.Event,
    instance_id: str,
    started_at_ms: int,
    interval_seconds: float = DEFAULT_RUNTIME_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    previous_tick_started: float | None = None
    while not stop_event.is_set():
        tick_started = time.monotonic()
        if previous_tick_started is not None:
            tick_delay = tick_started - previous_tick_started
            if tick_delay > max(interval_seconds * 2, 5.0):
                logger.warning(
                    "Runtime heartbeat loop delayed",
                    instance_id=instance_id,
                    interval_ms=round(interval_seconds * 1000, 1),
                    delay_ms=round(tick_delay * 1000, 1),
                )
        previous_tick_started = tick_started
        snapshot = get_runtime_startup_snapshot()
        publish_started = time.monotonic()
        await _publish_runtime_heartbeat(
            instance_id=instance_id,
            started_at_ms=started_at_ms,
            status=snapshot.startup_state,
            last_error=snapshot.reason or snapshot.detail,
        )
        publish_elapsed = time.monotonic() - publish_started
        if publish_elapsed > max(interval_seconds * 2, 5.0):
            logger.warning(
                "Runtime heartbeat publish slow",
                instance_id=instance_id,
                elapsed_ms=round(publish_elapsed * 1000, 1),
                status=snapshot.startup_state,
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
        store = resolve_runtime_trace_store()
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
