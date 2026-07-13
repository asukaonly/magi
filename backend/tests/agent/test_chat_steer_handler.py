"""Tests for SteerInbox wiring inside :class:`FunctionCallingHandler`.

Covers the three handler-side behaviours introduced alongside the STEER
disposition:

- A ``SteerInbox`` is built on every chat turn when a session run
  coordinator is wired, and any STEER pending turns that were persisted
  while the backend was offline are hydrated into the inbox at turn start
  (restart recovery).
- Newly queued STEER pending turns are drained at the top of each
  checkpoint iteration and appended to ``state.messages`` via
  ``FunctionCallingOrchestrator.apply_steer_messages``, so the next LLM
  call sees the steer text without rebuilding the prompt from scratch.
- Draining STEER pending turns emits supersession bookkeeping
  (``root_turn + intermediate pending turns → newest drained turn``),
  matching the AUGMENT merge shape, via the ``persist_turn_supersessions``
  callable on :class:`ChatHandlerDependencies`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.agent.execution.function_calling.step_executor import (
    FunctionCallingStepOutcome,
    FunctionCallingStepState,
)
from magi.control.run_control import SteerInbox
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.handlers.handlers import (
    ChatHandlerDependencies,
    FunctionCallingHandler,
)
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.chat.task_agent.session_run_decisions import TurnSupersession
from magi.llm.model_context import unknown_model_context
from magi.agent.task_agents.common import (
    ExecutionMode,
    FunctionCallingRequest,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)


class _FakeOrchestrator:
    """Minimal orchestrator stand-in that exposes the step-executor path.

    Records every ``apply_steer_messages`` invocation so tests can assert
    the handler drained the inbox at the right iteration. ``_execute_step``
    runs an optional callback that lets tests inject a new STEER pending
    turn mid-run to exercise the per-iteration drain.
    """

    MAX_ITERATIONS = 10

    def __init__(
        self,
        *,
        step_results: list[FunctionCallingStepOutcome],
        on_step: Any = None,
    ) -> None:
        self.step_executor = SimpleNamespace(execute_step=self._execute_step)
        self._step_results = list(step_results)
        self._on_step = on_step
        self.build_step_state_calls: list[str] = []
        self.apply_steer_calls: list[list[str]] = []

    def build_step_state(
        self,
        *,
        turn: Any,
        system_prompt: str,
        selected_tools: list[str],
        conversation_history: Any = None,
        session_summary: Any = None,
        session_origin: Any = None,
        reply_context: Any = None,
        allow_attachment_grounding: bool = False,
        ephemeral_context: Any = None,
        **kwargs: Any,
    ) -> FunctionCallingStepState:
        _ = (system_prompt, selected_tools, conversation_history, session_summary, session_origin, reply_context, allow_attachment_grounding, ephemeral_context, kwargs)
        self.build_step_state_calls.append(turn.text)
        return FunctionCallingStepState(
            messages=[{"role": "user", "content": turn.text}],
            effective_system_prompt="system prompt",
            tools=[],
        )

    async def _execute_step(self, **kwargs: Any) -> FunctionCallingStepOutcome:
        state = kwargs["state"]
        if self._on_step is not None:
            maybe_awaitable = self._on_step(state)
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable
        outcome = self._step_results.pop(0)
        state.iteration = outcome.iteration
        return outcome

    async def apply_steer_messages(
        self, state: FunctionCallingStepState, steer_inbox: SteerInbox
    ) -> None:
        drained = await steer_inbox.drain()
        injected_contents: list[str] = []
        for message in drained:
            content = (message.content or "").strip()
            if not content:
                continue
            state.messages.append({"role": "user", "content": content})
            injected_contents.append(content)
        self.apply_steer_calls.append(injected_contents)

    async def _prepare_context_for_model(
        self,
        state: FunctionCallingStepState,
    ) -> None:
        return None


def _make_context(
    *,
    active_run: Any,
    revision: int,
    latest_user_message: str,
) -> ChatRuntimeContext:
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
        prompt_context=SimpleNamespace(
            runtime_system=SimpleNamespace(cwd="/tmp/magi")
        ),
        system_prompt="system prompt",
        selected_tools=["memory_query"],
    )


def _make_handler(
    orchestrator: _FakeOrchestrator,
    coordinator: SessionRunCoordinator,
    *,
    persist_turn_supersessions: Any = None,
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
        persist_turn_supersessions=persist_turn_supersessions,
    )
    return FunctionCallingHandler(deps)


@pytest.mark.asyncio
async def test_steer_turn_queued_before_execution_is_hydrated_at_turn_start() -> None:
    """Persisted STEER turns must land in the inbox before the first step.

    Simulates the restart-recovery case: a STEER pending turn is queued
    on the coordinator *before* the handler starts executing, and must
    be drained+applied before the very first LLM call.

    Post-H6, the sync interruption classifier only matches strict cancel
    phrases (everything else DEFERs); STEER is now assigned only via the
    async LLM classifier. The test seeds a STEER-disposition pending turn
    directly on the run store so we exercise the handler-side drain path
    without depending on classifier internals.
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
    coordinator._run_store.append_pending_turn(
        "s-chat",
        "turn-2",
        "Also, use the staging endpoint.",
        disposition="steer",
    )

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(
                status="completed", iteration=1, content="final"
            ),
        ]
    )
    supersession_calls: list[tuple[list[TurnSupersession], int]] = []

    async def _capture_supersessions(
        superseded_turns: list[TurnSupersession], updated_at_ms: int
    ) -> None:
        supersession_calls.append((superseded_turns, updated_at_ms))

    handler = _make_handler(
        orchestrator,
        coordinator,
        persist_turn_supersessions=_capture_supersessions,
    )
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == "final"
    # Hydration at turn start drained the STEER pending turn before the
    # first step ran.
    assert coordinator.peek_steer_turns("s-chat") == []
    # apply_steer_messages was called once at the top of iteration 0 with
    # the hydrated message.
    assert orchestrator.apply_steer_calls == [["Also, use the staging endpoint."]]
    # Supersession bookkeeping matches the AUGMENT merge shape: the root
    # turn is superseded by the newest STEER turn.
    assert len(supersession_calls) == 1
    (turns, _updated_at_ms) = supersession_calls[0]
    assert [(t.turn_id, t.anchor_turn_id, t.reason) for t in turns] == [
        ("turn-1", "turn-2", "steer"),
    ]


