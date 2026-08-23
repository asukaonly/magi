from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.execution.task_budget import task_execution_budget_scope
from magi.agent.execution.function_calling.step_executor import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
)
from magi.agent.execution.function_calling.types import ExecutionOutcome
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.handlers.handlers import ChatHandlerDependencies, FunctionCallingHandler
from magi.chat.task_agent.interruption_classifier import InterruptionDisposition
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.control.run_control import RetractRequested, SuspendRequested, null_run_control
from magi.llm.model_context import unknown_model_context
from magi.agent.task_agents.common import (
    ExecutionMode,
    FunctionCallingRequest,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)


class _FakeOrchestrator:
    MAX_ITERATIONS = 10

    def __init__(
        self,
        step_results,
        on_step=None,
        context_failure: ExecutionOutcome | None = None,
    ):  # type: ignore[no-untyped-def]
        self.step_executor = SimpleNamespace(execute_step=self._execute_step)
        self._step_results = list(step_results)
        self._on_step = on_step
        self.build_step_state_calls: list[str] = []
        self.execute_with_tools_calls: list[dict[str, object]] = []
        self.fallback_calls: list[dict[str, object]] = []
        self.prepare_context_calls = 0
        self.prepare_context_include_tools: list[bool] = []
        self.context_failure = context_failure
        self.execute_step_calls: list[dict[str, object]] = []

    def build_step_state(
        self,
        *,
        turn,
        system_prompt,
        selected_tools,
        conversation_history=None,
        session_summary=None,
        session_origin=None,
        reply_context=None,
        allow_attachment_grounding=False,
        ephemeral_context=None,
        **kwargs,
    ):  # type: ignore[no-untyped-def]
        _ = (
            system_prompt,
            selected_tools,
            conversation_history,
            session_summary,
            session_origin,
            reply_context,
            allow_attachment_grounding,
            ephemeral_context,
            kwargs,
        )
        self.build_step_state_calls.append(turn.text)
        return FunctionCallingStepState(
            messages=[{"role": "user", "content": turn.text}],
            effective_system_prompt="system prompt",
            tools=[],
        )

    async def _execute_step(self, **kwargs):  # type: ignore[no-untyped-def]
        self.execute_step_calls.append(dict(kwargs))
        state = kwargs["state"]
        if self._on_step is not None:
            callback = self._on_step(state)
            if hasattr(callback, "__await__"):
                await callback
        outcome = self._step_results.pop(0)
        state.iteration = outcome.iteration
        return outcome

    @staticmethod
    def _build_retracted_outcome(state, _signal):  # type: ignore[no-untyped-def]
        return ExecutionOutcome(status="retracted", content="", iterations=state.iteration)

    @staticmethod
    def _build_suspended_outcome(state, _signal):  # type: ignore[no-untyped-def]
        return ExecutionOutcome(status="suspended", content="", iterations=state.iteration)

    async def _prepare_context_for_model(
        self,
        state: FunctionCallingStepState,
        *,
        include_tools: bool = True,
    ) -> ExecutionOutcome | None:
        _ = (state, include_tools)
        self.prepare_context_calls += 1
        self.prepare_context_include_tools.append(include_tools)
        return self.context_failure

    async def run(self, run_input):  # engine front door (ADR-0004 P4) → forwards
        return await self.execute_with_tools(**run_input.to_execute_kwargs())

    async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
        self.execute_with_tools_calls.append(dict(kwargs))
        return SimpleNamespace(
            content="tool result",
            to_dict=lambda: {"status": "completed", "content": "tool result"},
        )

    async def _execute_fallback_final_response(self, **kwargs):  # type: ignore[no-untyped-def]
        self.fallback_calls.append(dict(kwargs))
        return SimpleNamespace(
            content="fallback result",
            to_dict=lambda: {"status": "completed", "content": "fallback result"},
        )


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
        ),
        tool_selection=ToolSelection(tools=["memory_query"], reasoning="tool use"),
        prompt_context=SimpleNamespace(runtime_system=SimpleNamespace(cwd="/tmp/magi")),
        system_prompt="system prompt",
        selected_tools=["memory_query"],
    )


