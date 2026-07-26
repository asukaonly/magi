from __future__ import annotations

from collections import deque

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.chat.task_agent.interruption_classifier import InterruptionDisposition
from magi.chat.task_agent.postprocess.constants import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.agent.task_agents.common import ExecutionMode, IncomingFactKind
from magi.events.events import EventTypes
from magi.memory import UnifiedMemoryStore
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
    """Force a scripted disposition so the interruption test exercises
    the coordinator routing logic without depending on a real LLM.

    Phase H6 sync ``InterruptionClassifier.classify`` is strict-only,
    so AUGMENT decisions are only reachable via the LLM-backed async
    path. These integration tests use a ``_FakeLLMAdapter`` with no
    provider, which makes ``aclassify`` fall back to the sync path.
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
    # Each session needs AUGMENT for the second user turn so the
    # checkpoint correctly merges; the first turn opens a fresh run and
    # bypasses the classifier entirely.
    agent_a._session_run_coordinator._interruption_classifier = _StubInterruptionClassifier(
        [InterruptionDisposition.AUGMENT]
    )
    agent_b._session_run_coordinator._interruption_classifier = _StubInterruptionClassifier(
        [InterruptionDisposition.AUGMENT]
    )
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
        content="Instead of the login flow, inspect the signup flow.",
        turn_id="turn-a2",
    )
    augment_b = _user_fact(
        session_id="session-b",
        content="Instead of the billing flow, inspect the refund flow.",
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
        "Inspect the login flow.\n\nInstead of the login flow, inspect the signup flow."
    )
    assert checkpoint_b.latest_user_message == (
        "Inspect the billing flow.\n\nInstead of the billing flow, inspect the refund flow."
    )
    assert seen_messages == [
        ("session-a", "Inspect the login flow."),
        ("session-b", "Inspect the billing flow."),
        ("session-a", "Inspect the login flow.\n\nInstead of the login flow, inspect the signup flow."),
        ("session-b", "Inspect the billing flow.\n\nInstead of the billing flow, inspect the refund flow."),
    ]


@pytest.mark.asyncio
async def test_interruptible_chat_does_not_restore_pending_turns_from_l0_checkpoint(
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
    agent._session_run_coordinator._interruption_classifier = _StubInterruptionClassifier(
        [InterruptionDisposition.AUGMENT]
    )
    first_fact = _user_fact(session_id="session-a", content="Inspect the login flow.", turn_id="turn-a1")
    augment_fact = _user_fact(
        session_id="session-a",
        content="Instead of the login flow, inspect the signup flow.",
        turn_id="turn-a2",
    )

    first_context = await agent.build_context(await agent.merge_facts([first_fact]))
    assert first_context.latest_user_message == "Inspect the login flow."

    augment_context = await agent.build_context(await agent.merge_facts([augment_fact]))
    assert augment_context.planner_fact_kind == IncomingFactKind.OTHER_FACT

    await memory.l0.checkpoint_all()  # type: ignore[union-attr]
    await memory.shutdown()

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
    try:
        restored_agent = ChatTaskAgent(
            agent_id="session-a",
            llm_adapter=_FakeLLMAdapter(),
            unified_memory=restored_memory,
        )

        checkpoint_context = await restored_agent.build_context(
            await restored_agent.merge_facts([_tool_loop_fact(session_id="session-a")])
        )

        assert checkpoint_context.planner_fact_kind == IncomingFactKind.OTHER_FACT
        assert restored_agent._session_run_coordinator._run_store.get_active_run(
            "session-a"
        ) is None
    finally:
        await restored_memory.shutdown()
