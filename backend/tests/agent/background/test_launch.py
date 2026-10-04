from __future__ import annotations

import asyncio
from typing import Any

import pytest

from magi.agent.background import (
    BackgroundTaskManager,
    BackgroundTaskSpec,
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
from magi.agent.execution.checkpoint import AgentRunCheckpoint
from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningState
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.agent.execution.task_budget import (
    consume_task_llm_calls,
    current_task_budget,
)
from magi.agent.task_agents.common.contracts import (
    BaseAdmissionDecision,
    BaseRuntimeContext,
    CapabilitySelection,
    ExecutionRequest,
    IncomingFactKind,
    UserMessagePayload,
)
from magi.chat import ChatStore
from magi.control.session_store import ControlSessionStore
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
    admission = BaseAdmissionDecision(
        run_kind="chat",
        execution_mode=None,
    )
    return ExecutionRequest(
        mode=None,
        context=context,
        admission=admission,
        capabilities=CapabilitySelection(tools=list(tools or [])),
    )


def _make_checkpoint(run_id: str = "run-detached") -> dict[str, Any]:
    policy = ReasoningPolicy()
    return AgentRunCheckpoint(
        run_id=run_id,
        messages=[{"role": "user", "content": "detached chat task"}],
        effective_system_prompt=f"system\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
        tools=[],
        iteration=1,
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    ).to_dict()


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


@pytest.mark.parametrize(
    "title,expected",
    [("analyse commit history", "analyse commit history"), ("", "this task"), ("  ", "this task")],
)
def test_acknowledgment_has_a_task_label_and_background_context(title, expected):
    text = default_ack_text(title)
    assert expected in text
    assert "background" in text.lower()


# ----------------------------------------------------------------------
# build_spec_from_request
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "workspace,expected_workspace",
    [(" /home/u/repos/energy ", "/home/u/repos/energy"), ("   ", None), (None, None)],
)
def test_build_spec_captures_request_snapshot(workspace, expected_workspace) -> None:
    request = _make_request(
        user_message="deep research: renewable energy storage trends",
        tools=["deep_research"],
        workspace_path=workspace,
        turn_id="turn-xyz",
    )

    spec = build_spec_from_request(
        request,
        trigger_source=BackgroundTaskTriggerSource.RULE,
        agent_run_checkpoint=_make_checkpoint(),
    )

    assert spec.user_id == "u1"
    assert spec.session_id == "s1"
    assert spec.origin_turn_id == "turn-xyz"
    assert spec.goal == "deep research: renewable energy storage trends"
    assert spec.title == "deep research: renewable energy storage trends"
    assert spec.selected_tools == ["deep_research"]
    assert spec.workspace_path == expected_workspace
    assert spec.trigger is None
    assert spec.trigger_source is BackgroundTaskTriggerSource.RULE
    assert spec.task_budget_root_turn_id == "turn-xyz"
    assert spec.run_id == "run-detached"
    assert spec.agent_run_checkpoint == _make_checkpoint()


def test_build_spec_rejects_incomplete_checkpoint() -> None:
    with pytest.raises(KeyError, match="run_id"):
        build_spec_from_request(
            _make_request(),
            trigger_source=BackgroundTaskTriggerSource.RULE,
            agent_run_checkpoint={},
        )


@pytest.mark.parametrize(
    "message,expected_title",
    [
        ("a" * 200, "a" * 77 + "..."),
        ("Do the thing\nand then some\ncontinued", "Do the thing"),
        ("", "background task"),
    ],
)
def test_background_title_shortens_display_without_changing_goal(message, expected_title):
    spec = build_spec_from_request(
        _make_request(user_message=message),
        trigger_source=BackgroundTaskTriggerSource.CLASSIFIER,
        agent_run_checkpoint=_make_checkpoint(),
    )
    assert spec.title == expected_title
    assert spec.goal == message


def test_build_spec_honours_timeout_and_iteration_overrides() -> None:
    request = _make_request()

    spec = build_spec_from_request(
        request,
        trigger_source=BackgroundTaskTriggerSource.RULE,
        agent_run_checkpoint=_make_checkpoint(),
        timeout_seconds=600,
        max_iterations=5,
    )

    assert spec.timeout_seconds == 600
    assert spec.max_iterations == 5


