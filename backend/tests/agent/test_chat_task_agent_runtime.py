from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.chat.task_agent.interruption_classifier import InterruptionDisposition
from magi.chat.task_agent.postprocess.constants import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.chat.task_agent import chat_task_agent as chat_task_agent_module
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent, _format_llm_error
from magi.agent.task_agents.common import ExecutionMode, IncomingFactKind
from magi.chat import ChatStore
from magi.events.events import EventTypes
from magi.tools.context_routing import RouteDecision


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


def _make_decision(user_message: str) -> RouteDecision:
    return RouteDecision(
        profile="chat",
        graph_shape="reply",
        complexity="simple",
        tools=[],
        reasoning=f"route:{user_message}",
        memory_route="none",
    )


class _StubInterruptionClassifier:
    """Forces the bound :class:`SessionRunCoordinator` to apply a scripted
    interruption disposition.

    Phase H6 made the sync ``InterruptionClassifier.classify`` strict
    (only full-message matches against ``interruption_phrases.yaml``
    yield INTERRUPT; everything else returns DEFER). These runtime tests
    target the *agent* end-to-end flow for AUGMENT / INTERRUPT cases
    without spinning up a real LLM, so they swap in this stub.
    """

    def __init__(self, dispositions: list[InterruptionDisposition]) -> None:
        self._queue: deque[InterruptionDisposition] = deque(dispositions)
        self._last: InterruptionDisposition = InterruptionDisposition.DEFER

    def classify(self, context):  # type: ignore[no-untyped-def]
        _ = context
        if self._queue:
            self._last = self._queue.popleft()
        return self._last

    async def aclassify(self, context):  # type: ignore[no-untyped-def]
        return self.classify(context)

    def looks_like_strict_interrupt(self, user_text: str) -> bool:
        _ = user_text
        return False


def _user_fact(content: str, *, turn_id: str) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": content,
            "turn_id": turn_id,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"corr-{turn_id}",
    )


def _tool_loop_fact(*, revision: int = 0) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "stage": "tool_result",
            "response_preview": "tool checkpoint",
            "run_revision": revision,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"tool-{revision}",
    )


def test_chat_task_agent_streaming_enabled_reads_streaming_preference(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_get_user_preference(key: str, default: object = None) -> object:
        calls.append((key, default))
        return False

    monkeypatch.setattr(chat_task_agent_module, "get_user_preference", fake_get_user_preference)
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    assert agent._streaming_enabled("u-chat") is False
    assert calls == [("streaming_chat_enabled", False)]


def test_chat_task_agent_disables_streaming_when_rhythm_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        chat_task_agent_module,
        "get_user_preference",
        lambda key, default=None: True if key == "streaming_chat_enabled" else default,
    )
    monkeypatch.setattr(chat_task_agent_module, "is_conversation_rhythm_enabled", lambda: True)
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    assert agent._streaming_enabled("u-chat") is False


@pytest.mark.asyncio
async def test_chat_task_agent_uses_injected_chat_read_service_for_workspace() -> None:
    class _FakeSessionSummary:
        workspace_path = "/tmp/magi-workspace"

    class _FakeReadService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def aget_session_summary(self, user_id: str, session_id: str):
            self.calls.append((user_id, session_id))
            return _FakeSessionSummary()

    read_service = _FakeReadService()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        chat_read_service_factory=lambda: read_service,
    )

    workspace_path = await agent._resolve_session_workspace_path(user_id="u-chat", session_id="s-chat")

    assert workspace_path == "/tmp/magi-workspace"
    assert read_service.calls == [("u-chat", "s-chat")]


