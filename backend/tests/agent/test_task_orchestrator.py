from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.agent.cancel import EventCancelToken
from magi.agent.runtime.contracts import FactRecord
import magi.agent.task_orchestrator as task_orchestrator_module
import magi.agent.task_orchestration_workers as task_orchestration_workers_module
from magi.agent.orchestration_plan import OrchestrationPlan
from magi.agent.task_orchestrator import TaskOrchestrator
from magi.agent.orchestration import SubtaskDefinition, TaskOrchestrationState
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolResult


async def _fake_plan_subtasks(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("plan_subtasks should not be called in this test")


async def _fake_aggregate(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("aggregate_orchestration should not be called in this test")


def _fake_register_user_message(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    _ = (args, kwargs)


class _FakeControlSessionStore:
    def __init__(self) -> None:
        self.replace_calls: list[tuple[str, list[dict[str, object]]]] = []

    async def replace_todos(self, session_id: str, items: list[dict[str, object]]):
        self.replace_calls.append((session_id, items))
        return []


@pytest.mark.asyncio
async def test_build_agent_tool_context_includes_workspace_and_agent_metadata() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    context = await orchestrator._build_agent_tool_context(
        "user-1",
        "session-1",
        user_message_generation=7,
    )

    assert context.agent_id == "explore:user-1"
    expected_workspace = Path(task_orchestrator_module.__file__).resolve().parents[4]
    assert context.workspace == str(expected_workspace)
    assert context.permissions == ["authenticated"]
    assert context.env_vars == {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_task_agent_type": "explore",
        "target_task_agent_id": "user-1",
        "parent_task_agent_type": "explore",
        "parent_task_agent_id": "user-1",
        "run_id": "",
        "run_revision": "0",
        "user_message_generation": "7",
    }


def test_orchestration_state_persists_user_message_generation() -> None:
    state = TaskOrchestrationState(
        orchestration_id="orch-generation",
        user_id="user-1",
        session_id="session-1",
        root_user_message="inspect repository",
        planner="task_agent",
        user_message_generation=7,
    )

    restored = TaskOrchestrationState.from_dict(state.to_dict())

    assert restored.user_message_generation == 7


@pytest.mark.asyncio
async def test_publish_session_todos_uses_injected_control_session_store() -> None:
    store = _FakeControlSessionStore()
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
        control_session_store_provider=lambda: store,
    )
    state = TaskOrchestrationState(
        orchestration_id="orch-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="do it",
        planner="task_agent",
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask-1",
                description="Inspect logs",
                subagent_type="CodeExplore",
                prompt="Inspect logs",
                status="running",
            ),
            SubtaskDefinition(
                subtask_id="subtask-2",
                description="Patch fix",
                subagent_type="CodeExplore",
                prompt="Patch fix",
                status="running",
            ),
        ],
    )

    await orchestrator._publish_session_todos(state)

    assert store.replace_calls == [
        (
            "session-1",
            [
                {
                    "id": "subtask-1",
                    "content": "Inspect logs",
                    "status": "in_progress",
                },
                {
                    "id": "subtask-2",
                    "content": "Patch fix",
                    "status": "not_started",
                },
            ],
        )
    ]


@pytest.mark.asyncio
async def test_chat_default_workspace_root_prefers_session_workspace() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
        session_workspace_provider=lambda **_: "/tmp/magi",
    )

    resolved = await orchestrator._default_workspace_root(user_id="user-1", session_id="session-1")

    assert resolved == "/tmp/magi"


@pytest.mark.asyncio
async def test_chat_default_workspace_root_returns_empty_when_session_workspace_missing() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    resolved = await orchestrator._default_workspace_root(user_id="user-1", session_id="session-1")

    assert resolved == ""


@pytest.mark.asyncio
async def test_explore_default_workspace_root_uses_runtime_project_root_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    unrelated_cwd = tmp_path / "outside"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    resolved = await orchestrator._default_workspace_root(user_id="user-1", session_id="session-1")

    assert resolved == str(Path(task_orchestrator_module.__file__).resolve().parents[4])
    assert resolved != str(unrelated_cwd.resolve())


@pytest.mark.asyncio
async def test_resolve_workspace_root_prefers_explicit_user_scope() -> None:
    expected_workspace_root = str(Path(task_orchestrator_module.__file__).resolve().parents[4])
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    resolved = await orchestrator._resolve_workspace_root(
        user_id="user-1",
        session_id="session-1",
        user_message=f"看下 {expected_workspace_root} 的代码，分析下代码架构",
    )

    assert resolved == expected_workspace_root


