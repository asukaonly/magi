"""Focused tests for transactional worker startup and foreground cancellation."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from magi.agent.execution.task_budget import task_execution_budget_scope
from magi.agent.workers.worker_launch import WorkerLaunchMixin
from magi.agent.workers.worker_manager import WorkerAgentManager
from magi.agent.workers.worker_state import WorkerRunState
from magi.agent.workers.worker_status import WorkerStatusMixin
from magi.tools.schema import ToolExecutionContext, ToolResult


class _WorkerLaunchHost(WorkerLaunchMixin, WorkerStatusMixin):
    def __init__(self) -> None:
        self._llm_adapter = object()
        self._lock = asyncio.Lock()
        self._runs: dict[str, WorkerRunState] = {}
        self._pending_runs: dict[str, WorkerRunState] = {}
        self._cancelled_run_keys: dict[tuple[str, str, int], float] = {}
        self.trace_events: list[str] = []
        self.seen_states: list[WorkerRunState] = []
        self.run_started_ids: list[str] = []
        self.run_started = asyncio.Event()
        self.release_run = asyncio.Event()
        self.terminalized = asyncio.Event()
        self.terminalized_ids: list[str] = []
        self.terminalized_while_registered: list[str] = []
        self.cancelled_trace_ids: list[str] = []
        self.cancelled_worker_span_ids: list[str] = []
        self.cancelled_attempt_span_ids: list[str] = []
        self.cancelled_fact_ids: list[str] = []
        self.fail_trace_name: str | None = None
        self.fail_started_trace_number: int | None = None
        self.pause_started_trace_number: int | None = None
        self.started_trace_count = 0
        self.started_trace_paused = asyncio.Event()
        self.release_started_trace = asyncio.Event()
        self.fail_registration = False
        self.fail_terminalization = False

    async def cancel_run_workers(self, **kwargs: Any) -> list[str]:
        return await WorkerAgentManager.cancel_run_workers(self, **kwargs)  # type: ignore[arg-type]

    def _normalize_subagent_type(self, subagent_type: str) -> str:
        return "CodeExplore" if subagent_type == "CodeExplore" else ""

    def _resolve_tools_for_type(self, subagent_type: str) -> list[str]:
        return []

    def _build_worker_system_prompt(
        self,
        *,
        worker_id: str,
        subagent_type: str,
        description: str,
        selected_tools: list[str],
        execution_workspace: str,
    ) -> str:
        return f"{worker_id}:{description}"

    async def _run_worker(
        self,
        run_state: WorkerRunState,
        worker_system_prompt: str,
        selected_tools: list[str],
        max_iterations: int,
        execution_workspace: str,
    ) -> None:
        self.run_started_ids.append(run_state.worker_id)
        self.run_started.set()
        try:
            await self.release_run.wait()
        except asyncio.CancelledError:
            await self._handle_cancelled_error(run_state)
            return
        run_state.status = "completed"

    async def _handle_cancelled_error(self, run_state: WorkerRunState) -> None:
        run_state.status = "cancelled"
        run_state.error = "Worker cancelled"
        run_state.failure_reason = "CANCELLED"
        run_state.updated_at = time.time()
        run_state.completed_at = run_state.updated_at
        self.terminalized_ids.append(run_state.worker_id)
        if self._runs.get(run_state.worker_id) is run_state:
            self.terminalized_while_registered.append(run_state.worker_id)
        await self._emit_worker_cancelled_trace(run_state)
        self.cancelled_fact_ids.append(run_state.worker_id)
        self.terminalized.set()

    async def _emit_worker_cancelled_trace(self, run_state: WorkerRunState) -> None:
        await self._emit_worker_terminal_trace(run_state, "cancelled")
        await self._emit_worker_attempt_terminal_trace(run_state, "cancelled")

    async def _emit_worker_terminal_trace(
        self,
        run_state: WorkerRunState,
        status: str,
    ) -> None:
        assert status == "cancelled"
        self.cancelled_worker_span_ids.append(run_state.worker_id)
        self._record_terminalized_trace(run_state)
        if self.fail_terminalization:
            raise RuntimeError("terminal lifecycle failed")

    async def _emit_worker_attempt_terminal_trace(
        self,
        run_state: WorkerRunState,
        status: str,
    ) -> None:
        assert status == "cancelled"
        self.cancelled_attempt_span_ids.append(run_state.worker_id)
        self._record_terminalized_trace(run_state)

    def _record_terminalized_trace(self, run_state: WorkerRunState) -> None:
        if run_state.worker_id not in self.cancelled_trace_ids:
            self.cancelled_trace_ids.append(run_state.worker_id)
        if run_state.worker_id not in self.terminalized_ids:
            self.terminalized_ids.append(run_state.worker_id)
        if (
            self._runs.get(run_state.worker_id) is run_state
            and run_state.worker_id not in self.terminalized_while_registered
        ):
            self.terminalized_while_registered.append(run_state.worker_id)
        self.terminalized.set()

    def _trim_history(self, max_runs: int) -> None:
        if self._runs:
            self.seen_states.append(next(reversed(self._runs.values())))
        if self.fail_registration:
            raise RuntimeError("registration failed")

    def _build_run_result(self, run_state: WorkerRunState) -> ToolResult:
        return ToolResult(
            success=run_state.status == "completed",
            data={"worker_id": run_state.worker_id, "status": run_state.status},
        )

    def _serialize_run_state(self, run_state: WorkerRunState) -> dict[str, Any]:
        return {"worker_id": run_state.worker_id, "status": run_state.status}

    async def _emit_worker_dispatch_trace(self, run_state: WorkerRunState) -> None:
        self.seen_states.append(run_state)
        await self._record_trace("dispatch")

    async def _emit_worker_attempt_started_trace(self, run_state: WorkerRunState) -> None:
        await self._record_trace("attempt")

    async def _emit_worker_started_trace(self, run_state: WorkerRunState) -> None:
        self.started_trace_count += 1
        await self._record_trace("started")
        if self.pause_started_trace_number == self.started_trace_count:
            self.started_trace_paused.set()
            await self.release_started_trace.wait()
        if self.fail_started_trace_number == self.started_trace_count:
            raise RuntimeError("started trace failed")

    async def _record_trace(self, name: str) -> None:
        self.trace_events.append(name)
        await asyncio.sleep(0)
        if self.fail_trace_name == name:
            raise RuntimeError(f"{name} trace failed")


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="chat:test-user",
        workspace=".",
        env_vars={"user_id": "test-user", "session_id": "test-session"},
    )


def _parameters(*, description: str = "inspect code") -> dict[str, Any]:
    return {
        "subagent_type": "CodeExplore",
        "description": description,
        "prompt": f"Prompt for {description}",
    }


@pytest.mark.asyncio
async def test_worker_body_starts_only_after_registration_and_start_traces() -> None:
    host = _WorkerLaunchHost()

    run_state = await host._start_worker(_parameters(), _context())

    assert isinstance(run_state, WorkerRunState)
    assert host._runs[run_state.worker_id] is run_state
    assert host.trace_events == ["dispatch", "attempt", "started"]
    assert host.run_started_ids == []

    await asyncio.wait_for(host.run_started.wait(), timeout=1)
    host.release_run.set()
    assert run_state.task is not None
    await run_state.task


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["registration", "trace"])
async def test_worker_start_failure_unregisters_without_running_body(failure: str) -> None:
    host = _WorkerLaunchHost()
    host.fail_registration = failure == "registration"
    host.fail_trace_name = "attempt" if failure == "trace" else None

    with pytest.raises(RuntimeError):
        await host._start_worker(_parameters(), _context())

    assert host._runs == {}
    assert host.run_started_ids == []
    assert host.seen_states
    run_state = host.seen_states[0]
    if failure == "registration":
        assert run_state.task is not None
        assert run_state.task.done()
    else:
        assert run_state.task is None
    assert run_state.cancel_token is not None
    assert await run_state.cancel_token.is_cancelled() is True
    assert run_state.status == "cancelled"
    assert run_state.completed_at is not None
    assert run_state.startup_committed is False
    assert host.cancelled_fact_ids == []
    assert run_state.worker_id in host.terminalized_ids
    assert run_state.worker_id in host.cancelled_trace_ids
    assert host.terminalized_while_registered == []


@pytest.mark.asyncio
async def test_batch_trace_failure_rolls_back_all_workers_before_body_runs() -> None:
    host = _WorkerLaunchHost()
    host.fail_started_trace_number = 2

    with pytest.raises(RuntimeError, match="started trace failed"):
        await host._launch_workers_batch(
            {
                "workers": [
                    _parameters(description="first worker"),
                    _parameters(description="second worker"),
                ],
                "orchestration_id": "orchestration-staging-failure",
                "run_in_background": True,
            },
            _context(),
        )

    assert host._runs == {}
    assert host.run_started_ids == []
    unique_states = {state.worker_id: state for state in host.seen_states}.values()
    assert len(list(unique_states)) == 2
    for run_state in unique_states:
        assert run_state.cancel_token is not None
        assert await run_state.cancel_token.is_cancelled() is True
        if run_state.task is not None:
            assert run_state.task.done()
        assert run_state.startup_committed is False
        assert run_state.worker_id in host.terminalized_ids
        assert run_state.worker_id in host.cancelled_worker_span_ids
        assert run_state.worker_id in host.cancelled_attempt_span_ids
    assert host.terminalized_while_registered == []
    assert host.cancelled_fact_ids == []


@pytest.mark.asyncio
async def test_batch_trace_rollback_does_not_consume_worker_budget() -> None:
    host = _WorkerLaunchHost()
    host.fail_started_trace_number = 2

    async with task_execution_budget_scope(max_worker_launches=2) as budget:
        with pytest.raises(RuntimeError, match="started trace failed"):
            await host._launch_workers_batch(
                {
                    "workers": [
                        _parameters(description="first worker"),
                        _parameters(description="second worker"),
                    ],
                    "run_in_background": True,
                },
                _context(),
            )

    assert budget.worker_launches == 0
    assert host._runs == {}
    assert host._pending_runs == {}


@pytest.mark.asyncio
async def test_batch_staging_is_private_and_cannot_publish_cancellation_fact() -> None:
    host = _WorkerLaunchHost()
    host.pause_started_trace_number = 2
    host.fail_started_trace_number = 2
    launch_task = asyncio.create_task(
        host._launch_workers_batch(
            {
                "workers": [
                    _parameters(description="first worker"),
                    _parameters(description="second worker"),
                ],
                "run_in_background": True,
            },
            _context(),
        )
    )

    await asyncio.wait_for(host.started_trace_paused.wait(), timeout=1)
    assert host._runs == {}
    assert len(host._pending_runs) == 2
    staged_states = list({state.worker_id: state for state in host.seen_states}.values())
    assert len(staged_states) == 2
    first_state = staged_states[0]
    assert first_state.task is not None
    first_state.task.cancel()
    await asyncio.gather(first_state.task, return_exceptions=True)

    assert first_state.status == "cancelled"
    assert first_state.startup_committed is False
    assert host.cancelled_fact_ids == []

    host.release_started_trace.set()
    with pytest.raises(RuntimeError, match="started trace failed"):
        await launch_task

    assert host._runs == {}
    assert host._pending_runs == {}
    assert host.cancelled_fact_ids == []


@pytest.mark.asyncio
async def test_run_cancellation_includes_private_single_worker_start() -> None:
    host = _WorkerLaunchHost()
    host.pause_started_trace_number = 1
    launch_task = asyncio.create_task(
        host._start_worker(
            {**_parameters(), "run_id": "run-1", "run_revision": 3},
            _context(),
        )
    )

    await asyncio.wait_for(host.started_trace_paused.wait(), timeout=1)
    assert host._runs == {}
    assert len(host._pending_runs) == 1

    cancelled_ids = await host.cancel_run_workers(
        session_id="test-session",
        run_id="run-1",
        run_revision=3,
        reason="test_run_cancelled",
    )
    assert len(cancelled_ids) == 1
    host.release_started_trace.set()

    result = await launch_task

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert result.data == {"reason": "run_cancelled_before_worker_start"}
    assert host._runs == {}
    assert host._pending_runs == {}
    assert host.run_started_ids == []
    assert host.cancelled_fact_ids == []


@pytest.mark.asyncio
async def test_run_cancellation_tombstone_rejects_late_worker_start() -> None:
    host = _WorkerLaunchHost()

    cancelled_ids = await host.cancel_run_workers(
        session_id="test-session",
        run_id="run-late",
        run_revision=4,
        reason="test_run_cancelled",
    )
    assert cancelled_ids == []

    result = await host._start_worker(
        {**_parameters(), "run_id": "run-late", "run_revision": 4},
        _context(),
    )

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert result.data == {"reason": "run_cancelled_before_worker_start"}
    assert host._runs == {}
    assert host._pending_runs == {}
    assert host.trace_events == []
    assert host.run_started_ids == []
    assert host.cancelled_fact_ids == []


@pytest.mark.asyncio
async def test_start_error_is_not_masked_when_terminal_lifecycle_fails() -> None:
    host = _WorkerLaunchHost()
    host.fail_trace_name = "attempt"
    host.fail_terminalization = True

    with pytest.raises(RuntimeError, match="attempt trace failed"):
        await host._start_worker(_parameters(), _context())

    assert host._runs == {}
    assert host.terminalized_ids
    run_state = host.seen_states[0]
    assert run_state.worker_id in host.cancelled_attempt_span_ids


@pytest.mark.asyncio
async def test_cancel_before_gated_task_first_runs_still_terminalizes() -> None:
    host = _WorkerLaunchHost()
    run_state = await host._start_worker(
        _parameters(),
        _context(),
        start_gate=asyncio.Event(),
    )
    assert isinstance(run_state, WorkerRunState)
    assert run_state.task is not None

    run_state.task.cancel()
    await asyncio.gather(run_state.task, return_exceptions=True)
    await asyncio.wait_for(host.terminalized.wait(), timeout=1)

    assert run_state.status == "cancelled"
    assert run_state.completed_at is not None
    assert run_state.worker_id in host.cancelled_trace_ids
    assert run_state.worker_id in host.cancelled_fact_ids


@pytest.mark.asyncio
async def test_serial_batch_starts_next_worker_only_after_previous_finishes() -> None:
    host = _WorkerLaunchHost()
    launch_task = asyncio.create_task(
        host._launch_workers_batch(
            {
                "workers": [
                    _parameters(description="first worker"),
                    _parameters(description="second worker"),
                ],
                "parallel": False,
            },
            _context(),
        )
    )
    await asyncio.wait_for(host.run_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert len(host._runs) == 2
    assert len(host.run_started_ids) == 1

    host.release_run.set()
    result = await launch_task

    assert result.success is True
    assert len(host.run_started_ids) == 2


@pytest.mark.asyncio
async def test_serial_batch_cancellation_terminalizes_later_gated_worker() -> None:
    host = _WorkerLaunchHost()
    launch_task = asyncio.create_task(
        host._launch_workers_batch(
            {
                "workers": [
                    _parameters(description="first worker"),
                    _parameters(description="second worker"),
                ],
                "parallel": False,
            },
            _context(),
        )
    )
    await asyncio.wait_for(host.run_started.wait(), timeout=1)
    run_states = list(host._runs.values())
    assert len(run_states) == 2
    assert host.run_started_ids == [run_states[0].worker_id]

    launch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await launch_task

    assert host.run_started_ids == [run_states[0].worker_id]
    assert set(host.terminalized_ids) == {state.worker_id for state in run_states}
    for run_state in run_states:
        assert run_state.status == "cancelled"
        assert run_state.completed_at is not None
        assert run_state.task is not None
        assert run_state.task.done()


@pytest.mark.asyncio
async def test_foreground_cancellation_stops_worker_before_propagating() -> None:
    host = _WorkerLaunchHost()
    launch_task = asyncio.create_task(host._launch_worker(_parameters(), _context()))
    await asyncio.wait_for(host.run_started.wait(), timeout=1)
    run_state = next(iter(host._runs.values()))

    launch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await launch_task

    assert run_state.task is not None
    assert run_state.task.done()
    assert run_state.status == "cancelled"
    assert run_state.cancel_token is not None
    assert run_state.cancel_token.reason == "foreground_worker_wait_cancelled"


@pytest.mark.asyncio
async def test_background_launch_keeps_worker_running_after_return() -> None:
    host = _WorkerLaunchHost()
    result = await host._launch_worker(
        {**_parameters(), "run_in_background": True},
        _context(),
    )
    await asyncio.wait_for(host.run_started.wait(), timeout=1)
    run_state = next(iter(host._runs.values()))

    assert result.success is True
    assert run_state.task is not None
    assert not run_state.task.done()

    host.release_run.set()
    await run_state.task


@pytest.mark.asyncio
async def test_refresh_cancelled_task_does_not_raise_cancelled_error() -> None:
    host = _WorkerLaunchHost()
    run_state = await host._start_worker(
        _parameters(),
        _context(),
        start_gate=asyncio.Event(),
    )
    assert isinstance(run_state, WorkerRunState)
    assert run_state.task is not None
    run_state.task.cancel()
    await asyncio.gather(run_state.task, return_exceptions=True)
    await asyncio.wait_for(host.terminalized.wait(), timeout=1)

    run_state.status = "running"
    run_state.error = None
    run_state.failure_reason = None
    run_state.completed_at = None
    await host._refresh_run_state(run_state)

    assert run_state.status == "cancelled"
    assert run_state.failure_reason == "CANCELLED"
    assert run_state.completed_at is not None


@pytest.mark.asyncio
async def test_refreshing_full_tombstone_cache_keeps_recent_run_cancelled() -> None:
    host = _WorkerLaunchHost()
    refreshed_key = ("session-refreshed", "run-refreshed", 1)
    host._cancelled_run_keys[refreshed_key] = 1.0
    for index in range(1, 1024):
        host._cancelled_run_keys[(f"session-{index}", f"run-{index}", index)] = float(index + 1)

    await host.cancel_run_workers(
        session_id=refreshed_key[0],
        run_id=refreshed_key[1],
        run_revision=refreshed_key[2],
    )
    await host.cancel_run_workers(
        session_id="session-new",
        run_id="run-new",
        run_revision=1025,
    )

    assert len(host._cancelled_run_keys) == 1024
    assert refreshed_key in host._cancelled_run_keys
    assert ("session-1", "run-1", 1) not in host._cancelled_run_keys
    assert ("session-new", "run-new", 1025) in host._cancelled_run_keys