@pytest.mark.asyncio
async def test_steer_turn_arriving_mid_run_is_drained_on_next_iteration() -> None:
    """STEER turns queued while a tool batch is running must be drained
    at the top of the next checkpoint iteration, not deferred to the end.
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

    def _queue_steer_after_first_step(state: FunctionCallingStepState) -> None:
        # Only queue once, after the first continue step completes.
        # Post-H6, STEER is set only by the async LLM classifier; we seed
        # the disposition directly on the run store to keep the test
        # focused on handler-side drain behaviour.
        if len(state.messages) == 1:
            coordinator._run_store.append_pending_turn(
                "s-chat",
                "turn-2",
                "Also, use the staging endpoint.",
                disposition="steer",
            )

    orchestrator = _FakeOrchestrator(
        step_results=[
            FunctionCallingStepOutcome(status="continue", iteration=1),
            FunctionCallingStepOutcome(
                status="completed", iteration=2, content="final"
            ),
        ],
        on_step=_queue_steer_after_first_step,
    )
    supersession_calls: list[tuple[list[TurnSupersession], int]] = []

    async def _capture_supersessions(
        superseded_turns: list[TurnSupersession], updated_at_ms: int
    ) -> None:
        supersession_calls.append((superseded_turns, updated_at_ms))

    handler = _make_handler(
        orchestrator,
        coordinator,
        persist_turn_supersessions=_capture_supersessions,
    )
    context = _make_context(
        active_run=first_turn.active_run,
        revision=first_turn.active_run.revision,
        latest_user_message="Inspect the login flow.",
    )

    result = await handler.execute(_make_request(context))

    assert result.response_text == "final"
    # Iteration 0: inbox is empty (no hydration) → empty drain.
    # Iteration 1: the STEER turn queued after the first step is drained
    # and applied before the second step runs.
    assert orchestrator.apply_steer_calls == [
        [],
        ["Also, use the staging endpoint."],
    ]
    # Supersession emitted once, only for the iteration that drained
    # non-empty turns.
    assert len(supersession_calls) == 1
    (turns, _updated_at_ms) = supersession_calls[0]
    assert [(t.turn_id, t.anchor_turn_id, t.reason) for t in turns] == [
        ("turn-1", "turn-2", "steer"),
    ]


@pytest.mark.asyncio
async def test_no_steer_drain_when_coordinator_is_absent() -> None:
    """Handler must tolerate missing coordinator — plain path only."""
    deps = ChatHandlerDependencies(
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        planning_service=SimpleNamespace(),
        function_calling_orchestrator=SimpleNamespace(
            execute_with_tools=lambda **_: SimpleNamespace(
                content="final",
                to_dict=lambda: {"status": "completed", "content": "final"},
            )
        ),
        task_orchestrator=SimpleNamespace(),
        context_assembler=SimpleNamespace(),
        model_context_provider=lambda: unknown_model_context(None),
        agent_id="s-chat",
        get_task_agent_manager=lambda: None,
        session_run_coordinator=None,
    )
    handler = FunctionCallingHandler(deps)

    # With no coordinator, _build_steer_inbox returns None and no drain
    # ever fires.
    inbox = await handler._build_steer_inbox(
        _make_request(
            _make_context(
                active_run=SimpleNamespace(run_id="run-1", revision=0),
                revision=0,
                latest_user_message="Inspect.",
            )
        )
    )
    assert inbox is None