@pytest.mark.asyncio
async def test_chat_task_agent_prefers_user_fact_over_tool_loop_trace_in_mixed_batch(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    seen_messages: list[str] = []

    async def _fake_decide(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        seen_messages.append(user_message)
        return _make_decision(user_message)

    monkeypatch.setattr(agent.context_decider, "decide", _fake_decide)
    user_fact = _user_fact("Help me inspect the login flow.", turn_id="turn-1")
    tool_loop_fact = _tool_loop_fact()

    merged = await agent.merge_facts([user_fact, tool_loop_fact])
    context = await agent.build_context(merged)
    decision = await agent.match_intent(context)

    assert context.latest_fact == tool_loop_fact
    assert context.planner_fact == user_fact
    assert context.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert context.latest_user_message == "Help me inspect the login flow."
    assert decision.execution_mode == ExecutionMode.DIRECT_LLM
    assert seen_messages == ["Help me inspect the login flow."]


@pytest.mark.asyncio
async def test_chat_task_agent_routes_pending_augment_into_next_checkpoint(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # The sync InterruptionClassifier only emits INTERRUPT / DEFER. Force
    # AUGMENT so the coordinator queues the second turn for checkpoint
    # merging instead of dropping it as a deferred turn.
    agent._session_run_coordinator._interruption_classifier = _StubInterruptionClassifier(
        [InterruptionDisposition.AUGMENT]
    )
    seen_messages: list[str] = []

    async def _fake_decide(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        seen_messages.append(user_message)
        return _make_decision(user_message)

    monkeypatch.setattr(agent.context_decider, "decide", _fake_decide)
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    await agent.match_intent(first_context)

    augment_fact = _user_fact("Instead of the login flow, inspect the signup flow.", turn_id="turn-2")
    augment_context = await agent.build_context(await agent.merge_facts([augment_fact]))

    assert augment_context.planner_fact_kind == IncomingFactKind.OTHER_FACT
    assert augment_context.session_run_id
    assert [item.content for item in augment_context.pending_turns] == [
        "Instead of the login flow, inspect the signup flow."
    ]

    checkpoint_fact = _tool_loop_fact()
    checkpoint_context = await agent.build_context(await agent.merge_facts([checkpoint_fact]))
    checkpoint_decision = await agent.match_intent(checkpoint_context)

    assert checkpoint_context.planner_fact == checkpoint_fact
    assert checkpoint_context.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert checkpoint_context.latest_user_message == "\n\n".join(
        [
            "Inspect the login flow.",
            "Instead of the login flow, inspect the signup flow.",
        ]
    )
    assert checkpoint_decision.execution_mode == ExecutionMode.DIRECT_LLM
    assert seen_messages == [
        "Inspect the login flow.",
        "Inspect the login flow.\n\nInstead of the login flow, inspect the signup flow.",
    ]


@pytest.mark.asyncio
async def test_chat_task_agent_marks_augmented_turn_as_merged(
    runtime_paths_with_schema, monkeypatch
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="Inspect the login flow.",
        created_at_ms=100,
    )
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-2",
        message_text="Instead of the login flow, inspect the signup flow.",
        created_at_ms=200,
    )
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter(), chat_store=chat_store)
    agent._session_run_coordinator._interruption_classifier = _StubInterruptionClassifier(
        [InterruptionDisposition.AUGMENT]
    )

    async def _fake_decide(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        return _make_decision(user_message)

    monkeypatch.setattr(agent.context_decider, "decide", _fake_decide)
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    await agent.match_intent(first_context)

    augment_fact = _user_fact("Instead of the login flow, inspect the signup flow.", turn_id="turn-2")
    await agent.build_context(await agent.merge_facts([augment_fact]))

    checkpoint_fact = _tool_loop_fact()
    await agent.build_context(await agent.merge_facts([checkpoint_fact]))

    first_turn = await chat_store.get_turn("turn-1")
    assert first_turn is not None
    assert first_turn.status == "merged"
    assert first_turn.response_anchor_turn_id == "turn-2"
    assert first_turn.superseded_by_turn_id == "turn-2"
    assert first_turn.supersession_reason == "merged"


@pytest.mark.asyncio
async def test_chat_task_agent_marks_interrupted_turn_as_interrupted(
    runtime_paths_with_schema,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="Inspect the login flow.",
        created_at_ms=100,
    )
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-2",
        message_text="Stop and change the goal to checkout.",
        created_at_ms=200,
    )
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter(), chat_store=chat_store)
    # Phase H6 sync InterruptionClassifier only matches the strict
    # cancel-phrase list; "Stop and change the goal..." no longer
    # qualifies. Force INTERRUPT so this test still exercises the
    # interrupt-supersession bookkeeping path.
    agent._session_run_coordinator._interruption_classifier = _StubInterruptionClassifier(
        [InterruptionDisposition.INTERRUPT]
    )

    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    await agent.build_context(await agent.merge_facts([first_fact]))

    interrupt_fact = _user_fact("Stop and change the goal to checkout.", turn_id="turn-2")
    await agent.build_context(await agent.merge_facts([interrupt_fact]))

    first_turn = await chat_store.get_turn("turn-1")
    assert first_turn is not None
    assert first_turn.status == "interrupted"
    assert first_turn.response_anchor_turn_id == "turn-2"
    assert first_turn.superseded_by_turn_id == "turn-2"
    assert first_turn.supersession_reason == "interrupted"


# ---------------------------------------------------------------------------
# _format_llm_error helpers
# ---------------------------------------------------------------------------


class _FakeRateLimitError(Exception):
    def __init__(self) -> None:
        super().__init__("Error code: 429 - {'error': {'code': '1302', 'message': '速率限制'}}")
        self.status_code = 429


class _FakeAuthError(Exception):
    def __init__(self) -> None:
        super().__init__("Error code: 401 - Unauthorized")
        self.status_code = 401


class _FakeServerError(Exception):
    def __init__(self) -> None:
        super().__init__("Error code: 503 - Service Unavailable")
        self.status_code = 503


def test_format_llm_error_rate_limit() -> None:
    msg = _format_llm_error(_FakeRateLimitError())
    assert "rate" in msg.lower() or "限" in msg


def test_format_llm_error_auth() -> None:
    msg = _format_llm_error(_FakeAuthError())
    assert "auth" in msg.lower() or "api key" in msg.lower()


def test_format_llm_error_server() -> None:
    msg = _format_llm_error(_FakeServerError())
    assert "unavailable" in msg.lower() or "later" in msg.lower()


def test_format_llm_error_generic() -> None:
    msg = _format_llm_error(ValueError("something went wrong"))
    assert "ValueError" in msg


# ---------------------------------------------------------------------------
# call_llm emits error stream chunk on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_emits_error_chunk_on_failure(monkeypatch) -> None:
    """When _coordinator.execute raises, call_llm must still return a terminal result.

    The result goes through the normal postprocess path so the session run can
    be finalized instead of leaving the turn stuck in `running`.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    monkeypatch.setattr(
        chat_task_agent_module,
        "get_user_preference",
        lambda key, default=None: key == "streaming_chat_enabled",
    )
    monkeypatch.setattr(chat_task_agent_module, "is_conversation_rhythm_enabled", lambda: False)

    emitted: list[dict] = []

    async def _fake_emit(*, event, user_id, session_id, turn_id, **_kwargs):
        emitted.append({"kind": event.kind, "text": event.text})

    monkeypatch.setattr(agent, "_emit_stream_event", _fake_emit)

    class _FakeCoordinator:
        async def execute(self, _params):
            raise _FakeRateLimitError()

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind

    ctx = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-test",
        history_key="u-chat:s-test",
        history=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=SimpleNamespace(turn_id="turn-x"),
        conversation_history=[],
        active_orchestrations=[],
    )

    result = await agent.call_llm(ctx, SimpleNamespace(mode=ExecutionMode.DIRECT_LLM))

    assert len(emitted) == 2
    assert emitted[0]["kind"] == "text_delta"
    assert "rate" in emitted[0]["text"].lower()
    assert emitted[1]["kind"] == "text_flush"
    assert result.response_text == emitted[0]["text"]
    assert result.streamed is True


@pytest.mark.asyncio
async def test_call_llm_does_not_emit_error_chunk_when_streaming_disabled(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    monkeypatch.setattr(
        chat_task_agent_module,
        "get_user_preference",
        lambda key, default=None: False,
    )

    emitted: list[dict] = []

    async def _fake_emit(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(agent, "_emit_stream_event", _fake_emit)

    class _FakeCoordinator:
        async def execute(self, _params):
            raise _FakeRateLimitError()

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind

    ctx = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-test",
        history_key="u-chat:s-test",
        history=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=SimpleNamespace(turn_id="turn-x"),
        conversation_history=[],
        active_orchestrations=[],
    )

    result = await agent.call_llm(ctx, SimpleNamespace(mode=ExecutionMode.DIRECT_LLM))

    assert emitted == []
    assert "rate" in result.response_text.lower()
    assert result.streamed is False


@pytest.mark.asyncio
async def test_call_llm_skips_emit_when_no_turn_id(monkeypatch) -> None:
    """If turn_id is missing, no stream chunk is emitted (avoids noisy errors)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    emitted: list[dict] = []

    async def _fake_emit(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(agent, "_emit_stream_event", _fake_emit)

    class _FakeCoordinator:
        async def execute(self, _params):
            raise RuntimeError("boom")

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind

    ctx = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-test",
        history_key="u-chat:s-test",
        history=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=SimpleNamespace(turn_id=""),
        conversation_history=[],
        active_orchestrations=[],
    )

    result = await agent.call_llm(ctx, SimpleNamespace(mode=ExecutionMode.DIRECT_LLM))

    assert emitted == []
    assert "RuntimeError" in result.response_text
    assert result.streamed is False


@pytest.mark.asyncio
async def test_failed_llm_turn_is_finalized_before_next_user_message(monkeypatch) -> None:
    """A failed first turn must not leave the active run open for turn two.

    Regression: when `call_llm` re-raised, `TaskAgent._run_loop` swallowed the
    exception before `parse_result` ran, so `ChatPostProcessService` never
    called `complete_session_run(...)`. The next user message then revised the
    old run instead of starting a fresh one.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    class _FakeEmitter:
        async def emit_chat_response_event(self, **kwargs):  # type: ignore[no-untyped-def]
            return None

    class _FakeCoordinator:
        async def execute(self, _params):
            raise RuntimeError("boom")

    agent._event_emitter = _FakeEmitter()  # type: ignore[assignment]
    agent._coordinator = _FakeCoordinator()

    first_fact = _user_fact("你是谁", turn_id="turn-1")
    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    assert first_context.session_run_id is not None

    result = await agent.call_llm(
        first_context,
        SimpleNamespace(mode=ExecutionMode.DIRECT_LLM),
    )
    await agent.parse_result(first_context, result)

    # The failed turn is fully finalized, so there is no active run left.
    assert agent._session_run_coordinator.get_active_run("s-chat") is None

    second_fact = _user_fact("你到底是谁", turn_id="turn-2")
    second_context = await agent.build_context(await agent.merge_facts([second_fact]))

    # The second message starts a fresh run rather than revising turn-1.
    assert second_context.session_run_id is not None
    assert second_context.session_run_id != first_context.session_run_id
    assert second_context.active_run is not None
    assert second_context.active_run.root_turn_id == "turn-2"


@pytest.mark.asyncio
async def test_add_fact_ingress_interrupt_requests_cancel_on_active_run() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # Prime an active run as if a turn is in flight.
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )
    assert agent._session_run_coordinator.get_active_run("s-chat").status == "running"

    # Enqueue a fact whose normalized form exactly equals a cancel phrase.
    interrupt_fact = _user_fact("Stop!", turn_id="turn-interrupt")
    enqueued = await agent.add_fact(interrupt_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert active_run.status == "cancelling"
    assert active_run.cancel_requested_by == "user"
    assert active_run.cancel_reason == "ingress_interrupt"
    assert active_run.cancel_anchor_turn_id == "turn-interrupt"


@pytest.mark.asyncio
async def test_add_fact_ingress_interrupt_accepts_chinese_cancel_phrase() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )

    interrupt_fact = _user_fact("取消！", turn_id="turn-cancel")
    enqueued = await agent.add_fact(interrupt_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert active_run.status == "cancelling"


@pytest.mark.asyncio
async def test_add_fact_long_message_containing_stop_keyword_falls_through_to_llm() -> None:
    """Strict ingress matching must NOT trigger on substring keywords.

    A long message that merely mentions "stop" in passing should be enqueued
    normally and left for the LLM-backed classifier in ``ahandle_user_turn``
    to judge — not pre-emptively cancelled by the ingress fast path.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )

    passing_fact = _user_fact(
        "Please don't stop at the login page, also check the checkout flow.",
        turn_id="turn-passing",
    )
    enqueued = await agent.add_fact(passing_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    # The substring "stop" must not trigger cancellation.
    assert active_run.status == "running"
    assert active_run.cancel_requested_by is None


@pytest.mark.asyncio
async def test_add_fact_non_interrupt_does_not_cancel_active_run() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
            source="api",
        )  # type: ignore[arg-type]
    )

    augment_fact = _user_fact("Also, include the staging endpoint.", turn_id="turn-aug")
    enqueued = await agent.add_fact(augment_fact)

    assert enqueued is True
    active_run = agent._session_run_coordinator.get_active_run("s-chat")
    assert active_run is not None
    # AUGMENT must not hijack the cancellation path.
    assert active_run.status == "running"
    assert active_run.cancel_requested_by is None


