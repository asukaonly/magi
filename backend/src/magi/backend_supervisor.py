"""Supervisor for the dual-process backend topology."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import urllib.error
import urllib.request

from .config import get_config
from .core.logger import get_logger
from .runtime_trace import RuntimeTraceStore
from .utils.runtime import get_runtime_paths

logger = get_logger(__name__)

DEFAULT_STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 5.0
DEFAULT_READINESS_POLL_INTERVAL_SECONDS = 0.25
API_PORT_OVERRIDE_ENV_VAR = "MAGI_API_PORT_OVERRIDE"


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install signal handlers that stop the supervisor."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            logger.warning("Signal handler registration is unavailable", signal=sig.name)


async def wait_for_runtime_worker_ready(
    *,
    runtime_trace_db_path: str,
    timeout_seconds: float,
    poll_interval_seconds: float = DEFAULT_READINESS_POLL_INTERVAL_SECONDS,
) -> None:
    """Wait until the runtime worker heartbeat reports a ready status."""
    store = RuntimeTraceStore(db_path=runtime_trace_db_path)
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while True:
        heartbeat = await store.get_runtime_heartbeat(role="runtime_worker")
        if heartbeat is not None and str(heartbeat.status or "").strip() == "ready":
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Timed out waiting for runtime worker heartbeat")
        await asyncio.sleep(poll_interval_seconds)


async def wait_for_api_ready(
    *,
    api_ready_url: str,
    timeout_seconds: float,
    poll_interval_seconds: float = DEFAULT_READINESS_POLL_INTERVAL_SECONDS,
) -> None:
    """Wait until the API process reports ready via the readiness endpoint."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while True:
        payload = await asyncio.to_thread(_load_ready_payload, api_ready_url)
        if bool(payload.get("data", {}).get("ready")):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Timed out waiting for API readiness")
        await asyncio.sleep(poll_interval_seconds)


async def run_dual_process_supervisor(
    *,
    backend_dir: str,
    runtime_trace_db_path: str,
    api_ready_url: str,
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    shutdown_timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    python_executable: str = sys.executable,
    child_env: dict[str, str] | None = None,
    api_port: int | None = None,
) -> int:
    """Run runtime worker and API as one supervised topology."""
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    env = dict(child_env or os.environ)

    runtime_process = await _start_backend_role(
        backend_dir=backend_dir,
        role="runtime_worker",
        python_executable=python_executable,
        env=env,
    )

    api_process = None
    stop_task = asyncio.create_task(stop_event.wait())
    runtime_wait_task = asyncio.create_task(runtime_process.wait())
    api_wait_task: asyncio.Task[int] | None = None

    try:
        await wait_for_runtime_worker_ready(
            runtime_trace_db_path=runtime_trace_db_path,
            timeout_seconds=startup_timeout_seconds,
        )

        api_process = await _start_backend_role(
            backend_dir=backend_dir,
            role="api",
            python_executable=python_executable,
            env=env,
            port=api_port,
        )
        await wait_for_api_ready(
            api_ready_url=api_ready_url,
            timeout_seconds=startup_timeout_seconds,
        )
        api_wait_task = asyncio.create_task(api_process.wait())

        wait_set: list[asyncio.Task[object]] = [stop_task, runtime_wait_task, api_wait_task]
        done, pending = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            if task is stop_task:
                task.cancel()

        if stop_task in done:
            return 0
        if runtime_wait_task in done:
            return int(runtime_process.returncode or 0)
        if api_wait_task in done:
            return int(api_process.returncode or 0)
        return 1
    finally:
        await _terminate_process(
            api_process,
            name="api",
            timeout_seconds=shutdown_timeout_seconds,
        )
        await _terminate_process(
            runtime_process,
            name="runtime_worker",
            timeout_seconds=shutdown_timeout_seconds,
        )
        stop_task.cancel()


async def _start_backend_role(
    *,
    backend_dir: str,
    role: str,
    python_executable: str,
    env: dict[str, str],
    port: int | None = None,
):
    logger.info("Starting backend role", role=role)
    command = [
        python_executable,
        "run_server.py",
        "--role",
        role,
    ]
    if port is not None and role == "api":
        command.extend(["--port", str(port)])
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=backend_dir,
        env=env,
    )


async def _terminate_process(process, *, name: str, timeout_seconds: float) -> None:
    if process is None or process.returncode is not None:
        return

    logger.info("Stopping supervised process", role=name)
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning("Process did not exit after TERM; forcing stop", role=name)
        process.kill()
        await process.wait()


def _load_ready_payload(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_api_port(env: dict[str, str] | None = None) -> int:
    override = str((env or os.environ).get(API_PORT_OVERRIDE_ENV_VAR, "")).strip()
    if override:
        try:
            return int(override)
        except ValueError:
            logger.warning("Ignoring invalid API port override", value=override)
    config = get_config()
    return int(config.server.port or 8000)


def _resolve_api_ready_url() -> str:
    config = get_config()
    host = str(config.server.host or "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    port = _resolve_api_port()
    return f"http://{host}:{port}/api/ready"


async def async_main() -> int:
    """Run the dual-process supervisor."""
    runtime_paths = get_runtime_paths()
    backend_dir = Path(__file__).resolve().parents[2]
    return await run_dual_process_supervisor(
        backend_dir=str(backend_dir),
        runtime_trace_db_path=str(runtime_paths.runtime_trace_db_path),
        api_ready_url=_resolve_api_ready_url(),
        api_port=_resolve_api_port(),
    )


def main() -> None:
    """Run the supervisor entrypoint."""
    raise SystemExit(asyncio.run(async_main()))


__all__ = [
    "async_main",
    "main",
    "run_dual_process_supervisor",
    "wait_for_api_ready",
    "wait_for_runtime_worker_ready",
]
