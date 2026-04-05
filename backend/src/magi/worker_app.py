"""IPC worker entry point — runs agent runtime with IPC server, no HTTP.

Used by Tauri desktop host when the management plane runs in Rust.
Python only handles IPC commands and the agent runtime.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid

from .core.container import wire_container
from .core.logger import configure_logging, get_logger
from .bootstrap import initialize_agent_runtime, shutdown_agent_runtime
from .process_roles import ProcessRole
from .utils.runtime import get_runtime_paths

logger = get_logger(__name__, category="WORKER")


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
    await initialize_agent_runtime(role=ProcessRole.UNIFIED)
    logger.info("Agent runtime initialized")

    # Build FastAPI app for IPC api.forward dispatch (no HTTP server)
    from .websocket.http_app import create_transport_app
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from fastapi import FastAPI

    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield

    app = create_transport_app(lifespan=_noop_lifespan)
    app.state.backend_ready = True
    app.state.process_role = ProcessRole.UNIFIED.value

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
    from .backend_runtime_worker import (
        _heartbeat_loop,
        _publish_runtime_heartbeat,
        _begin_runtime_drain,
        DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS,
    )

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

    def _signal_handler() -> None:
        shutdown_event.set()

    loop = asyncio.get_running_loop()
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
