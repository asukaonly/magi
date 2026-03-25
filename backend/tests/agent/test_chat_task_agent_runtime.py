from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.chat.postprocess_service import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
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