# ----------------------------------------------------------------------
# BackgroundLaunchService
# ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_ack", [False, True])
@pytest.mark.parametrize("external_trigger", [False, True])
async def test_launch_acknowledges_the_durable_task_with_complete_trigger(
    manager, custom_ack, external_trigger
):
    ack_inputs = []

    def ack_builder(spec, task):
        ack_inputs.append((spec.title, task.task_id))
        return f"OK[{task.task_id}]{spec.title}"

    service = BackgroundLaunchService(manager, ack_builder=ack_builder if custom_ack else None)
    trigger = (
        RunTrigger(
            trigger_type="external_inbound",
            source_channel="weixin",
            requester="u1",
            priority="foreground",
        )
        if external_trigger
        else None
    )
    source = (
        BackgroundTaskTriggerSource.USER if external_trigger else BackgroundTaskTriggerSource.RULE
    )
    request = _make_request(
        user_message="deep research job", tools=["deep_research"], turn_id="turn-7"
    )
    result = await service.enqueue_from_request(
        request, trigger_source=source, agent_run_checkpoint=_make_checkpoint(), trigger=trigger
    )
    task_id = result.message_payload["background_task_id"]
    stored = await manager.get_task(task_id)
    assert stored is not None
    assert stored.spec.goal == "deep research job"
    assert stored.spec.selected_tools == ["deep_research"]
    assert stored.spec.origin_turn_id == "turn-7"
    assert stored.spec.trigger_source is source
    assert (stored.spec.trigger.to_dict() if stored.spec.trigger else None) == (
        trigger.to_dict() if trigger else None
    )
    assert result.mode is None
    assert result.turn_id == "turn-7"
    assert result.message_payload == {
        "background_task_id": task_id,
        "background_task_title": "deep research job",
        "background_task_attempt": stored.attempt_index,
    }
    if custom_ack:
        assert ack_inputs == [("deep research job", task_id)]
        assert result.response_text == f"OK[{task_id}]deep research job"
    else:
        assert ack_inputs == []
        assert "deep research job" in result.response_text
        assert "background" in result.response_text.lower()


# ----------------------------------------------------------------------
# build_background_run_fn
# ----------------------------------------------------------------------


class _RecordingOrchestrator:
    """Stand-in for the unified orchestrator."""

    def __init__(self, outcome: ExecutionOutcome) -> None:
        self._outcome = outcome
        self.calls: list[Any] = []

    async def run(self, run_input: Any) -> ExecutionOutcome:
        self.calls.append(run_input)
        return self._outcome


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
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        run_plan_store=ControlSessionStore(),
    )

    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="turn-1",
        title="T",
        goal="do the thing",
        selected_tools=["deep_research"],
        skill_preapproval_rules=("bash(git diff *)",),
        system_prompt=f"stable prompt\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
        working_context="run-local guidance",
        ephemeral_context="launch snapshot",
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
    assert result.result_payload["status"] == "completed"
    assert len(orchestrator.calls) == 1
    call = orchestrator.calls[0]
    assert call.turn.text == "do the thing"
    assert call.selected_tools == ["deep_research"]
    assert call.user_id == "u1"
    assert call.session_id == "s1"
    assert call.execution_workspace == "/w"
    assert call.system_prompt.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert "# Runtime World State" in call.runtime_world_state
    assert "* Working Directory: /w" in call.runtime_world_state
    assert call.working_context == "run-local guidance"
    assert call.ephemeral_context == "launch snapshot"
    assert call.max_iterations == 7
    assert call.execution_preset == "background"
    assert call.execution_agent_id == f"background:{task.task_id}"
    assert [rule.display for rule in call.skill_preapproval_rules] == ["bash(git diff *)"]
    # Cancellation is plumbed through.
    assert call.control is not None
    assert call.control.cancel_token is not None


