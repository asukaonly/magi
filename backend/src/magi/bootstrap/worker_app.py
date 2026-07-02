"""IPC worker entry point for the Python runtime sidecar.

Used by the Tauri desktop host when the management plane runs in Rust.
Python only handles IPC commands and the agent runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any

from fastapi import FastAPI

from ..core.container import get_container, wire_container
from ..core.logger import configure_logging, get_logger
from ..utils.runtime import get_runtime_paths
from .backend import initialize_agent_runtime, shutdown_agent_runtime
from .runtime_startup_state import get_runtime_startup_snapshot

logger = get_logger(__name__, category="WORKER")

DEFAULT_RUNTIME_MONITOR_INTERVAL_SECONDS = 2.0
DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class RuntimeMonitorHandle:
    """Runtime monitor task state owned by the IPC worker."""

    stop_event: asyncio.Event
    task: asyncio.Task[None]
    startup_state: str


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


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


async def _run_worker() -> None:
    """Main async worker loop."""
    worker_t0 = time.monotonic()
    runtime_paths = get_runtime_paths()
    configure_worker_logging()
    logger.info("IPC worker starting")

    app = await _initialize_worker_transport_app()
    ipc_server = await _start_ipc_server(app)
    runtime_monitor = _start_runtime_monitor()
    health_file = _write_worker_ready_file(runtime_paths)
    _log_worker_ready(worker_t0, runtime_monitor.startup_state)

    shutdown_event = _install_shutdown_signal_handlers()
    await shutdown_event.wait()
    await _shutdown_worker(
        ipc_server=ipc_server,
        runtime_monitor=runtime_monitor,
        health_file=health_file,
    )


async def _initialize_worker_transport_app() -> FastAPI:
    t0 = time.monotonic()
    wire_container()
    logger.info("DI container wired", elapsed_ms=round((time.monotonic() - t0) * 1000, 1))

    t0 = time.monotonic()
    await initialize_agent_runtime()
    logger.info("Agent runtime initialized", elapsed_ms=round((time.monotonic() - t0) * 1000, 1))

    from ..transport.http_app import create_transport_app

    return create_transport_app(lifespan=_noop_lifespan)


async def _start_ipc_server(app: FastAPI) -> Any | None:
    ipc_socket = os.environ.get("MAGI_IPC_SOCKET")
    if not ipc_socket:
        logger.warning("MAGI_IPC_SOCKET not set — worker has no IPC transport")
        return None

    from ..ipc import IpcServer

    t0 = time.monotonic()
    ipc_server = IpcServer(asgi_app=app)
    await ipc_server.start()
    logger.info(
        "IPC server started on %s",
        ipc_socket,
        elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
    )
    return ipc_server


def _start_runtime_monitor() -> RuntimeMonitorHandle:
    monitor_stop = asyncio.Event()
    startup_snapshot = get_runtime_startup_snapshot()
    monitor_task = asyncio.create_task(
        _event_loop_monitor_loop(
            stop_event=monitor_stop,
        )
    )
    return RuntimeMonitorHandle(
        stop_event=monitor_stop,
        task=monitor_task,
        startup_state=startup_snapshot.startup_state,
    )


def _write_worker_ready_file(runtime_paths: Any) -> Path:
    health_file = runtime_paths.base_dir / "runtime" / "worker.ready"
    health_file.parent.mkdir(parents=True, exist_ok=True)
    health_file.write_text(str(os.getpid()))
    return health_file


def _log_worker_ready(worker_t0: float, startup_state: str) -> None:
    total_ms = round((time.monotonic() - worker_t0) * 1000, 1)
    logger.info(
        "IPC worker ready (pid=%d, startup_ms=%.1f, startup_state=%s)",
        os.getpid(),
        total_ms,
        startup_state,
    )


def _install_shutdown_signal_handlers() -> asyncio.Event:
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
    return shutdown_event


async def _shutdown_worker(
    *,
    ipc_server: Any | None,
    runtime_monitor: RuntimeMonitorHandle,
    health_file: Path,
) -> None:
    logger.info("IPC worker shutting down")

    await _begin_runtime_drain(timeout_seconds=DEFAULT_RUNTIME_DRAIN_TIMEOUT_SECONDS)
    await _stop_runtime_monitor(runtime_monitor)

    if ipc_server is not None:
        await ipc_server.stop()

    await shutdown_agent_runtime()

    try:
        health_file.unlink(missing_ok=True)
    except Exception:
        pass

    logger.info("IPC worker stopped")


async def _stop_runtime_monitor(runtime_monitor: RuntimeMonitorHandle) -> None:
    runtime_monitor.stop_event.set()
    runtime_monitor.task.cancel()
    try:
        await runtime_monitor.task
    except asyncio.CancelledError:
        pass


def main() -> None:
    """Entry point for IPC worker process."""
    asyncio.run(_run_worker())


async def _event_loop_monitor_loop(
    *,
    stop_event: asyncio.Event,
    interval_seconds: float = DEFAULT_RUNTIME_MONITOR_INTERVAL_SECONDS,
) -> None:
    previous_tick_started: float | None = None
    while not stop_event.is_set():
        tick_started = time.monotonic()
        if previous_tick_started is not None:
            tick_delay = tick_started - previous_tick_started
            if tick_delay > max(interval_seconds * 2, 5.0):
                logger.warning(
                    "Runtime event loop delayed",
                    interval_ms=round(interval_seconds * 1000, 1),
                    delay_ms=round(tick_delay * 1000, 1),
                )
        previous_tick_started = tick_started
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue


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
