from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from magi.agent.background import (
    BackgroundTaskManager,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.launch import (
    BackgroundLaunchService,
    build_background_run_fn,
    build_spec_from_request,
    default_ack_text,
)
from magi.agent.cancel import CancelToken, EventCancelToken, null_cancel_token
from magi.agent.execution.function_calling import ExecutionOutcome
from magi.agent.task_agents.common.contracts import (
    BaseIntentDecision,
    BaseRuntimeContext,
    ExecutionMode,
    ExecutionRequest,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _make_request(
    *,
    user_message: str = "summarise the recent PRs",
    tools: list[str] | None = None,
    workspace_path: str | None = None,
    turn_id: str = "turn-1",
) -> ExecutionRequest:
    payload = UserMessagePayload(
        user_id="u1",
        session_id="s1",
        content=user_message,
        attachments=[],
        workspace_path=workspace_path,
        turn_id=turn_id,
    )
    context = BaseRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="chat:u1",
        agent_type="chat",
        runtime_key="chat:u1",
        user_id="u1",
        session_id="s1",
        history_key="u1:s1",
        history=[],
        latest_user_message=user_message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=payload,
    )
    intent = BaseIntentDecision(
        intent="chat",
        execution_mode=ExecutionMode.FUNCTION_CALLING,
    )
    return ExecutionRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=list(tools or [])),
    )


@pytest.fixture
async def manager(tmp_path: Path) -> BackgroundTaskManager:
    store = BackgroundTaskStore(db_path=str(tmp_path / "bg.db"))

    async def _noop_run(task: Any, token: CancelToken) -> BackgroundTaskRunResult:
        return BackgroundTaskRunResult(summary="", result_payload={})

    mgr = BackgroundTaskManager(store=store, run_fn=_noop_run, max_concurrent=1)
    await mgr.start()
    try:
        yield mgr
    finally:
        await mgr.stop()


# ----------------------------------------------------------------------
# default_ack_text
# ----------------------------------------------------------------------


def test_default_ack_text_includes_title() -> None:
    text = default_ack_text("analyse commit history")

    assert "analyse commit history" in text
    assert "background" in text.lower()


def test_default_ack_text_handles_empty_title() -> None:
    text = default_ack_text("")

    assert "this task" in text


# ----------------------------------------------------------------------
# build_spec_from_request
# ----------------------------------------------------------------------


def test_build_spec_captures_request_snapshot() -> None:
    request = _make_request(
        user_message="deep research: renewable energy storage trends",
        tools=["deep_research"],
        workspace_path="/home/u/repos/energy",
        turn_id="turn-xyz",
    )

    spec = build_spec_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.RULE
    )

    assert spec.user_id == "u1"
    assert spec.session_id == "s1"
    assert spec.origin_turn_id == "turn-xyz"
    assert spec.goal == "deep research: renewable energy storage trends"
    assert spec.title == "deep research: renewable energy storage trends"
    assert spec.selected_tools == ["deep_research"]
    assert spec.workspace_path == "/home/u/repos/energy"
    assert spec.trigger_source is BackgroundTaskTriggerSource.RULE


def test_build_spec_derives_title_from_first_line_and_truncates() -> None:
    long_msg = "a" * 200
    request = _make_request(user_message=long_msg)

    spec = build_spec_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.CLASSIFIER
    )

    assert len(spec.title) <= 80
    assert spec.title.endswith("...")
    assert spec.goal == long_msg


def test_build_spec_first_line_becomes_title() -> None:
    request = _make_request(user_message="Do the thing\nand then some\ncontinued")

    spec = build_spec_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.USER
    )

    assert spec.title == "Do the thing"


def test_build_spec_defaults_title_when_message_empty() -> None:
    request = _make_request(user_message="")

    spec = build_spec_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.MANUAL
    )

    assert spec.title == "background task"


def test_build_spec_omits_blank_workspace_path() -> None:
    request = _make_request(workspace_path="   ")

    spec = build_spec_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.RULE
    )

    assert spec.workspace_path is None


def test_build_spec_honours_timeout_and_iteration_overrides() -> None:
    request = _make_request()

    spec = build_spec_from_request(
        request,
        trigger_source=BackgroundTaskTriggerSource.RULE,
        timeout_seconds=600,
        max_iterations=5,
    )

    assert spec.timeout_seconds == 600
    assert spec.max_iterations == 5