@pytest.mark.asyncio
async def test_resolve_workspace_root_supports_docs_relative_scope() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    resolved = await orchestrator._resolve_workspace_root(
        user_id="user-1",
        session_id="session-1",
        user_message="看下 docs/project-overview.md 的文档结构",
    )

    assert resolved.endswith("/docs")


@pytest.mark.asyncio
async def test_rate_limit_retry_uses_extended_budget_and_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    sleep_calls: list[float] = []
    execute_calls: list[dict] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    async def _fake_execute(name: str, payload: dict, context):  # type: ignore[no-untyped-def]
        execute_calls.append({"name": name, "payload": payload, "context": context})
        return ToolResult(success=True, data={"worker_id": "worker-retry-2"})

    class _FakeStore:
        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            _ = state

    monkeypatch.setattr(task_orchestration_workers_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(orchestrator._tool_registry, "execute", _fake_execute)
    orchestrator._orchestration_store = _FakeStore()

    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Inspect backend modules",
        subagent_type="CodeExplore",
        prompt="Inspect backend modules",
        status="failed",
        worker_id="worker-1",
        attempt_count=10,
    )
    state = TaskOrchestrationState(
        orchestration_id="orch-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="inspect backend",
        turn_id="turn-1",
        planner="task_agent",
        retry_budget=1,
        subtasks=[subtask],
    )

    retried = await orchestrator._maybe_retry_subtask(state, subtask, "LLM_RATE_LIMIT")

    assert retried is True
    assert sleep_calls == [60.0]
    assert len(execute_calls) == 1
    assert execute_calls[0]["payload"]["retry_count"] == 10
    assert subtask.worker_id == "worker-retry-2"
    assert subtask.attempt_count == 11
    assert subtask.status == "running"


@pytest.mark.asyncio
async def test_rate_limit_retry_stops_after_ten_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    async def _unexpected_execute(name: str, payload: dict, context):  # type: ignore[no-untyped-def]
        raise AssertionError("execute should not be called when retry budget is exhausted")

    monkeypatch.setattr(orchestrator._tool_registry, "execute", _unexpected_execute)

    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Inspect backend modules",
        subagent_type="CodeExplore",
        prompt="Inspect backend modules",
        status="failed",
        worker_id="worker-1",
        attempt_count=11,
    )
    state = TaskOrchestrationState(
        orchestration_id="orch-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="inspect backend",
        turn_id="turn-1",
        planner="task_agent",
        retry_budget=1,
        subtasks=[subtask],
    )

    retried = await orchestrator._maybe_retry_subtask(state, subtask, "LLM_RATE_LIMIT")

    assert retried is False


@pytest.mark.asyncio
async def test_start_orchestration_passes_workspace_root_to_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _record_plan_subtasks(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            subtasks=[
                SimpleNamespace(
                    description="Inspect backend",
                    subagent_type="CodeExplore",
                    prompt="Inspect backend",
                    parallel_group="group-a",
                )
            ]
        )

    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_record_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    class _FakeStore:
        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            captured["saved_state"] = state

    async def _fake_launch_workers(state: TaskOrchestrationState, *, run_id=None, run_revision=0):  # type: ignore[no-untyped-def]
        _ = (state, run_id, run_revision)
        return None

    monkeypatch.setattr(orchestrator, "_orchestration_store", _FakeStore())
    monkeypatch.setattr(orchestrator, "_launch_workers", _fake_launch_workers)
    async def _fake_resolve_workspace_root(*, user_id: str, session_id: str, user_message: str) -> str:
        _ = (user_id, session_id, user_message)
        return "/tmp/magi"

    monkeypatch.setattr(orchestrator, "_resolve_workspace_root", _fake_resolve_workspace_root)

    result = await orchestrator.start_orchestration(
        user_id="user-1",
        session_id="session-1",
        user_message="Analyze the repo",
        run_id=None,
        run_revision=0,
        turn_id="turn-1",
        user_message_generation=7,
        history=[],
        history_key="user-1::session-1",
        correlation_id=None,
        orchestration_plan=OrchestrationPlan(planner="task_agent", allow_parallel=True),
        persona_id="persona-orchestration",
    )

    assert result.skip_emit is True
    assert captured["kwargs"]["workspace_root"] == "/tmp/magi"
    assert captured["saved_state"].metadata["persona_id"] == "persona-orchestration"
    assert captured["saved_state"].user_message_generation == 7