def _make_handler(
    orchestrator: _FakeOrchestrator, coordinator: SessionRunCoordinator
) -> FunctionCallingHandler:
    deps = ChatHandlerDependencies(
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        planning_service=SimpleNamespace(),
        function_calling_orchestrator=orchestrator,
        task_orchestrator=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        model_context_provider=lambda: unknown_model_context(None),
        agent_id="s-chat",
        get_task_agent_manager=lambda: None,
        session_run_coordinator=coordinator,
    )
    return FunctionCallingHandler(deps)


@pytest.mark.asyncio
async def test_checkpoint_loop_stops_before_model_when_context_cannot_fit() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    orchestrator = _FakeOrchestrator(
        step_results=[],
        context_failure=ExecutionOutcome(
            status="failed",
            content="",
            failure_reason="Context window exceeded",
            iterations=0,
        ),
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.execution_outcome["status"] == "failed"
    assert result.execution_outcome["failure_reason"] == "Context window exceeded"
    assert orchestrator.prepare_context_calls == 1
    assert orchestrator.build_step_state_calls == ["Inspect the login flow."]


@pytest.mark.asyncio
async def test_checkpoint_loop_uses_last_budget_slot_for_fallback() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    orchestrator = _FakeOrchestrator(
        step_results=[FunctionCallingStepOutcome(status="continue", iteration=1)]
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    async with task_execution_budget_scope(max_llm_calls=1):
        result = await handler.execute(_make_request(context))

    assert result.response_text == "fallback result"
    assert orchestrator.fallback_calls[0]["final_response_reason"] == ("task_budget_finalization")
    assert len(orchestrator._step_results) == 1


@pytest.mark.asyncio
async def test_augment_turn_is_merged_at_next_checkpoint() -> None:
    """Verify the FC handler merges an AUGMENT pending turn at the
    next checkpoint boundary.

    H6 collapsed the sync interruption classifier to (strict cancel | DEFER),
    so AUGMENT can only arise via the async LLM classifier or by an
    explicit dispatch. The test seeds an AUGMENT-disposition pending turn
    directly on the run store to exercise the merge path without depending
    on classifier internals.
    """
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    # Seed an AUGMENT pending turn (post-H6: sync classifier never assigns
    # AUGMENT itself; we inject the disposition the LLM classifier would
    # have produced).
    coordinator._run_store.append_pending_turn(
        "s-chat",
        "turn-2",
        "Instead of the login flow, inspect the signup flow.",
        disposition=InterruptionDisposition.AUGMENT.value,
    )

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(status="continue", iteration=1),
            FunctionCallingStepOutcome(
                status="completed", iteration=1, content="final after augment"
            ),
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
        "Inspect the login flow.\n\nInstead of the login flow, inspect the signup flow.",
    ]
    assert result.execution_outcome["iterations"] == 2


@pytest.mark.asyncio
async def test_interrupt_turn_stops_continuation_and_replans() -> None:
    """Verify the handler aborts continuation and replans when a new
    INTERRUPT-class turn bumps the run revision mid-step.

    Post-H6, the sync classifier only matches strict cancel phrases.
    To exercise the mid-run replan path, we bump the revision and set
    the new root turn directly — the same mutation that the LLM
    classifier path would perform on a non-strict INTERRUPT.
    """
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
            coordinator._run_store.bump_revision(
                "s-chat",
                clear_pending_turns=True,
            )
            coordinator._run_store.set_root_turn(
                "s-chat",
                turn_id="turn-2",
                content="Stop and change the goal to the checkout flow.",
            )

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(status="continue", iteration=1),
            FunctionCallingStepOutcome(
                status="completed", iteration=1, content="final after interrupt"
            ),
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


@pytest.mark.asyncio
async def test_cancel_before_first_step_returns_cancelled_without_executing() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    # Simulate an ingress-time INTERRUPT: the coordinator is asked to cancel
    # before the handler ever runs a step.
    coordinator.request_cancel(
        session_id="s-chat",
        requested_by="user",
        reason="ingress_interrupt",
        anchor_turn_id="turn-interrupt",
    )

    orchestrator = _FakeOrchestrator(step_results=[])
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == ""
    assert result.execution_outcome["status"] == "cancelled"
    # The handler must not have invoked any step_executor call.
    assert orchestrator.build_step_state_calls == ["Inspect the login flow."]


@pytest.mark.asyncio
async def test_cancel_between_steps_short_circuits_loop() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )

    def _cancel_after_first_step(_state):  # type: ignore[no-untyped-def]
        if coordinator.get_active_run("s-chat").status == "running":
            coordinator.request_cancel(
                session_id="s-chat",
                requested_by="user",
                reason="ingress_interrupt",
                anchor_turn_id="turn-interrupt",
            )

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(status="continue", iteration=1),
            # If cancel is honored, we never reach the second outcome.
            FunctionCallingStepOutcome(status="completed", iteration=2, content="should not run"),
        ],
        on_step=_cancel_after_first_step,
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.execution_outcome["status"] == "cancelled"
    assert result.response_text == ""
    # Only one step state built (for iteration 0); cancel fires before iter 1.
    assert len(orchestrator.build_step_state_calls) == 1


