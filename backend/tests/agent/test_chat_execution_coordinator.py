from __future__ import annotations

import pytest

from magi.agent.task_agents.chat import ChatRuntimeContext, ExecutionMode, UserMessagePayload
from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.chat.fact_classifier import ChatFactClassifier, IncomingFactKind
from magi.agent.task_agents.chat.handlers import ExecutionHandlerRegistry
from magi.agent.runtime.contracts import FactRecord
from magi.events.events import EventTypes


class _FakeContextDecision:
    def __init__(
        self,
        *,
        intent: str,
        tools: list[str],
        deep_thinking: bool,
        reasoning: str,
        orchestration_strategy: dict,
        memory_route: str = "none",
        memory_query_hint: dict | None = None,
        llm_trace: dict | None = None,
    ):
        self.intent = intent
        self.tools = tools
        self.deep_thinking = deep_thinking
        self.reasoning = reasoning
        self.orchestration_strategy = orchestration_strategy
        self.memory_route = memory_route
        self.memory_query_hint = memory_query_hint
        self.llm_trace = llm_trace or {}


class _FakeContextDecider:
    def __init__(self, decision: _FakeContextDecision) -> None:
        self._decision = decision
        self.last_decision_context = None

    async def decide(self, user_message: str, decision_context: dict):  # type: ignore[no-untyped-def]
        _ = user_message
        self.last_decision_context = decision_context
        return self._decision


class _IntentTraceRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, context: ChatRuntimeContext, decision) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "user_id": context.user_id,
                "session_id": context.session_id,
                "intent": decision.intent,
                "execution_mode": decision.execution_mode.value,
                "tools": list(decision.tools),
                "reasoning": decision.reasoning,
            }
        )


@pytest.mark.asyncio
async def test_coordinator_routes_decompose_explore_to_orchestration_launch() -> None:
    trace_recorder = _IntentTraceRecorder()
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
        intent_trace_callback=trace_recorder,
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "分析代码架构"},
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
    assert trace_recorder.calls == [
        {
            "user_id": "u-chat",
            "session_id": "s-chat",
            "intent": "code_architecture",
            "execution_mode": "orchestration_launch",
            "tools": ["agent"],
            "reasoning": "decompose",
        }
    ]


@pytest.mark.asyncio
async def test_coordinator_carries_intent_llm_trace_metrics() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="chat",
                tools=[],
                deep_thinking=False,
                reasoning="direct response",
                orchestration_strategy={
                    "mode": "direct",
                    "planner": "task_agent",
                    "default_leaf_type": "general-purpose",
                    "allow_parallel": False,
                },
                llm_trace={
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "input_tokens": 48,
                    "output_tokens": 12,
                    "total_tokens": 60,
                    "reasoning_tokens": 0,
                    "thinking_enabled": False,
                    "duration_ms": 310,
                },
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "你好"},
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
        latest_user_message="你好",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.llm_trace["provider"] == "openai"
    assert decision.llm_trace["model"] == "gpt-4.1-mini"
    assert decision.llm_trace["input_tokens"] == 48
    assert decision.llm_trace["output_tokens"] == 12
    assert decision.llm_trace["duration_ms"] == 310
    assert decision.ux_plan.assistant_surface_mode.value == "final_only"
    assert decision.ux_plan.thinking_indicator.value == "hidden"
    assert decision.ux_plan.trace_display_mode.value == "none"


@pytest.mark.asyncio
async def test_coordinator_excludes_latest_user_message_from_recent_messages_context() -> None:
    fake_decider = _FakeContextDecider(
        _FakeContextDecision(
            intent="chat",
            tools=[],
            deep_thinking=False,
            reasoning="direct response",
            orchestration_strategy={
                "mode": "direct",
                "planner": "task_agent",
                "default_leaf_type": "general-purpose",
                "allow_parallel": False,
            },
        )
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=fake_decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "你是谁啊"},
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
        history=[{"role": "user", "content": "你是谁啊"}],
        conversation_history=[{"role": "user", "content": "你是谁啊"}],
        active_orchestrations=[],
        latest_user_message="你是谁啊",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    await coordinator.match_intent(context)

    assert fake_decider.last_decision_context is not None
    assert fake_decider.last_decision_context["recent_messages"] == []