@pytest.mark.asyncio
async def test_add_fact_ingress_interrupt_noop_when_no_active_run() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    # No active run exists; the ingress fast-path must stay silent and
    # simply enqueue the fact.
    interrupt_fact = _user_fact("stop", turn_id="turn-only")
    enqueued = await agent.add_fact(interrupt_fact)

    assert enqueued is True
    assert agent._session_run_coordinator.get_active_run("s-chat") is None


@pytest.mark.asyncio
async def test_drain_deferred_turns_mints_fresh_turn_id_for_reinjection() -> None:
    """Re-injected DEFER turns must not reuse the original ``turn_id``.

    The original ``turn_id`` is already persisted in L0 / chat history /
    timeline under the completed run. Reusing it when re-dispatching the
    pending turn as a brand-new user message would collide with those
    records and would also be picked up verbatim as the new run's
    ``root_turn_id`` by :meth:`SessionRunCoordinator._resolve_turn_id`. The
    fix mints a fresh UUID and keeps the original in
    ``payload.metadata.source_turn_id`` for traceability.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    captured_facts: list[FactRecord] = []

    class _CapturingManager:
        def current_user_message_generation(self) -> int:
            return 7

        async def add_fact_to_agent(self, agent_type, instance_id, fact):  # type: ignore[no-untyped-def]
            _ = (agent_type, instance_id)
            captured_facts.append(fact)

    agent._task_agent_manager = _CapturingManager()  # type: ignore[assignment]

    # Seed an active run and queue a DEFER pending turn with a known
    # original turn_id that must NOT be reused on re-injection.
    agent._session_run_coordinator.handle_user_turn(
        SimpleNamespace(
            user_id="u-chat",
            session_id="s-chat",
            content="Plan the refactor.",
            turn_id="turn-root",
            source="api",
        )  # type: ignore[arg-type]
    )
    agent._session_run_coordinator._run_store.append_pending_turn(
        "s-chat",
        "turn-deferred-original",
        "And also draft the release notes after.",
        disposition="defer",
    )

    await agent._drain_deferred_turns("s-chat")

    assert len(captured_facts) == 1
    fact = captured_facts[0]
    assert isinstance(fact.payload, dict)
    reinjected_turn_id = fact.payload["turn_id"]
    assert isinstance(reinjected_turn_id, str) and reinjected_turn_id
    assert reinjected_turn_id != "turn-deferred-original"
    assert fact.correlation_id == reinjected_turn_id
    metadata = fact.payload["metadata"]
    assert metadata["reinjected_from"] == "deferred_pending_turn"
    assert metadata["source_turn_id"] == "turn-deferred-original"
    assert fact.payload["content"] == "And also draft the release notes after."
    assert fact.user_message_generation == 7
