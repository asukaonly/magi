"""Tests for early background placement in the chat turn pipeline."""

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
from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.common.contracts import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ToolSelection,
    UserMessagePayload,
)
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.handlers.handlers import ChatHandlerDependencies, FunctionCallingHandler
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.chat.task_agent.fact_classifier import ChatFactClassifier, IncomingFactKind
from magi.chat.task_agent.run_placement_service import (
    ChatBackgroundLaunchRequest,
    ChatRunPlacementService,
)
from magi.agent.task_agents.handlers import ExecutionHandlerRegistry


class _FakeDispatcher:
    def __init__(self, decision: BackgroundDecision, exc: BaseException | None = None) -> None:
        self._decision = decision
        self._exc = exc
        self.calls: list[BackgroundDecisionContext] = []

    async def classify(self, context: BackgroundDecisionContext) -> BackgroundDecision:
        self.calls.append(context)
        if self._exc is not None:
            raise self._exc
        return self._decision


class _FakeLaunchService:
    def __init__(
        self,
        result: ExecutionResult | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self._result = result or ExecutionResult(
            mode=ExecutionMode.FUNCTION_CALLING,
            response_text="Started background task...",
            orchestration_id="bg_123",
            turn_id="turn-1",
        )
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def enqueue_from_request(
        self,
        request: ExecutionRequest,
        *,
        trigger_source: BackgroundTaskTriggerSource,
        trigger: Any | None = None,
    ) -> ExecutionResult:
        self.calls.append(
            {"request": request, "trigger_source": trigger_source, "trigger": trigger}
        )
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeContextDecider:
    tool_registry = SimpleNamespace(list_tools=lambda: [])


class _CountingHandler:
    mode = ExecutionMode.FUNCTION_CALLING

    def __init__(self) -> None:
        self.build_calls = 0

    async def build_request(self, request: ExecutionRequest) -> ExecutionRequest:
        self.build_calls += 1
        return request

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(mode=request.mode, response_text="foreground")


def _make_context(*, user_message: str = "summarise the PRs") -> ChatRuntimeContext:
    payload = UserMessagePayload(
        user_id="u1",
        session_id="s1",
        content=user_message,
        turn_id="turn-1",
    )
    return ChatRuntimeContext(
        latest_fact=FactRecord(
            agent_id="chat:u1",
            event_type="user_message",
            payload=payload.to_dict(),
        ),
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


def _make_intent() -> IntentDecision:
    return IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.FUNCTION_CALLING,
        reasoning="",
    )


def _make_request(
    *,
    user_message: str = "summarise the PRs",
    tools: list[str] | None = None,
) -> ExecutionRequest:
    return ExecutionRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=_make_context(user_message=user_message),
        intent=_make_intent(),
        tool_selection=ToolSelection(tools=list(tools or []), reasoning=""),
    )


def _enabled_service(
    *,
    dispatcher: Any | None = None,
    launch_service: Any | None = None,
    session_run_coordinator: Any | None = None,
) -> ChatRunPlacementService:
    service = ChatRunPlacementService(
        background_dispatcher=dispatcher,
        background_launch_service=launch_service,
        session_run_coordinator=session_run_coordinator,
    )
    service._auto_background_dispatch_enabled = lambda: True  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_run_placement_returns_background_request_on_background_verdict() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    service = _enabled_service(dispatcher=dispatcher, launch_service=_FakeLaunchService())

    request = await service.maybe_prepare_background_launch(
        _make_request(user_message="跑完告诉我", tools=["deep_research"])
    )

    assert isinstance(request, ChatBackgroundLaunchRequest)
    assert request.trigger_source is BackgroundTaskTriggerSource.RULE
    assert request.trigger is None
    assert dispatcher.calls[0].user_text == "跑完告诉我"
    assert dispatcher.calls[0].selected_tools == ["deep_research"]


@pytest.mark.asyncio
async def test_run_placement_forwards_run_trigger_keeping_decision_source() -> None:
    from magi_plugin_sdk.run_trigger import RunTrigger

    run_trigger = RunTrigger(
        trigger_type="external_inbound",
        source_channel="weixin",
        requester="u1",
        priority="foreground",
    )
    active_run = SimpleNamespace(trigger=run_trigger)
    coordinator = SimpleNamespace(get_active_run=lambda session_id: active_run)
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    service = _enabled_service(
        dispatcher=dispatcher,
        launch_service=_FakeLaunchService(),
        session_run_coordinator=coordinator,
    )

    request = await service.maybe_prepare_background_launch(_make_request())

    assert isinstance(request, ChatBackgroundLaunchRequest)
    assert request.trigger is run_trigger
    assert request.trigger.source_channel == "weixin"
    assert request.trigger_source is BackgroundTaskTriggerSource.RULE


@pytest.mark.asyncio
async def test_run_placement_maps_decision_source_to_trigger_source() -> None:
    mappings = [
        (BackgroundDecisionSource.PLANNER, BackgroundTaskTriggerSource.PLANNER),
        (BackgroundDecisionSource.RULE, BackgroundTaskTriggerSource.RULE),
        (BackgroundDecisionSource.LLM, BackgroundTaskTriggerSource.CLASSIFIER),
        (BackgroundDecisionSource.FALLBACK, BackgroundTaskTriggerSource.RULE),
    ]
    for source, expected in mappings:
        dispatcher = _FakeDispatcher(
            BackgroundDecision(
                disposition=BackgroundDisposition.BACKGROUND,
                source=source,
            )
        )
        service = _enabled_service(dispatcher=dispatcher, launch_service=_FakeLaunchService())

        request = await service.maybe_prepare_background_launch(_make_request())

        assert isinstance(request, ChatBackgroundLaunchRequest)
        assert request.trigger_source is expected


