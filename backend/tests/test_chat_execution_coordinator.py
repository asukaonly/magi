from __future__ import annotations

import pytest

from magi.agent.task_agents.chat import ChatRuntimeContext, ExecutionMode, UserMessagePayload
from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.chat.fact_classifier import ChatFactClassifier, IncomingFactKind
from magi.agent.task_agents.chat.handlers import ExecutionHandlerRegistry
from magi.core.runtime.contracts import FactRecord
from magi.events.events import EventTypes


class _FakeContextDecision:
    def __init__(self, *, intent: str, tools: list[str], deep_thinking: bool, reasoning: str, orchestration_strategy: dict):
        self.intent = intent
        self.tools = tools
        self.deep_thinking = deep_thinking
        self.reasoning = reasoning
        self.orchestration_strategy = orchestration_strategy


class _FakeContextDecider:
    def __init__(self, decision: _FakeContextDecision) -> None:
        self._decision = decision

    async def decide(self, user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = (user_message, decision_context)
        return self._decision


@pytest.mark.asyncio
async def test_coordinator_routes_decompose_explore_to_orchestration_launch() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="code_architecture",
                tools=["agent"],
                deep_thinking=False,
                reasoning="decompose",
                orchestration_strategy={
                    "mode": "decompose",
                    "planner": "task_agent",
                    "default_leaf_type": "Explore",
                    "allow_parallel": True,
                },
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "message": "分析代码架构"},
    )
    context = ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id="u-chat",
        agent_type="chat",
        runtime_key="chat:u-chat",
        user_id="u-chat",
        session_id="s-chat",
        history_key="u-chat::s-chat",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="分析代码架构",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert decision.orchestration_plan is not None
    assert decision.orchestration_plan.route_to_explore_task_agent is True