@pytest.mark.asyncio
async def test_run_fn_rejects_blocked_agent_outcome() -> None:
    orchestrator = _RecordingOrchestrator(
        ExecutionOutcome(
            status="blocked",
            content="Completion was blocked.",
            failure_reason="uncertain_effect",
            error_text="External effect outcome is uncertain.",
        )
    )
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        run_plan_store=ControlSessionStore(),
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id="u",
            session_id="s",
            origin_turn_id="t",
            title="T",
            goal="g",
        )
    )

    with pytest.raises(RuntimeError, match="blocked.*uncertain"):
        await run_fn(task, null_cancel_token())


@pytest.mark.asyncio
async def test_run_fn_passes_cancel_token_through() -> None:
    outcome = ExecutionOutcome(status="cancelled", content="", tool_failures=[], iterations=1)
    orchestrator = _RecordingOrchestrator(outcome)
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        run_plan_store=ControlSessionStore(),
    )

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

    with pytest.raises(asyncio.CancelledError):
        await run_fn(task, token)

    assert orchestrator.calls[0].control.cancel_token is token
    assert orchestrator.calls[0].system_prompt.endswith(
        SYSTEM_PROMPT_CACHE_BOUNDARY
    )
    assert "# Runtime World State" in orchestrator.calls[0].runtime_world_state


@pytest.mark.asyncio
async def test_standalone_run_rehydrates_task_budget_across_retries(
    runtime_paths_with_schema,
) -> None:
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    orchestrator = _BudgetConsumingOrchestrator()
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        background_task_budget_store=store,
        run_plan_store=ControlSessionStore(),
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
        run_plan_store=ControlSessionStore(),
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
async def test_run_fn_resumes_from_agent_checkpoint() -> None:
    outcome = ExecutionOutcome(
        status="completed", content="resumed answer", tool_failures=[], iterations=2
    )
    orchestrator = _RecordingOrchestrator(outcome)
    run_fn = build_background_run_fn(
        function_calling_orchestrator=orchestrator,
        run_plan_store=ControlSessionStore(),
    )

    snapshot_messages = [
        {"role": "user", "content": "please analyse the repo"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
    ]
    policy = ReasoningPolicy()
    checkpoint = AgentRunCheckpoint(
        run_id="run-1",
        messages=snapshot_messages,
        effective_system_prompt=f"system\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
        tools=[],
        iteration=1,
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
        selected_tool_names=["deep_research"],
    )
    spec = BackgroundTaskSpec(
        user_id="u1",
        session_id="s1",
        origin_turn_id="turn-1",
        title="T",
        goal="please analyse the repo",
        run_id="run-1",
        selected_tools=["deep_research"],
        trigger_source=BackgroundTaskTriggerSource.MANUAL,
        agent_run_checkpoint=checkpoint.to_dict(),
    )
    from magi.agent.background.contracts import BackgroundTask

    task = BackgroundTask.new(spec)
    result = await run_fn(task, null_cancel_token())

    assert result.summary == "resumed answer"
    call = orchestrator.calls[0]
    assert call.checkpoint is not None
    assert call.checkpoint.messages == snapshot_messages
    assert call.run_id == "run-1"


@pytest.mark.parametrize("has_checkpoint", [False, True])
def test_spec_serialization_isolates_checkpoint_in_both_directions(has_checkpoint):
    checkpoint = _make_checkpoint() if has_checkpoint else None
    spec = BackgroundTaskSpec(
        user_id="u",
        session_id="s",
        origin_turn_id="t",
        title="T",
        goal="g",
        run_id="run-detached",
        trigger_source=BackgroundTaskTriggerSource.MANUAL,
        agent_run_checkpoint=checkpoint,
    )
    payload = spec.to_dict()
    restored = BackgroundTaskSpec.from_dict(payload)
    assert restored.to_dict() == payload
    if has_checkpoint:
        expected_message = "detached chat task"
        spec.agent_run_checkpoint["messages"][0]["content"] = "mutated source spec"
        assert payload["agent_run_checkpoint"]["messages"][0]["content"] == expected_message
        payload["agent_run_checkpoint"]["messages"][0]["content"] = "mutated serialized payload"
        assert restored.agent_run_checkpoint["messages"][0]["content"] == expected_message
    else:
        assert payload["agent_run_checkpoint"] is None
        assert restored.agent_run_checkpoint is None
