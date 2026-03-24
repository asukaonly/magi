from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import magi.agent.task_orchestrator as task_orchestrator_module
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


def test_build_agent_tool_context_includes_workspace_and_agent_metadata() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    context = orchestrator._build_agent_tool_context("user-1", "session-1")

    assert context.agent_id == "explore:user-1"
    expected_workspace = Path.cwd().parent if Path.cwd().name == "backend" else Path.cwd()
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
    }


def test_chat_default_workspace_root_uses_managed_magi_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    expected_workspace = tmp_path / "home" / ".magi" / "chat-workspace"
    monkeypatch.setattr(
        task_orchestrator_module,
        "get_default_chat_workspace_path",
        lambda: str(expected_workspace),
    )

    resolved = orchestrator._default_workspace_root()

    assert resolved == str(expected_workspace)


def test_resolve_workspace_root_prefers_explicit_user_scope() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    resolved = orchestrator._resolve_workspace_root("看下~/code/magi下的代码，分析下代码架构")

    assert resolved == "/Users/asuka/code/magi"


def test_resolve_workspace_root_supports_docs_relative_scope() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    resolved = orchestrator._resolve_workspace_root("看下 docs/project-overview.md 的文档结构")

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

    monkeypatch.setattr(task_orchestrator_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(orchestrator._tool_registry, "execute", _fake_execute)
    orchestrator._orchestration_store = _FakeStore()

    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Inspect backend modules",
        subagent_type="Explore",
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
        subagent_type="Explore",
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
                    subagent_type="Explore",
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
            _ = state

    async def _fake_launch_workers(state: TaskOrchestrationState, *, run_id=None, run_revision=0):  # type: ignore[no-untyped-def]
        _ = (state, run_id, run_revision)
        return None

    monkeypatch.setattr(orchestrator, "_orchestration_store", _FakeStore())
    monkeypatch.setattr(orchestrator, "_launch_workers", _fake_launch_workers)
    monkeypatch.setattr(orchestrator, "_resolve_workspace_root", lambda user_message: "/Users/asuka/code/magi")

    result = await orchestrator.start_orchestration(
        user_id="user-1",
        session_id="session-1",
        user_message="Analyze the repo",
        run_id=None,
        run_revision=0,
        turn_id="turn-1",
        history=[],
        history_key="user-1::session-1",
        correlation_id=None,
        orchestration_strategy={"planner": "task_agent", "allow_parallel": True},
    )

    assert result.skip_emit is True
    assert captured["kwargs"]["workspace_root"] == "/Users/asuka/code/magi"