@pytest.mark.asyncio
async def test_run_placement_returns_none_on_foreground_verdict() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.FOREGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService()
    service = _enabled_service(dispatcher=dispatcher, launch_service=launch)

    request = await service.maybe_prepare_background_launch(_make_request())

    assert request is None
    assert launch.calls == []


@pytest.mark.asyncio
async def test_run_placement_skips_when_auto_dispatch_disabled() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService()
    service = ChatRunPlacementService(
        background_dispatcher=dispatcher,
        background_launch_service=launch,
    )
    service._auto_background_dispatch_enabled = lambda: False  # type: ignore[method-assign]

    request = await service.maybe_prepare_background_launch(_make_request())

    assert request is None
    assert dispatcher.calls == []
    assert launch.calls == []


@pytest.mark.asyncio
async def test_run_placement_returns_none_when_services_not_wired() -> None:
    service = _enabled_service(dispatcher=None, launch_service=None)

    request = await service.maybe_prepare_background_launch(_make_request())

    assert request is None


@pytest.mark.asyncio
async def test_run_placement_degrades_on_dispatcher_exception() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        ),
        exc=RuntimeError("dispatcher boom"),
    )
    launch = _FakeLaunchService()
    service = _enabled_service(dispatcher=dispatcher, launch_service=launch)

    request = await service.maybe_prepare_background_launch(_make_request())

    assert request is None
    assert launch.calls == []


@pytest.mark.asyncio
async def test_run_placement_launches_background_request() -> None:
    ack = ExecutionResult(mode=ExecutionMode.FUNCTION_CALLING, orchestration_id="bg_x")
    launch = _FakeLaunchService(result=ack)
    service = _enabled_service(launch_service=launch)
    request = ChatBackgroundLaunchRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=_make_context(),
        intent=_make_intent(),
        tool_selection=ToolSelection(tools=["deep_research"]),
        trigger_source=BackgroundTaskTriggerSource.CLASSIFIER,
    )

    result = await service.launch_background(request)

    assert result is ack
    assert launch.calls[0]["trigger_source"] is BackgroundTaskTriggerSource.CLASSIFIER


@pytest.mark.asyncio
async def test_run_placement_launch_degrades_on_launch_exception() -> None:
    launch = _FakeLaunchService(exc=RuntimeError("manager not started"))
    service = _enabled_service(launch_service=launch)
    request = ChatBackgroundLaunchRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=_make_context(),
        intent=_make_intent(),
        tool_selection=ToolSelection(tools=["deep_research"]),
    )

    result = await service.launch_background(request)

    assert result is None


@pytest.mark.asyncio
async def test_coordinator_places_background_before_handler_build() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    launch = _FakeLaunchService()
    placement = _enabled_service(dispatcher=dispatcher, launch_service=launch)
    handler = _CountingHandler()
    registry = ExecutionHandlerRegistry()
    registry.register(handler)
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(),
        fact_classifier=ChatFactClassifier(),
        handler_registry=registry,
        run_placement_service=placement,
    )

    request = await coordinator.assemble_request(
        _make_context(user_message="跑完告诉我"),
        _make_intent(),
        ToolSelection(tools=["deep_research"], reasoning=""),
    )

    assert isinstance(request, ChatBackgroundLaunchRequest)
    assert handler.build_calls == 0


@pytest.mark.asyncio
async def test_coordinator_launch_failure_falls_back_to_handler_build() -> None:
    dispatcher = _FakeDispatcher(
        BackgroundDecision(
            disposition=BackgroundDisposition.BACKGROUND,
            source=BackgroundDecisionSource.RULE,
        )
    )
    placement = _enabled_service(
        dispatcher=dispatcher,
        launch_service=_FakeLaunchService(exc=RuntimeError("manager not started")),
    )
    handler = _CountingHandler()
    registry = ExecutionHandlerRegistry()
    registry.register(handler)
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(),
        fact_classifier=ChatFactClassifier(),
        handler_registry=registry,
        run_placement_service=placement,
        execution_engine=SimpleNamespace(
            execute=lambda request: _fake_execution_outcome(request),
        ),
    )
    request = await coordinator.assemble_request(
        _make_context(user_message="跑完告诉我"),
        _make_intent(),
        ToolSelection(tools=["deep_research"], reasoning=""),
    )

    result = await coordinator.execute(request)

    assert handler.build_calls == 1
    assert result.response_text == "foreground"


async def _fake_execution_outcome(request: ExecutionRequest) -> Any:
    return SimpleNamespace(
        result=ExecutionResult(mode=request.mode, response_text="foreground"),
        used_graph=False,
    )


def test_function_calling_handler_no_longer_auto_dispatches_background() -> None:
    source = FunctionCallingHandler.execute.__code__.co_names

    assert "_maybe_dispatch_to_background" not in source


def test_handler_dependencies_no_longer_carry_background_dispatcher() -> None:
    assert "background_dispatcher" not in ChatHandlerDependencies.__dataclass_fields__
