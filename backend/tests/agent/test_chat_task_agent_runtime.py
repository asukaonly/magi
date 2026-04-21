from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.chat.postprocess_service import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent, _format_llm_error
from magi.agent.task_agents.common import ExecutionMode, IncomingFactKind
from magi.chat import ChatStore
from magi.events.events import EventTypes


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


def _make_decision(user_message: str) -> SimpleNamespace:
    return SimpleNamespace(
        intent="chat",
        tools=[],
        deep_thinking=False,
        thinking_depth="none",
        reasoning=f"route:{user_message}",
        orchestration_strategy={
            "mode": "direct",
            "planner": "task_agent",
            "default_leaf_type": "general-purpose",
            "allow_parallel": False,
        },
        memory_route="none",
        routing_memory_hint=None,
        llm_trace={},
    )


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
    seen_messages: list[str] = []

    async def _fake_decide(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        seen_messages.append(user_message)
        return _make_decision(user_message)

    monkeypatch.setattr(agent.context_decider, "decide", _fake_decide)
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    await agent.match_intent(first_context)

    augment_fact = _user_fact("Also, use the staging endpoint.", turn_id="turn-2")
    augment_context = await agent.build_context(await agent.merge_facts([augment_fact]))

    assert augment_context.planner_fact_kind == IncomingFactKind.OTHER_FACT
    assert augment_context.session_run_id
    assert [item.content for item in augment_context.pending_turns] == [
        "Also, use the staging endpoint."
    ]

    checkpoint_fact = _tool_loop_fact()
    checkpoint_context = await agent.build_context(await agent.merge_facts([checkpoint_fact]))
    checkpoint_decision = await agent.match_intent(checkpoint_context)

    assert checkpoint_context.planner_fact == checkpoint_fact
    assert checkpoint_context.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert checkpoint_context.latest_user_message == "\n\n".join(
        [
            "Inspect the login flow.",
            "Also, use the staging endpoint.",
        ]
    )
    assert checkpoint_decision.execution_mode == ExecutionMode.DIRECT_LLM
    assert seen_messages == [
        "Inspect the login flow.",
        "Inspect the login flow.\n\nAlso, use the staging endpoint.",
    ]


@pytest.mark.asyncio
async def test_chat_task_agent_marks_augmented_turn_as_merged(tmp_path: Path, monkeypatch) -> None:
    chat_store = ChatStore(db_path=str(tmp_path / "chat.db"))
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
        message_text="Also, use the staging endpoint.",
        created_at_ms=200,
    )
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter(), chat_store=chat_store)

    async def _fake_decide(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        return _make_decision(user_message)

    monkeypatch.setattr(agent.context_decider, "decide", _fake_decide)
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    await agent.match_intent(first_context)

    augment_fact = _user_fact("Also, use the staging endpoint.", turn_id="turn-2")
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
async def test_chat_task_agent_marks_interrupted_turn_as_interrupted(tmp_path: Path) -> None:
    chat_store = ChatStore(db_path=str(tmp_path / "chat.db"))
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
    """When _coordinator.execute raises, call_llm must emit a terminal stream chunk."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    emitted: list[dict] = []

    async def _fake_emit(*, user_id, session_id, turn_id, content_delta, is_final, retract=False):
        emitted.append({"content_delta": content_delta, "is_final": is_final})

    monkeypatch.setattr(agent, "_emit_stream_chunk", _fake_emit)

    class _FakeCoordinator:
        async def execute(self, _params):
            raise _FakeRateLimitError()

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.chat.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind, GenericFactPayload

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

    with pytest.raises(_FakeRateLimitError):
        await agent.call_llm(ctx, SimpleNamespace())

    assert len(emitted) == 2
    assert emitted[0]["is_final"] is False
    assert "rate" in emitted[0]["content_delta"].lower()
    assert emitted[1]["is_final"] is True
    assert emitted[1]["content_delta"] == ""


@pytest.mark.asyncio
async def test_call_llm_skips_emit_when_no_turn_id(monkeypatch) -> None:
    """If turn_id is missing, no stream chunk is emitted (avoids noisy errors)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    emitted: list[dict] = []

    async def _fake_emit(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(agent, "_emit_stream_chunk", _fake_emit)

    class _FakeCoordinator:
        async def execute(self, _params):
            raise RuntimeError("boom")

    agent._coordinator = _FakeCoordinator()

    from magi.agent.task_agents.chat.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common.contracts import IncomingFactKind, GenericFactPayload

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

    with pytest.raises(RuntimeError):
        await agent.call_llm(ctx, SimpleNamespace())

    assert emitted == []


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

