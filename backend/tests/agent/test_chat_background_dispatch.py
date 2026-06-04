"""Tests for the background-task dispatch branch in FunctionCallingHandler."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.agent.background.contracts import BackgroundTaskTriggerSource
from magi.agent.background.dispatcher import (
    BackgroundDecision,
    BackgroundDecisionContext,
    BackgroundDecisionSource,
    BackgroundDisposition,
)
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.chat.task_agent.fact_classifier import IncomingFactKind
from magi.agent.task_agents.handlers.handlers import (
    ChatHandlerDependencies,
    FunctionCallingHandler,
)
from magi.agent.task_agents.common.contracts import (
    ExecutionMode,
    ExecutionResult,
    FunctionCallingRequest,
    OrchestrationPlan,
    ToolSelection,
    UserMessagePayload,
)
from magi.agent.turn_input import UserTurnInput


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------


class _FakeDispatcher:
    def __init__(self, decision: BackgroundDecision, exc: BaseException | None = None) -> None:
        self._decision = decision
        self._exc = exc
        self.calls: list[BackgroundDecisionContext] = []

    async def classify(
        self, context: BackgroundDecisionContext
    ) -> BackgroundDecision:
        self.calls.append(context)
        if self._exc is not None:
            raise self._exc
        return self._decision


class _FakeLaunchService:
    def __init__(
        self, result: ExecutionResult, exc: BaseException | None = None
    ) -> None:
        self._result = result
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def enqueue_from_request(
        self,
        request: FunctionCallingRequest,
        *,
        trigger_source: BackgroundTaskTriggerSource,
    ) -> ExecutionResult:
        self.calls.append({"request": request, "trigger_source": trigger_source})
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_with_tools(self, **kwargs: Any) -> Any:
        self.calls += 1

        class _Outcome:
            status = "completed"
            content = "foreground reply"

            def to_dict(self) -> dict[str, Any]:
                return {"status": self.status, "content": self.content}

        return _Outcome()


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _make_request(*, user_message: str = "summarise the PRs", tools: list[str] | None = None
) -> FunctionCallingRequest:
    payload = UserMessagePayload(
        user_id="u1",
        session_id="s1",
        content=user_message,
        turn_id="turn-1",
    )
    context = ChatRuntimeContext(
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
        conversation_history=[],
        active_orchestrations=[],
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.FUNCTION_CALLING,
        reasoning="",
    )
    return FunctionCallingRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=list(tools or []), reasoning=""),
        prompt_context=SimpleNamespace(runtime_system=SimpleNamespace(cwd="/")),
        system_prompt="system prompt",
        selected_tools=list(tools or []),
    )


def _make_handler(
    *,
    dispatcher: Any | None = None,
    launch_service: Any | None = None,
    orchestrator: Any | None = None,
) -> FunctionCallingHandler:
    deps = ChatHandlerDependencies(
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        planning_service=SimpleNamespace(),
        function_calling_orchestrator=orchestrator or _FakeOrchestrator(),
        task_orchestrator=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        agent_id="chat:u1",
        get_task_agent_manager=lambda: None,
        session_run_coordinator=None,
        background_dispatcher=dispatcher,
        background_launch_service=launch_service,
    )
    return FunctionCallingHandler(deps)


# ----------------------------------------------------------------------
# Dispatcher branch
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_auto_background_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "magi.agent.task_agents.handlers.runtime_control._auto_background_dispatch_enabled",
        lambda: True,
    )


@pytest.mark.asyncio
async def test_background_branch_returns_launch_service_result_on_background_verdict() -> None:
    ack = ExecutionResult(
        mode=ExecutionMode.FUNCTION_CALLING,
        response_text="Started background task...",
        orchestration_id="bg_123",
        turn_id="turn-1",
    )
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService(ack)
    orchestrator = _FakeOrchestrator()
    handler = _make_handler(
        dispatcher=dispatcher, launch_service=launch, orchestrator=orchestrator
    )
    request = _make_request(user_message="跑完告诉我", tools=["deep_research"])

    result = await handler._maybe_dispatch_to_background(request)

    assert result is ack
    assert orchestrator.calls == 0  # foreground orchestrator never invoked
    assert len(launch.calls) == 1
    assert launch.calls[0]["trigger_source"] is BackgroundTaskTriggerSource.RULE
    # Dispatcher received the user text and selected tools.
    assert dispatcher.calls[0].user_text == "跑完告诉我"
    assert dispatcher.calls[0].selected_tools == ["deep_research"]


@pytest.mark.asyncio
async def test_background_branch_maps_decision_source_to_trigger_source() -> None:
    mappings = [
        (BackgroundDecisionSource.PLANNER, BackgroundTaskTriggerSource.PLANNER),
        (BackgroundDecisionSource.RULE, BackgroundTaskTriggerSource.RULE),
        (BackgroundDecisionSource.LLM, BackgroundTaskTriggerSource.CLASSIFIER),
        (BackgroundDecisionSource.FALLBACK, BackgroundTaskTriggerSource.RULE),
    ]
    for source, expected in mappings:
        dispatcher = _FakeDispatcher(
            BackgroundDecision(
                disposition=BackgroundDisposition.BACKGROUND, source=source
            )
        )
        ack = ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, orchestration_id="bg_x")
        launch = _FakeLaunchService(ack)
        handler = _make_handler(dispatcher=dispatcher, launch_service=launch)

        result = await handler._maybe_dispatch_to_background(_make_request())

        assert result is ack
        assert launch.calls[0]["trigger_source"] is expected


@pytest.mark.asyncio
async def test_background_branch_returns_none_on_foreground_verdict() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.FOREGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService(
        ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, orchestration_id="bg_x")
    )
    handler = _make_handler(dispatcher=dispatcher, launch_service=launch)

    result = await handler._maybe_dispatch_to_background(_make_request())

    assert result is None
    assert launch.calls == []


@pytest.mark.asyncio
async def test_background_branch_returns_none_when_dispatcher_not_wired() -> None:
    handler = _make_handler(dispatcher=None, launch_service=None)

    result = await handler._maybe_dispatch_to_background(_make_request())

    assert result is None


@pytest.mark.asyncio
async def test_background_branch_skips_when_auto_dispatch_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.agent.task_agents.handlers.runtime_control._auto_background_dispatch_enabled",
        lambda: False,
    )
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService(
        ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, orchestration_id="bg_x")
    )
    handler = _make_handler(dispatcher=dispatcher, launch_service=launch)

    result = await handler._maybe_dispatch_to_background(_make_request())

    assert result is None
    assert dispatcher.calls == []
    assert launch.calls == []


@pytest.mark.asyncio
async def test_background_branch_returns_none_when_launch_service_not_wired() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    handler = _make_handler(dispatcher=dispatcher, launch_service=None)

    result = await handler._maybe_dispatch_to_background(_make_request())

    assert result is None


@pytest.mark.asyncio
async def test_background_branch_degrades_on_dispatcher_exception() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        ),
        exc=RuntimeError("dispatcher boom"),
    )
    launch = _FakeLaunchService(
        ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, orchestration_id="bg_x")
    )
    handler = _make_handler(dispatcher=dispatcher, launch_service=launch)

    result = await handler._maybe_dispatch_to_background(_make_request())

    assert result is None
    assert launch.calls == []


@pytest.mark.asyncio
async def test_background_branch_degrades_on_launch_exception() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService(
        ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, orchestration_id="bg_x"),
        exc=RuntimeError("manager not started"),
    )
    handler = _make_handler(dispatcher=dispatcher, launch_service=launch)

    result = await handler._maybe_dispatch_to_background(_make_request())

    assert result is None