# ----------------------------------------------------------------------
# BackgroundLaunchService
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_service_enqueues_task_and_returns_ack(
    manager: BackgroundTaskManager,
) -> None:
    service = BackgroundLaunchService(manager)
    request = _make_request(
        user_message="deep research job",
        tools=["deep_research"],
        turn_id="turn-7",
    )

    result = await service.enqueue_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.RULE
    )

    assert result.mode is ExecutionMode.FUNCTION_CALLING
    assert result.turn_id == "turn-7"
    assert result.orchestration_id  # task id surfaced back to caller
    assert result.orchestration_id.startswith("bg_")
    assert "deep research job" in result.response_text
    # Task is visible in the store.
    stored = await manager._store.get_task(result.orchestration_id)  # type: ignore[attr-defined]
    assert stored is not None
    assert stored.status in {BackgroundTaskStatus.PENDING, BackgroundTaskStatus.RUNNING}
    assert stored.spec.goal == "deep research job"
    assert stored.spec.trigger_source is BackgroundTaskTriggerSource.RULE


@pytest.mark.asyncio
async def test_launch_service_uses_custom_ack_builder(
    manager: BackgroundTaskManager,
) -> None:
    def ack_builder(spec: BackgroundTaskSpec, task: Any) -> str:
        return f"OK[{task.task_id}]{spec.title}"

    service = BackgroundLaunchService(manager, ack_builder=ack_builder)
    request = _make_request(user_message="a specific task")

    result = await service.enqueue_from_request(
        request, trigger_source=BackgroundTaskTriggerSource.PLANNER
    )

    assert result.response_text.startswith("OK[bg_")
    assert "a specific task" in result.response_text


# ----------------------------------------------------------------------
# build_background_run_fn
# ----------------------------------------------------------------------


class _RecordingOrchestrator:
    """Stand-in for FunctionCallingOrchestrator — records kwargs & returns a
    scripted outcome."""

    def __init__(self, outcome: ExecutionOutcome) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def execute_with_tools(self, **kwargs: Any) -> ExecutionOutcome:
        self.calls.append(kwargs)
        return self._outcome


@pytest.mark.asyncio
async def test_run_fn_wraps_execute_with_tools_outcome() -> None:
    outcome = ExecutionOutcome(
        status="completed",
        content="final answer",
        tool_failures=[],
        iterations=3,
    )
    orchestrator = _RecordingOrchestrator(outcome)
    run_fn = build_background_run_fn(function_calling_orchestrator=orchestrator)

    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="turn-1",
        title="T",
        goal="do the thing",
        selected_tools=["deep_research"],
        workspace_path="/w",
        trigger_source=BackgroundTaskTriggerSource.RULE,
        max_iterations=7,
        timeout_seconds=600,
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(spec)

    result = await run_fn(task, null_cancel_token())

    assert isinstance(result, BackgroundTaskRunResult)
    assert result.summary == "final answer"
    assert result.orchestration_id == task.task_id
    assert result.result_payload["status"] == "completed"
    assert len(orchestrator.calls) == 1
    call = orchestrator.calls[0]
    assert call["user_message"] == "do the thing"
    assert call["selected_tools"] == ["deep_research"]
    assert call["user_id"] == "u1"
    assert call["session_id"] == "s1"
    assert call["execution_workspace"] == "/w"
    assert call["max_iterations"] == 7
    assert call["intent"] == "background"
    # Cancellation is plumbed through.
    assert call["cancel_token"] is not None


@pytest.mark.asyncio
async def test_run_fn_passes_cancel_token_through() -> None:
    outcome = ExecutionOutcome(
        status="cancelled", content="", tool_failures=[], iterations=1
    )
    orchestrator = _RecordingOrchestrator(outcome)
    run_fn = build_background_run_fn(function_calling_orchestrator=orchestrator)

    token = EventCancelToken()
    spec = BackgroundTaskSpec(
        user_id="u",
        session_id="s",
        origin_turn_id="t",
        title="T",
        goal="g",
        trigger_source=BackgroundTaskTriggerSource.RULE,
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(spec)

    result = await run_fn(task, token)

    assert result.summary == ""
    assert orchestrator.calls[0]["cancel_token"] is token