@pytest.mark.asyncio
async def test_start_orchestration_discards_plan_when_cancelled_during_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_token = EventCancelToken()
    control_store = _FakeControlSessionStore()

    async def _planning_then_cancel(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        cancel_token.cancel("user_cancel")
        return SimpleNamespace(
            subtasks=[
                SimpleNamespace(
                    description="Inspect backend",
                    subagent_type="CodeExplore",
                    prompt="Inspect backend",
                    parallel_group="group-a",
                )
            ]
        )

    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_planning_then_cancel,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
        control_session_store_provider=lambda: control_store,
    )

    class _UnexpectedStore:
        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            _ = state
            raise AssertionError("save_orchestration should not be called after cancellation")

    async def _unexpected_launch_workers(
        state: TaskOrchestrationState,
        *,
        run_id=None,
        run_revision=0,
    ):  # type: ignore[no-untyped-def]
        _ = (state, run_id, run_revision)
        raise AssertionError("workers should not launch after cancellation")

    monkeypatch.setattr(orchestrator, "_orchestration_store", _UnexpectedStore())
    monkeypatch.setattr(orchestrator, "_launch_workers", _unexpected_launch_workers)

    result = await orchestrator.start_orchestration(
        user_id="user-1",
        session_id="session-1",
        user_message="Analyze the repo",
        run_id="run-1",
        run_revision=0,
        turn_id="turn-1",
        history=[],
        history_key="user-1::session-1",
        correlation_id=None,
        orchestration_plan=OrchestrationPlan(planner="task_agent", allow_parallel=True),
        cancel_token=cancel_token,
    )

    assert result.skip_emit is True
    assert result.response == ""
    assert control_store.replace_calls == []


@pytest.mark.asyncio
async def test_start_orchestration_cancels_inflight_planner_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_token = EventCancelToken()
    planner_started = asyncio.Event()
    planner_cancelled = asyncio.Event()

    async def _slow_planner(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        planner_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            planner_cancelled.set()
            raise

    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_slow_planner,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    class _UnexpectedStore:
        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            _ = state
            raise AssertionError("save_orchestration should not be called after planner cancellation")

    async def _unexpected_launch_workers(
        state: TaskOrchestrationState,
        *,
        run_id=None,
        run_revision=0,
    ):  # type: ignore[no-untyped-def]
        _ = (state, run_id, run_revision)
        raise AssertionError("workers should not launch after planner cancellation")

    monkeypatch.setattr(orchestrator, "_orchestration_store", _UnexpectedStore())
    monkeypatch.setattr(orchestrator, "_launch_workers", _unexpected_launch_workers)

    task = asyncio.create_task(
        orchestrator.start_orchestration(
            user_id="user-1",
            session_id="session-1",
            user_message="Analyze the repo",
            run_id="run-1",
            run_revision=0,
            turn_id="turn-1",
            history=[],
            history_key="user-1::session-1",
            correlation_id=None,
            orchestration_plan=OrchestrationPlan(planner="task_agent", allow_parallel=True),
            cancel_token=cancel_token,
        )
    )
    await planner_started.wait()

    cancel_token.cancel("user_cancel")
    result = await task

    assert result.skip_emit is True
    assert result.response == ""
    assert planner_cancelled.is_set()


@pytest.mark.asyncio
async def test_launch_workers_skips_when_orchestration_is_cancelling() -> None:
    class _UnexpectedRegistry(ToolRegistry):
        async def execute(self, name: str, payload: dict, context):  # type: ignore[no-untyped-def]
            raise AssertionError("execute should not be called when orchestration is cancelling")

    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=_UnexpectedRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    saved_states: list[TaskOrchestrationState] = []

    class _FakeStore:
        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            saved_states.append(state)

    orchestrator._orchestration_store = _FakeStore()
    state = TaskOrchestrationState(
        orchestration_id="orch-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="analyze repo",
        planner="task_agent",
        status="cancelling",
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask-1",
                description="Inspect backend",
                subagent_type="CodeExplore",
                prompt="Inspect backend",
            )
        ],
    )

    error = await orchestrator._launch_workers(state)

    assert error is None
    assert state.status == "cancelled"
    assert state.subtasks[0].status == "cancelled"
    assert saved_states[-1].status == "cancelled"


