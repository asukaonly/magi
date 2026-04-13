from __future__ import annotations

import pytest

from magi.agent.task_agents.chat import ChatRuntimeContext, ExecutionMode, UserMessagePayload
from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.chat.fact_classifier import ChatFactClassifier, IncomingFactKind
from magi.agent.task_agents.chat.handlers import ExecutionHandlerRegistry
from magi.agent.runtime.contracts import FactRecord
from magi.config.models import ThinkingDepth
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
        routing_memory_hint: dict | None = None,
        llm_trace: dict | None = None,
    ):
        self.intent = intent
        self.tools = tools
        self.deep_thinking = deep_thinking
        self.thinking_depth = ThinkingDepth.HIGH if deep_thinking else ThinkingDepth.NONE
        self.reasoning = reasoning
        self.orchestration_strategy = orchestration_strategy
        self.memory_route = memory_route
        self.routing_memory_hint = routing_memory_hint
        self.llm_trace = llm_trace or {}


class _FakeToolRegistry:
    """Minimal stub so the coordinator can call ``tool_registry.list_tools()``."""

    def __init__(self, tools: list[str] | None = None) -> None:
        self._tools = tools or []

    def list_tools(self) -> list[str]:
        return list(self._tools)


class _FakeContextDecider:
    def __init__(self, decision: _FakeContextDecision) -> None:
        self._decision = decision
        self.last_decision_context = None
        self.tool_registry = _FakeToolRegistry()

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
async def test_coordinator_builds_typed_routing_environment_context() -> None:
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
        latest_payload=UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="你好",
            workspace_path="/tmp/workspace",
            turn_id="turn-1",
        ),
    )

    await coordinator.match_intent(context)

    assert fake_decider.last_decision_context is not None
    assert fake_decider.last_decision_context["os_name"]
    assert fake_decider.last_decision_context["os_version"]
    assert fake_decider.last_decision_context["current_datetime"]
    assert fake_decider.last_decision_context["timezone"]
    assert fake_decider.last_decision_context["workspace_path"] == "/tmp/workspace"


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


@pytest.mark.asyncio
async def test_coordinator_injects_tool_advisory_into_decision_context() -> None:
    """Advisory provider should populate ContextDeciderContext.tool_advisory."""
    fake_advisories = [
        {"tool_name": "web_search", "available": True, "breaker_state": "closed",
         "success_rate": 0.8, "total_attempts": 5, "strategy_hint": "use quotes",
         "context_fit": None, "risk_note": None},
    ]

    async def advisory_provider(task_context=None):
        return fake_advisories

    decider = _FakeContextDecider(
        _FakeContextDecision(
            intent="realtime_query",
            tools=["web_search"],
            deep_thinking=False,
            reasoning="search",
            orchestration_strategy={"mode": "direct", "planner": "task_agent",
                                    "default_leaf_type": "general-purpose",
                                    "allow_parallel": False},
        )
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        tool_advisory_provider=advisory_provider,
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "search weather"},
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
        latest_user_message="search weather",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    await coordinator.match_intent(context)

    dc = decider.last_decision_context
    assert dc is not None
    assert hasattr(dc, "tool_advisory")
    assert dc.tool_advisory == fake_advisories


@pytest.mark.asyncio
async def test_coordinator_works_without_advisory_provider() -> None:
    """Coordinator should work fine when tool_advisory_provider is None."""
    decider = _FakeContextDecider(
        _FakeContextDecision(
            intent="chat",
            tools=[],
            deep_thinking=False,
            reasoning="greeting",
            orchestration_strategy={"mode": "direct", "planner": "task_agent",
                                    "default_leaf_type": "general-purpose",
                                    "allow_parallel": False},
        )
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        # no tool_advisory_provider
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "hey"},
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
        latest_user_message="hey",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)
    dc = decider.last_decision_context
    assert dc is not None
    assert dc.tool_advisory == []


@pytest.mark.asyncio
async def test_coordinator_injects_fallback_tools_when_tools_active() -> None:
    """web-search should be appended as a fallback when tool-calling is active."""
    decider = _FakeContextDecider(
        _FakeContextDecision(
            intent="code_execution",
            tools=["bash"],
            deep_thinking=False,
            reasoning="run command",
            orchestration_strategy={"mode": "direct", "planner": "task_agent",
                                    "default_leaf_type": "general-purpose",
                                    "allow_parallel": False},
        )
    )
    decider.tool_registry = _FakeToolRegistry(["bash", "web-search", "file_read"])

    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "查一下这个进程"},
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
        latest_user_message="查一下这个进程",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)
    assert "bash" in decision.tools
    assert "web-search" in decision.tools


@pytest.mark.asyncio
async def test_coordinator_does_not_inject_fallback_tools_for_chat() -> None:
    """Pure chat (no tools) should stay tool-free — no fallback injection."""
    decider = _FakeContextDecider(
        _FakeContextDecision(
            intent="chat",
            tools=[],
            deep_thinking=False,
            reasoning="greeting",
            orchestration_strategy={"mode": "direct", "planner": "task_agent",
                                    "default_leaf_type": "general-purpose",
                                    "allow_parallel": False},
        )
    )
    decider.tool_registry = _FakeToolRegistry(["bash", "web-search"])

    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
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
    assert decision.tools == []
    assert decision.execution_mode == ExecutionMode.DIRECT_LLM
