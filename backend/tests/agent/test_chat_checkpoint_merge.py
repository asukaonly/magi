from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.execution.function_calling_step_executor import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
)
from magi.agent.task_agents.chat.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.chat.handlers import ChatHandlerDependencies, FunctionCallingHandler
from magi.agent.task_agents.chat.interruption_classifier import InterruptionDisposition
from magi.agent.task_agents.chat.session_run_coordinator import SessionRunCoordinator
from magi.agent.task_agents.common import ExecutionMode, FunctionCallingRequest, IncomingFactKind, OrchestrationPlan, ToolSelection, UserMessagePayload


class _FakeOrchestrator:
    MAX_ITERATIONS = 10

    def __init__(self, step_results, on_step=None):  # type: ignore[no-untyped-def]
        self.step_executor = SimpleNamespace(execute_step=self._execute_step)
        self._step_results = list(step_results)
        self._on_step = on_step
        self.build_step_state_calls: list[str] = []

    def build_step_state(self, *, user_message, system_prompt, selected_tools, conversation_history=None):  # type: ignore[no-untyped-def]
        _ = (system_prompt, selected_tools, conversation_history)
        self.build_step_state_calls.append(user_message)
        return FunctionCallingStepState(
            messages=[{"role": "user", "content": user_message}],
            effective_system_prompt="system prompt",
            tools=[],
        )

    async def _execute_step(self, **kwargs):  # type: ignore[no-untyped-def]
        state = kwargs["state"]
        if self._on_step is not None:
            callback = self._on_step(state)
            if hasattr(callback, "__await__"):
                await callback
        outcome = self._step_results.pop(0)
        state.iteration = outcome.iteration
        return outcome


def _make_context(*, active_run, revision: int, latest_user_message: str) -> ChatRuntimeContext:
    return ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="s-chat",
        agent_type="chat",
        runtime_key="chat:s-chat",
        user_id="u-chat",
        session_id="s-chat",
        history_key="u-chat::s-chat",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message=latest_user_message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content=latest_user_message,
            turn_id="turn-1",
        ),
        active_run=active_run,
        session_run_id=active_run.run_id if active_run is not None else None,
        session_run_revision=revision,
        planner_fact=None,
        planner_fact_kind=IncomingFactKind.USER_MESSAGE,
        planner_payload=UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content=latest_user_message,
            turn_id="turn-1",
        ),
        pending_turns=[],
    )


def _make_request(context: ChatRuntimeContext) -> FunctionCallingRequest:
    return FunctionCallingRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=context,
        intent=IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.FUNCTION_CALLING,
            reasoning="tool use",
            orchestration_plan=OrchestrationPlan(),
        ),
        tool_selection=ToolSelection(tools=["memory_query"], reasoning="tool use"),
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        disable_thinking=True,
    )


def _make_handler(orchestrator: _FakeOrchestrator, coordinator: SessionRunCoordinator) -> FunctionCallingHandler:
    deps = ChatHandlerDependencies(
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        planning_service=SimpleNamespace(),
        function_calling_orchestrator=orchestrator,
        task_orchestrator=SimpleNamespace(),
        history_service=SimpleNamespace(),
        agent_id="s-chat",
        get_task_agent_manager=lambda: None,
        session_run_coordinator=coordinator,
    )
    return FunctionCallingHandler(deps)


@pytest.mark.asyncio
async def test_augment_turn_is_merged_at_next_checkpoint() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    augment_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Also, use the staging endpoint.",
            turn_id="turn-2",
        )
    )

    assert augment_turn.interruption_disposition == InterruptionDisposition.AUGMENT

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(status="continue", iteration=1),
            FunctionCallingStepOutcome(status="completed", iteration=1, content="final after augment"),
        ]
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == "final after augment"
    assert result.turn_id == "turn-2"
    assert orchestrator.build_step_state_calls == [
        "Inspect the login flow.",
        "Inspect the login flow.\n\nAlso, use the staging endpoint.",
    ]


@pytest.mark.asyncio
async def test_interrupt_turn_stops_continuation_and_replans() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )

    def _interrupt_after_first_step(_state):  # type: ignore[no-untyped-def]
        if coordinator.get_active_run("s-chat").revision == 0:
            coordinator.handle_user_turn(
                UserMessagePayload(
                    user_id="u-chat",
                    session_id="s-chat",
                    content="Stop and change the goal to the checkout flow.",
                    turn_id="turn-2",
                )
            )

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(status="continue", iteration=1),
            FunctionCallingStepOutcome(status="completed", iteration=1, content="final after interrupt"),
        ],
        on_step=_interrupt_after_first_step,
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == "final after interrupt"
    assert result.turn_id == "turn-2"
    assert orchestrator.build_step_state_calls == [
        "Inspect the login flow.",
        "Stop and change the goal to the checkout flow.",
    ]