@pytest.mark.asyncio
async def test_process_worker_updates_does_not_aggregate_cancelling_orchestration() -> None:
    registry = ToolRegistry()
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=registry,
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    aggregate_called = False

    async def _unexpected_aggregate(state: TaskOrchestrationState) -> str:
        nonlocal aggregate_called
        aggregate_called = True
        _ = state
        return "should not happen"

    class _FakeStore:
        def __init__(self, state: TaskOrchestrationState) -> None:
            self.state = state
            self.saved_states: list[TaskOrchestrationState] = []

        async def get_orchestration(self, orchestration_id: str) -> TaskOrchestrationState | None:
            return self.state if orchestration_id == self.state.orchestration_id else None

        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            self.state = state
            self.saved_states.append(state)

    state = TaskOrchestrationState(
        orchestration_id="orch-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="analyze repo",
        planner="task_agent",
        status="cancelling",
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask-1",
                description="Inspect backend",
                subagent_type="CodeExplore",
                prompt="Inspect backend",
                status="running",
                worker_id="worker-1",
                attempt_count=1,
            )
        ],
    )
    store = _FakeStore(state)
    orchestrator._orchestration_store = store
    orchestrator._aggregate_orchestration = _unexpected_aggregate

    completed_fact = FactRecord(
        agent_id="chat:session-1",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "orchestration_id": "orch-1",
            "subtask_id": "subtask-1",
            "worker_id": "worker-1",
            "worker_result": {
                "summary": "done",
                "result_status": "success",
            },
        },
    )

    result = await orchestrator.process_worker_updates([completed_fact])

    assert aggregate_called is False
    assert result.skip_emit is True
    assert store.state.status == "cancelled"
    assert store.state.final_response is None


@pytest.mark.asyncio
async def test_cancel_run_marks_matching_orchestrations_cancelled() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    matching = TaskOrchestrationState(
        orchestration_id="orch-match",
        user_id="user-1",
        session_id="session-1",
        root_user_message="analyze repo",
        planner="task_agent",
        status="running",
        metadata={"run_id": "run-1", "run_revision": 0},
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask-1",
                description="Inspect backend",
                subagent_type="CodeExplore",
                prompt="Inspect backend",
                status="running",
                worker_id="worker-1",
                attempt_count=1,
            )
        ],
    )
    other = TaskOrchestrationState(
        orchestration_id="orch-other",
        user_id="user-1",
        session_id="session-1",
        root_user_message="another run",
        planner="task_agent",
        status="running",
        metadata={"run_id": "run-2", "run_revision": 0},
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask-2",
                description="Inspect frontend",
                subagent_type="CodeExplore",
                prompt="Inspect frontend",
                status="running",
                worker_id="worker-2",
                attempt_count=1,
            )
        ],
    )

    class _FakeStore:
        def __init__(self) -> None:
            self.saved_states: list[TaskOrchestrationState] = []

        async def list_orchestrations(
            self,
            user_id: str | None = None,
            session_id: str | None = None,
            statuses: list[str] | None = None,
        ) -> list[TaskOrchestrationState]:
            _ = (user_id, statuses)
            return [matching, other] if session_id == "session-1" else []

        async def save_orchestration(self, state: TaskOrchestrationState) -> None:
            self.saved_states.append(state)

    store = _FakeStore()
    orchestrator._orchestration_store = store

    cancelled = await orchestrator.cancel_run(
        session_id="session-1",
        run_id="run-1",
        run_revision=0,
    )

    assert cancelled == ["orch-match"]
    assert matching.status == "cancelled"
    assert matching.subtasks[0].status == "cancelled"
    assert other.status == "running"


@pytest.mark.asyncio
async def test_strict_cancel_run_reports_live_worker_cancellation_failure() -> None:
    class FailingWorkerManager:
        async def cancel_run_workers(self, **_kwargs):
            raise RuntimeError("worker cancellation failed")

    registry = SimpleNamespace(
        get_tool=lambda _name: SimpleNamespace(_manager=FailingWorkerManager())
    )
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=registry,  # type: ignore[arg-type]
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    with pytest.raises(
        RuntimeError,
        match="Failed to cancel live worker tasks before destructive clear",
    ):
        await orchestrator.cancel_run(
            session_id="session-1",
            run_id="run-1",
            run_revision=0,
            strict_worker_cancellation=True,
        )