@pytest.mark.asyncio
async def test_coordinator_routes_decompose_without_agent_tool_to_orchestration_launch() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="code_analysis",
                tools=["grep", "file_read", "glob"],
                deep_thinking=True,
                reasoning="multi-step analysis should decompose",
                orchestration_strategy={
                    "mode": "decompose",
                    "planner": "task_agent",
                    "default_leaf_type": "general-purpose",
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
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "具体是什么代码导致的"},
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
        latest_user_message="具体是什么代码导致的",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert decision.ux_plan.assistant_surface_mode.value == "interim_then_final"
    assert decision.ux_plan.trace_display_mode.value == "collapsible"
    assert decision.ux_plan.interim_text


@pytest.mark.asyncio
async def test_coordinator_routes_complex_news_to_generic_orchestration_without_explore() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="planning",
                tools=["web-search", "web-fetch"],
                deep_thinking=True,
                reasoning="complex research",
                orchestration_strategy={
                    "mode": "decompose",
                    "planner": "task_agent",
                    "default_leaf_type": "general-purpose",
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
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "搜一下最近7天杭州有什么重要的新闻，给我来10条"},
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
        latest_user_message="搜一下最近7天杭州有什么重要的新闻，给我来10条",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert decision.orchestration_plan is not None
    assert decision.orchestration_plan.default_leaf_type == "general-purpose"
    assert decision.orchestration_plan.route_to_explore_task_agent is False


@pytest.mark.asyncio
async def test_coordinator_passes_recent_tool_errors_to_context_decider() -> None:
    fake_decider = _FakeContextDecider(
        _FakeContextDecision(
            intent="chat",
            tools=[],
            deep_thinking=False,
            reasoning="follow-up",
            orchestration_strategy={
                "mode": "direct",
                "planner": "task_agent",
                "default_leaf_type": "general-purpose",
                "allow_parallel": False,
            },
        )
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=fake_decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "要配什么key"},
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
        recent_tool_errors=[
            {
                "tool_name": "weather",
                "error_code": "PROVIDER_NOT_CONFIGURED",
                "error_message": "Missing API key",
                "config_path": "tool.weather.providers.qweather.api_key",
            }
        ],
        latest_user_message="要配什么key",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    await coordinator.match_intent(context)

    assert fake_decider.last_decision_context is not None
    assert fake_decider.last_decision_context["recent_tool_errors"][0]["config_path"] == (
        "tool.weather.providers.qweather.api_key"
    )


@pytest.mark.asyncio
async def test_coordinator_marks_tool_query_as_collapsible_trace_ui() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="weather_query",
                tools=["weather"],
                deep_thinking=False,
                reasoning="tool required",
                orchestration_strategy={
                    "mode": "direct",
                    "planner": "task_agent",
                    "default_leaf_type": "general-purpose",
                    "allow_parallel": False,
                },
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "杭州天气怎么样"},
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
        latest_user_message="杭州天气怎么样",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.FUNCTION_CALLING
    assert decision.ux_plan.assistant_surface_mode.value == "final_only"
    assert decision.ux_plan.trace_display_mode.value == "collapsible"
    assert decision.ux_plan.allow_trace_collapse is True


@pytest.mark.asyncio
async def test_coordinator_marks_acknowledgement_as_reaction_only_ui() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="small_ack",
                tools=[],
                deep_thinking=False,
                reasoning="acknowledgement",
                orchestration_strategy={
                    "mode": "direct",
                    "planner": "task_agent",
                    "default_leaf_type": "general-purpose",
                    "allow_parallel": False,
                },
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "嗯"},
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
        latest_user_message="嗯",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.DIRECT_LLM
    assert decision.ux_plan.assistant_surface_mode.value == "reaction_only"
    assert decision.ux_plan.reaction_style == "acknowledge"


@pytest.mark.asyncio
async def test_coordinator_forces_direct_llm_for_image_attachments() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            _FakeContextDecision(
                intent="screenshot_analysis",
                tools=["file_read"],
                deep_thinking=False,
                reasoning="tool required",
                orchestration_strategy={
                    "mode": "direct",
                    "planner": "task_agent",
                    "default_leaf_type": "general-purpose",
                    "allow_parallel": False,
                },
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": "这张图里是什么",
            "attachments": [{"attachment_id": "att-image", "kind": "image", "original_name": "diagram.png"}],
        },
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
        latest_user_message="这张图里是什么",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.DIRECT_LLM