@pytest.mark.asyncio
async def test_checkpoint_loop_honors_registered_retract_control() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    control = null_run_control()
    coordinator.register_active_run_control(
        "s-chat",
        first_turn.active_run.run_id,
        control,
    )
    assert coordinator.request_retract(
        session_id="s-chat",
        payload=RetractRequested(reason="user_retract"),
    )
    orchestrator = _FakeOrchestrator(step_results=[])
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )
    context.control = control

    result = await handler.execute(_make_request(context))

    assert result.execution_outcome["status"] == "retracted"
    assert orchestrator.execute_step_calls == []


@pytest.mark.asyncio
async def test_checkpoint_loop_honors_registered_suspend_control() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    control = null_run_control()
    control.suspend_signal.request(SuspendRequested(reason="window_closed"))
    orchestrator = _FakeOrchestrator(step_results=[])
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )
    context.control = control

    result = await handler.execute(_make_request(context))

    assert result.execution_outcome["status"] == "suspended"
    assert orchestrator.execute_step_calls == []


@pytest.mark.asyncio
async def test_checkpoint_loop_passes_control_into_model_step() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    control = null_run_control()
    coordinator.register_active_run_control(
        "s-chat",
        first_turn.active_run.run_id,
        control,
    )

    def _retract_during_step(_state):  # type: ignore[no-untyped-def]
        coordinator.request_retract(
            session_id="s-chat",
            payload=RetractRequested(reason="user_retract"),
        )

    orchestrator = _FakeOrchestrator(
        step_results=[FunctionCallingStepOutcome(status="aborted", iteration=1)],
        on_step=_retract_during_step,
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )
    context.control = control

    result = await handler.execute(_make_request(context))

    assert result.execution_outcome["status"] == "retracted"
    assert orchestrator.execute_step_calls[0]["control"] is control


@pytest.mark.asyncio
async def test_function_calling_handler_passes_prompt_workspace_to_execute_with_tools() -> None:
    orchestrator = _FakeOrchestrator(step_results=[])
    deps = ChatHandlerDependencies(
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        planning_service=SimpleNamespace(),
        function_calling_orchestrator=orchestrator,
        task_orchestrator=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        model_context_provider=lambda: unknown_model_context(None),
        agent_id="s-chat",
        get_task_agent_manager=lambda: None,
        session_run_coordinator=None,
    )
    handler = FunctionCallingHandler(deps)
    context = _make_context(
        active_run=None, revision=0, latest_user_message="Inspect the login flow."
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == "tool result"
    assert orchestrator.execute_with_tools_calls[0]["execution_workspace"] == "/tmp/magi"


@pytest.mark.asyncio
async def test_function_calling_handler_passes_prompt_workspace_to_checkpoint_fallback() -> None:
    coordinator = SessionRunCoordinator()
    first_turn = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )
    orchestrator = _FakeOrchestrator(
        step_results=[FunctionCallingStepOutcome(status="continue", iteration=10)]
    )
    handler = _make_handler(orchestrator, coordinator)
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == "fallback result"
    assert orchestrator.fallback_calls[0]["execution_workspace"] == "/tmp/magi"
    assert orchestrator.prepare_context_include_tools[-1] is False
