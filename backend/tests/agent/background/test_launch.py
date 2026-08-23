from __future__ import annotations

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
from magi_plugin_sdk.run_trigger import RunTrigger

from magi.agent.cancel import CancelToken, EventCancelToken, null_cancel_token
from magi.agent.execution.function_calling import ExecutionOutcome
from magi.agent.execution.task_budget import (
    consume_task_llm_calls,
    current_task_budget,
)
from magi.agent.task_agents.common.contracts import (
    BaseIntentDecision,
    BaseRuntimeContext,
    ExecutionMode,
    ExecutionRequest,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)
from magi.chat import ChatStore
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
async def manager(runtime_paths_with_schema) -> BackgroundTaskManager:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

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

    spec = build_spec_from_request(request, trigger_source=BackgroundTaskTriggerSource.RULE)

    assert spec.user_id == "u1"
    assert spec.session_id == "s1"
    assert spec.origin_turn_id == "turn-xyz"
    assert spec.goal == "deep research: renewable energy storage trends"
    assert spec.title == "deep research: renewable energy storage trends"
    assert spec.selected_tools == ["deep_research"]
    assert spec.workspace_path == "/home/u/repos/energy"
    assert spec.trigger_source is BackgroundTaskTriggerSource.RULE
    assert spec.task_budget_root_turn_id == "turn-xyz"


def test_build_spec_derives_title_from_first_line_and_truncates() -> None:
    long_msg = "a" * 200
    request = _make_request(user_message=long_msg)

    spec = build_spec_from_request(request, trigger_source=BackgroundTaskTriggerSource.CLASSIFIER)

    assert len(spec.title) <= 80
    assert spec.title.endswith("...")
    assert spec.goal == long_msg


def test_build_spec_first_line_becomes_title() -> None:
    request = _make_request(user_message="Do the thing\nand then some\ncontinued")

    spec = build_spec_from_request(request, trigger_source=BackgroundTaskTriggerSource.USER)

    assert spec.title == "Do the thing"


def test_build_spec_defaults_title_when_message_empty() -> None:
    request = _make_request(user_message="")

    spec = build_spec_from_request(request, trigger_source=BackgroundTaskTriggerSource.MANUAL)

    assert spec.title == "background task"


def test_build_spec_omits_blank_workspace_path() -> None:
    request = _make_request(workspace_path="   ")

    spec = build_spec_from_request(request, trigger_source=BackgroundTaskTriggerSource.RULE)

    assert spec.workspace_path is None


def test_build_spec_carries_run_trigger() -> None:
    request = _make_request()
    trigger = RunTrigger(
        trigger_type="external_inbound",
        source_channel="weixin",
        requester="u1",
        priority="foreground",
    )

    spec = build_spec_from_request(
        request,
        trigger_source=BackgroundTaskTriggerSource.USER,
        trigger=trigger,
    )

    assert spec.trigger is trigger
    assert spec.trigger.source_channel == "weixin"


def test_build_spec_trigger_defaults_to_none() -> None:
    spec = build_spec_from_request(_make_request(), trigger_source=BackgroundTaskTriggerSource.RULE)
    assert spec.trigger is None


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
async def test_launch_service_persists_run_trigger_on_spec(
    manager: BackgroundTaskManager,
) -> None:
    service = BackgroundLaunchService(manager)
    trigger = RunTrigger(
        trigger_type="external_inbound",
        source_channel="weixin",
        requester="u1",
        priority="foreground",
    )

    result = await service.enqueue_from_request(
        _make_request(user_message="weixin-originated long task"),
        trigger_source=BackgroundTaskTriggerSource.USER,
        trigger=trigger,
    )

    stored = await manager._store.get_task(result.orchestration_id)  # type: ignore[attr-defined]
    assert stored is not None
    # The origin channel survives onto the persisted background spec, so the
    # completed task can be delivered back to weixin.
    assert stored.spec.trigger is not None
    assert stored.spec.trigger.trigger_type == "external_inbound"
    assert stored.spec.trigger.source_channel == "weixin"


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

    async def run(self, run_input: Any) -> ExecutionOutcome:  # engine front door (ADR-0004 P4)
        return await self.execute_with_tools(**run_input.to_execute_kwargs())


class _BudgetConsumingOrchestrator:
    def __init__(self) -> None:
        self.roots: list[str | None] = []

    async def run(self, _run_input: Any) -> ExecutionOutcome:
        budget = current_task_budget()
        self.roots.append(budget.root_turn_id if budget is not None else None)
        await consume_task_llm_calls()
        return ExecutionOutcome(
            status="completed",
            content="done",
            tool_failures=[],
            iterations=1,
        )


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
    assert call["turn"].text == "do the thing"
    assert call["selected_tools"] == ["deep_research"]
    assert call["user_id"] == "u1"
    assert call["session_id"] == "s1"
    assert call["execution_workspace"] == "/w"
    assert call["max_iterations"] == 7
    assert call["intent"] == "background"
    assert call["execution_agent_id"] == f"background:{task.task_id}"
    # Cancellation is plumbed through.
    assert call["cancel_token"] is not None


