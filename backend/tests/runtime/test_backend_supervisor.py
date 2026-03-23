from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from magi.runtime_trace import RuntimeHeartbeatRecord, RuntimeTraceStore


@pytest.mark.asyncio
async def test_wait_for_runtime_worker_ready_returns_after_heartbeat(tmp_path: Path) -> None:
    from magi.backend_supervisor import wait_for_runtime_worker_ready

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    async def _emit_heartbeat() -> None:
        await asyncio.sleep(0.05)
        await store.upsert_runtime_heartbeat(
            RuntimeHeartbeatRecord(
                role="runtime_worker",
                instance_id="worker-1",
                pid=123,
                started_at_ms=100,
                last_seen_at_ms=999_999_999_999,
                status="ready",
            )
        )

    task = asyncio.create_task(_emit_heartbeat())
    try:
        await wait_for_runtime_worker_ready(
            runtime_trace_db_path=str(db_path),
            timeout_seconds=1.0,
            poll_interval_seconds=0.01,
        )
    finally:
        await task
        await store.shutdown()


@pytest.mark.asyncio
async def test_run_dual_process_supervisor_stops_api_when_runtime_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.backend_supervisor import run_dual_process_supervisor

    class _FakeProcess:
        def __init__(self, name: str) -> None:
            self.name = name
            self.returncode: int | None = None
            self.terminated = False
            self.killed = False
            self._wait_future: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        async def wait(self) -> int:
            return await self._wait_future

        def terminate(self) -> None:
            self.terminated = True
            if not self._wait_future.done():
                self.returncode = -15
                self._wait_future.set_result(-15)

        def kill(self) -> None:
            self.killed = True
            if not self._wait_future.done():
                self.returncode = -9
                self._wait_future.set_result(-9)

    started_roles: list[str] = []
    readiness_checks: list[str] = []
    runtime_process = _FakeProcess("runtime_worker")
    api_process = _FakeProcess("api")

    async def _fake_create_subprocess_exec(*cmd, cwd=None, env=None):  # type: ignore[no-untyped-def]
        _ = (cwd, env)
        role = cmd[-1]
        started_roles.append(role)
        if role == "runtime_worker":
            return runtime_process
        if role == "api":
            return api_process
        raise AssertionError(f"Unexpected role: {role}")

    async def _fake_wait_for_runtime(*args, **kwargs):  # type: ignore[no-untyped-def]
        readiness_checks.append("runtime")
        return None

    async def _fake_wait_for_api(*args, **kwargs):  # type: ignore[no-untyped-def]
        readiness_checks.append("api")
        return None

    monkeypatch.setattr("magi.backend_supervisor.asyncio.create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr("magi.backend_supervisor.wait_for_runtime_worker_ready", _fake_wait_for_runtime)
    monkeypatch.setattr("magi.backend_supervisor.wait_for_api_ready", _fake_wait_for_api)
    monkeypatch.setattr("magi.backend_supervisor._install_signal_handlers", lambda stop_event: None)

    supervisor_task = asyncio.create_task(
        run_dual_process_supervisor(
            backend_dir="/tmp/magi-backend",
            runtime_trace_db_path="/tmp/runtime_trace.db",
            api_ready_url="http://127.0.0.1:8000/api/ready",
            startup_timeout_seconds=1.0,
            shutdown_timeout_seconds=0.2,
        )
    )

    await asyncio.sleep(0)
    runtime_process.returncode = 1
    runtime_process._wait_future.set_result(1)

    exit_code = await supervisor_task

    assert started_roles == ["runtime_worker", "api"]
    assert readiness_checks == ["runtime", "api"]
    assert api_process.terminated is True
    assert exit_code == 1


def test_resolve_api_port_prefers_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.backend_supervisor import _resolve_api_port

    monkeypatch.setenv("MAGI_API_PORT_OVERRIDE", "9321")

    assert _resolve_api_port() == 9321
