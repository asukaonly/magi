from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.chat.postprocess_service import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
from magi.agent.task_agents.common import ExecutionMode, IncomingFactKind
from magi.events.events import EventTypes
from magi.memory import UnifiedMemoryStore


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
        memory_query_hint=None,
        llm_trace={},
    )


def _user_fact(*, session_id: str, content: str, turn_id: str) -> FactRecord:
    return FactRecord(
        agent_id=f"chat:{session_id}",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "user-1",
            "session_id": session_id,
            "content": content,
            "turn_id": turn_id,
        },
        agent_type="chat",
        agent_instance_id=session_id,
        correlation_id=f"corr-{turn_id}",
    )


def _tool_loop_fact(*, session_id: str, revision: int = 0) -> FactRecord:
    return FactRecord(
        agent_id=f"chat:{session_id}",
        event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
        payload={
            "user_id": "user-1",
            "session_id": session_id,
            "stage": "tool_result",
            "response_preview": "tool checkpoint",
            "run_revision": revision,
        },
        agent_type="chat",
        agent_instance_id=session_id,
        correlation_id=f"tool-{session_id}-{revision}",
    )


@pytest.mark.asyncio
async def test_interruptible_chat_sessions_do_not_cross_streams_and_merge_at_own_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_a = ChatTaskAgent(agent_id="session-a", llm_adapter=_FakeLLMAdapter())
    agent_b = ChatTaskAgent(agent_id="session-b", llm_adapter=_FakeLLMAdapter())
    seen_messages: list[tuple[str, str]] = []

    async def _decide_a(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        seen_messages.append(("session-a", user_message))
        return _make_decision(user_message)

    async def _decide_b(user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = decision_context
        seen_messages.append(("session-b", user_message))
        return _make_decision(user_message)

    monkeypatch.setattr(agent_a.context_decider, "decide", _decide_a)
    monkeypatch.setattr(agent_b.context_decider, "decide", _decide_b)

    first_a = _user_fact(session_id="session-a", content="Inspect the login flow.", turn_id="turn-a1")
    first_b = _user_fact(session_id="session-b", content="Inspect the billing flow.", turn_id="turn-b1")

    context_a = await agent_a.build_context(await agent_a.merge_facts([first_a]))
    context_b = await agent_b.build_context(await agent_b.merge_facts([first_b]))

    decision_a = await agent_a.match_intent(context_a)
    decision_b = await agent_b.match_intent(context_b)

    assert decision_a.execution_mode == ExecutionMode.DIRECT_LLM
    assert decision_b.execution_mode == ExecutionMode.DIRECT_LLM

    augment_a = _user_fact(
        session_id="session-a",
        content="Also, use the staging endpoint.",
        turn_id="turn-a2",
    )
    augment_b = _user_fact(
        session_id="session-b",
        content="Also, include receipts.",
        turn_id="turn-b2",
    )

    augment_context_a = await agent_a.build_context(await agent_a.merge_facts([augment_a]))
    augment_context_b = await agent_b.build_context(await agent_b.merge_facts([augment_b]))

    assert augment_context_a.planner_fact_kind == IncomingFactKind.OTHER_FACT
    assert augment_context_b.planner_fact_kind == IncomingFactKind.OTHER_FACT

    checkpoint_a = await agent_a.build_context(
        await agent_a.merge_facts([_tool_loop_fact(session_id="session-a")])
    )
    checkpoint_b = await agent_b.build_context(
        await agent_b.merge_facts([_tool_loop_fact(session_id="session-b")])
    )

    decision_checkpoint_a = await agent_a.match_intent(checkpoint_a)
    decision_checkpoint_b = await agent_b.match_intent(checkpoint_b)

    assert decision_checkpoint_a.execution_mode == ExecutionMode.DIRECT_LLM
    assert decision_checkpoint_b.execution_mode == ExecutionMode.DIRECT_LLM
    assert checkpoint_a.latest_user_message == (
        "Inspect the login flow.\n\nAlso, use the staging endpoint."
    )
    assert checkpoint_b.latest_user_message == (
        "Inspect the billing flow.\n\nAlso, include receipts."
    )
    assert seen_messages == [
        ("session-a", "Inspect the login flow."),
        ("session-b", "Inspect the billing flow."),
        ("session-a", "Inspect the login flow.\n\nAlso, use the staging endpoint."),
        ("session-b", "Inspect the billing flow.\n\nAlso, include receipts."),
    ]


@pytest.mark.asyncio
async def test_interruptible_chat_recovers_pending_turns_from_l0_checkpoint(
    tmp_path,
) -> None:
    memory = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        enable_l0=True,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await memory.initialize()

    agent = ChatTaskAgent(
        agent_id="session-a",
        llm_adapter=_FakeLLMAdapter(),
        unified_memory=memory,
    )
    first_fact = _user_fact(session_id="session-a", content="Inspect the login flow.", turn_id="turn-a1")
    augment_fact = _user_fact(
        session_id="session-a",
        content="Also, use the staging endpoint.",
        turn_id="turn-a2",
    )

    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    assert first_context.latest_user_message == "Inspect the login flow."

    augment_context = await agent.build_context(await agent.merge_facts([augment_fact]))
    assert augment_context.planner_fact_kind == IncomingFactKind.OTHER_FACT

    await memory.l0.checkpoint_all()  # type: ignore[union-attr]

    restored_memory = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        enable_l0=True,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await restored_memory.initialize()
    restored_agent = ChatTaskAgent(
        agent_id="session-a",
        llm_adapter=_FakeLLMAdapter(),
        unified_memory=restored_memory,
    )

    checkpoint_context = await restored_agent.build_context(
        await restored_agent.merge_facts([_tool_loop_fact(session_id="session-a")])
    )

    assert checkpoint_context.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert checkpoint_context.latest_user_message == (
        "Inspect the login flow.\n\nAlso, use the staging endpoint."
    )