@pytest.mark.asyncio
async def test_run_fn_passes_cancel_token_through() -> None:
    outcome = ExecutionOutcome(status="cancelled", content="", tool_failures=[], iterations=1)
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


@pytest.mark.asyncio
async def test_standalone_run_rehydrates_task_budget_across_retries(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    orchestrator = _BudgetConsumingOrchestrator()
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        background_task_budget_store=store,
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id="u",
            session_id="s",
            origin_turn_id="",
            title="T",
            goal="g",
            trigger_source=BackgroundTaskTriggerSource.SCHEDULE,
        )
    )
    await store.create_task(task)

    await run_fn(task, null_cancel_token())
    await run_fn(task, null_cancel_token())

    state = await store.ensure_task_execution_budget(
        root_turn_id=task.task_id,
        max_llm_calls=30,
        max_worker_launches=8,
    )
    assert orchestrator.roots == [task.task_id, task.task_id]
    assert state == (30, 2, 8, 0)


@pytest.mark.asyncio
async def test_chat_background_run_continues_root_turn_budget(
    runtime_paths_with_schema,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.create_user_turn(
        session_id="s",
        user_id="u",
        turn_id="turn-root",
        message_text="continue in background",
        created_at_ms=100,
    )
    background_store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    orchestrator = _BudgetConsumingOrchestrator()
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        chat_task_budget_store=chat_store,
        background_task_budget_store=background_store,
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id="u",
            session_id="s",
            origin_turn_id="turn-root",
            title="T",
            goal="g",
            trigger_source=BackgroundTaskTriggerSource.MANUAL,
            task_budget_root_turn_id="turn-root",
        )
    )
    await background_store.create_task(task)

    await run_fn(task, null_cancel_token())
    await run_fn(task, null_cancel_token())

    state = await chat_store.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=30,
        max_worker_launches=8,
    )
    assert orchestrator.roots == ["turn-root", "turn-root"]
    assert state == (30, 2, 8, 0)


@pytest.mark.asyncio
async def test_run_fn_resumes_from_initial_messages_when_present() -> None:
    """When a spec carries an OrchestratorSnapshot's messages, the run
    function must pass them as ``conversation_history`` and leave
    ``user_message`` empty so the resumed turn is not duplicated.
    """
    outcome = ExecutionOutcome(
        status="completed", content="resumed answer", tool_failures=[], iterations=2
    )
    orchestrator = _RecordingOrchestrator(outcome)
    run_fn = build_background_run_fn(function_calling_orchestrator=orchestrator)

    snapshot_messages = [
        {"role": "user", "content": "please analyse the repo"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
    ]
    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="turn-1",
        title="T",
        goal="please analyse the repo",
        selected_tools=["deep_research"],
        trigger_source=BackgroundTaskTriggerSource.MANUAL,
        initial_messages=snapshot_messages,
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(spec)
    result = await run_fn(task, null_cancel_token())

    assert result.summary == "resumed answer"
    call = orchestrator.calls[0]
    assert call["turn"].text == ""
    assert call["conversation_history"] == snapshot_messages
    # The background runner must deep-copy so a later mutation of the
    # spec payload cannot retroactively change the live orchestrator
    # input.
    assert call["conversation_history"] is not snapshot_messages


def test_spec_roundtrip_preserves_initial_messages() -> None:
    messages = [{"role": "user", "content": "resume me"}]
    spec = BackgroundTaskSpec(
        user_id="u",
        session_id="s",
        origin_turn_id="t",
        title="T",
        goal="g",
        trigger_source=BackgroundTaskTriggerSource.MANUAL,
        initial_messages=messages,
    )
    restored = BackgroundTaskSpec.from_dict(spec.to_dict())
    assert restored.initial_messages == messages
    # Deep copy: mutating the original must not reach the restored spec.
    messages[0]["content"] = "edited"
    assert restored.initial_messages is not None
    assert restored.initial_messages[0]["content"] == "resume me"


def test_spec_roundtrip_without_initial_messages_stays_none() -> None:
    spec = BackgroundTaskSpec(
        user_id="u",
        session_id="s",
        origin_turn_id="t",
        title="T",
        goal="g",
        trigger_source=BackgroundTaskTriggerSource.RULE,
    )
    restored = BackgroundTaskSpec.from_dict(spec.to_dict())
    assert restored.initial_messages is None
