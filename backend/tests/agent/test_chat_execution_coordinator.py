from __future__ import annotations

import pytest

from magi.agent.task_agents.chat import ChatRuntimeContext, ExecutionMode, UserMessagePayload
from magi.agent.task_agents.chat import ExecutionHandlerRegistry
from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator
from magi.agent.task_agents.chat.fact_classifier import ChatFactClassifier, IncomingFactKind
from magi.agent.runtime.contracts import FactRecord
from magi.config.models import ThinkingDepth
from magi.events.events import EventTypes
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.glob_tool import GlobTool
from magi.tools.builtin.grep_tool import GrepTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.context_routing import RouteDecision
from magi.tools.registry import ToolRegistry


class _FakeToolRegistry:
    """Minimal stub so the coordinator can call ``tool_registry.list_tools()``."""

    def __init__(self, tools: list[str] | None = None) -> None:
        self._tools = tools or []

    def list_tools(self) -> list[str]:
        return list(self._tools)


def _build_real_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool_class in (GlobTool, GrepTool, FileReadTool):
        registry.register(tool_class)
    return registry


def _build_real_tool_registry_with_web() -> ToolRegistry:
    registry = _build_real_tool_registry()
    registry.register(WebSearchTool)
    registry.register(WebFetchTool)
    return registry


class _FakeContextDecider:
    def __init__(self, decision: RouteDecision, tool_registry=None) -> None:
        self._decision = decision
        self.last_decision_context = None
        self.tool_registry = tool_registry or _FakeToolRegistry()

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


async def _advisory_provider_for_runtime_rerank(task_context=None, tool_names=None, limit=10):
    if tool_names is None:
        return []
    assert task_context == "分析 backend/src/magi/agent 的调用链路"
    assert tool_names == ["glob", "grep", "file_read"]
    return [
        {
            "tool_name": "glob",
            "available": True,
            "breaker_state": "closed",
            "success_rate": 0.3,
            "total_attempts": 6,
            "strategy_hint": None,
            "context_fit": 0.0,
            "risk_note": "Low success rate",
        },
        {
            "tool_name": "grep",
            "available": True,
            "breaker_state": "closed",
            "success_rate": 0.95,
            "total_attempts": 11,
            "strategy_hint": "Best when tracing call sites.",
            "context_fit": 0.92,
            "risk_note": None,
        },
    ]


@pytest.mark.asyncio
async def test_coordinator_routes_decompose_explore_to_orchestration_launch() -> None:
    trace_recorder = _IntentTraceRecorder()
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="explore",
                graph_shape="plan_fanout",
                complexity="medium",
                tools=["agent"],
                reasoning="decompose",
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
    assert decision.route_decision is not None
    assert decision.route_decision.profile == "explore"
    assert decision.route_decision.graph_shape == "plan_fanout"
    assert trace_recorder.calls == [
        {
            "user_id": "u-chat",
            "session_id": "s-chat",
            "intent": "explore",
            "execution_mode": "orchestration_launch",
            "tools": ["agent"],
            "reasoning": "decompose",
        }
    ]


@pytest.mark.asyncio
async def test_coordinator_keeps_bounded_external_plan_in_direct_web_tools() -> None:
    decider = _FakeContextDecider(
        RouteDecision(
            profile="research",
            graph_shape="plan_fanout",
            complexity="medium",
            tools=["agent"],
            thinking_depth=ThinkingDepth.HIGH,
            reasoning="router tried decomposition",
        ),
        tool_registry=_FakeToolRegistry(
            ["agent", "web-search", "web-fetch", "find-relevant-tools"]
        ),
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    message = "我8点到杭州西站，晚上7点约了人吃饭，中间帮我安排下行程，包括地铁"
    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": message},
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
        latest_user_message=message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.FUNCTION_CALLING
    assert decision.route_decision is not None
    # force_direct_external overrides the plan_fanout graph_shape → FUNCTION_CALLING
    assert "agent" not in decision.tools
    assert "web-search" in decision.tools


@pytest.mark.asyncio
async def test_coordinator_allows_explicit_external_research_decomposition() -> None:
    decider = _FakeContextDecider(
        RouteDecision(
            profile="research",
            graph_shape="plan_fanout",
            complexity="medium",
            tools=["agent"],
            thinking_depth=ThinkingDepth.HIGH,
            reasoning="source-heavy research",
        ),
        tool_registry=_FakeToolRegistry(["agent", "web-search", "find-relevant-tools"]),
    )
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    message = "find the 10 most important Hangzhou news stories from the last 7 days and give links and sources"
    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": message},
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
        latest_user_message=message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "plan_fanout"
    assert "agent" in decision.tools


@pytest.mark.asyncio
async def test_coordinator_carries_intent_llm_trace_metrics() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="chat",
                graph_shape="reply",
                complexity="simple",
                tools=[],
                reasoning="direct response",
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
    assert decision.ux_plan.trace_display_mode.value == "collapsible"


@pytest.mark.asyncio
async def test_coordinator_marks_tool_and_orchestration_turns_as_prominent_trace() -> None:
    tool_decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="tool_loop",
            complexity="simple",
            tools=["memory_query"],
            reasoning="tool use",
        )
    )
    tool_coordinator = ChatExecutionCoordinator(
        context_decider=tool_decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "帮我查一下"},
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
        latest_user_message="帮我查一下",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    tool_decision = await tool_coordinator.match_intent(context)

    assert tool_decision.execution_mode == ExecutionMode.FUNCTION_CALLING
    assert tool_decision.ux_plan.trace_display_mode.value == "prominent"

    orchestration_decider = _FakeContextDecider(
        RouteDecision(
            profile="explore",
            graph_shape="plan_fanout",
            complexity="medium",
            tools=["agent"],
            reasoning="decompose",
        )
    )
    orchestration_coordinator = ChatExecutionCoordinator(
        context_decider=orchestration_decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    orchestration_decision = await orchestration_coordinator.match_intent(context)

    assert orchestration_decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert orchestration_decision.ux_plan.trace_display_mode.value == "prominent"


@pytest.mark.asyncio
async def test_coordinator_match_tools_reorders_runtime_tools_with_task_hint() -> None:
    registry = _build_real_tool_registry()
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="coding",
                graph_shape="tool_loop",
                complexity="simple",
                tools=["file_read", "grep", "glob"],
                reasoning="inspect code",
            ),
            tool_registry=registry,
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
            "content": "分析 backend/src/magi/agent 的调用链路",
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
        latest_user_message="分析 backend/src/magi/agent 的调用链路",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)
    selection = await coordinator.match_tools(context, decision)

    assert decision.task_hint["task_intent"] == "trace_implementation"
    assert decision.task_hint["target_locality"] == "explicit_path"
    assert selection.tools[:2] == ["glob", "grep"]
    assert selection.task_hint["domain"] == "codebase"
    assert selection.recommended_tools[0]["tool"] == "glob"


@pytest.mark.asyncio
async def test_coordinator_match_tools_applies_l4_advisory_rerank() -> None:
    registry = _build_real_tool_registry()
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="coding",
                graph_shape="tool_loop",
                complexity="simple",
                tools=["file_read", "grep", "glob"],
                reasoning="inspect code",
            ),
            tool_registry=registry,
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        tool_advisory_provider=_advisory_provider_for_runtime_rerank,
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": "分析 backend/src/magi/agent 的调用链路",
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
        latest_user_message="分析 backend/src/magi/agent 的调用链路",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)
    selection = await coordinator.match_tools(context, decision)

    assert selection.tools[:2] == ["grep", "glob"]
    assert selection.recommended_tools[0]["tool"] == "grep"
    assert "strong historical fit" in selection.recommended_tools[0]["reason"]


@pytest.mark.asyncio
async def test_coordinator_marks_ambiguous_external_reference_scope() -> None:
    registry = _build_real_tool_registry_with_web()
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="research",
                graph_shape="tool_loop",
                complexity="simple",
                tools=["web-search", "file_read"],
                reasoning="compare external implementation",
            ),
            tool_registry=registry,
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
            "content": "详细对比下 Magi 和 AnotherProject 的记忆实现",
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
        latest_user_message="详细对比下 Magi 和 AnotherProject 的记忆实现",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.task_hint["target_locality"] == "ambiguous_external_reference"
    assert decision.task_hint["preferred_resolution_order"] == "ask_or_web_before_external_scan"
    assert decision.task_hint["requires_clarification"] is True


@pytest.mark.asyncio
async def test_coordinator_excludes_latest_user_message_from_recent_messages_context() -> None:
    fake_decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="direct response",
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
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="direct response",
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
            RouteDecision(
                profile="coding",
                graph_shape="plan_fanout",
                complexity="large",
                tools=["grep", "file_read", "glob"],
                thinking_depth=ThinkingDepth.HIGH,
                reasoning="multi-step analysis should decompose",
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
    assert decision.ux_plan.trace_display_mode.value == "prominent"
    assert decision.ux_plan.interim_text


@pytest.mark.asyncio
async def test_coordinator_routes_complex_news_to_generic_orchestration_without_explore() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="research",
                graph_shape="plan_fanout",
                complexity="large",
                tools=["web-search", "web-fetch"],
                thinking_depth=ThinkingDepth.HIGH,
                reasoning="complex research",
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
            "content": "搜一下最近7天杭州有什么重要的新闻，给我来10条",
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
        latest_user_message="搜一下最近7天杭州有什么重要的新闻，给我来10条",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "plan_fanout"
    assert decision.route_decision.profile != "explore"


@pytest.mark.asyncio
async def test_coordinator_passes_recent_tool_errors_to_context_decider() -> None:
    fake_decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="follow-up",
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
async def test_coordinator_marks_tool_query_as_prominent_trace_ui() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="chat",
                graph_shape="tool_loop",
                complexity="simple",
                tools=["weather"],
                reasoning="tool required",
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
    assert decision.ux_plan.trace_display_mode.value == "prominent"
    assert decision.ux_plan.allow_trace_collapse is True


@pytest.mark.asyncio
async def test_coordinator_marks_acknowledgement_as_reaction_only_ui() -> None:
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="chat",
                graph_shape="reply",
                complexity="simple",
                tools=[],
                reasoning="acknowledgement",
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
            RouteDecision(
                profile="chat",
                graph_shape="tool_loop",
                complexity="simple",
                tools=["file_read"],
                reasoning="tool required",
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
            "attachments": [
                {"attachment_id": "att-image", "kind": "image", "original_name": "diagram.png"}
            ],
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
        {
            "tool_name": "web_search",
            "available": True,
            "breaker_state": "closed",
            "success_rate": 0.8,
            "total_attempts": 5,
            "strategy_hint": "use quotes",
            "context_fit": None,
            "risk_note": None,
        },
    ]

    async def advisory_provider(task_context=None, tool_names=None, limit=10):
        assert task_context == "search weather"
        assert tool_names is None
        assert limit == 6
        return fake_advisories

    decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="tool_loop",
            complexity="simple",
            tools=["web_search"],
            reasoning="search",
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
    assert dc.tool_advisory == [
        {
            "tool_name": "web_search",
            "available": True,
            "breaker_state": "closed",
            "success_rate": 0.8,
            "total_attempts": 5,
            "context_fit": None,
            "strategy_hint": "use quotes",
            "risk_note": None,
        }
    ]


@pytest.mark.asyncio
async def test_coordinator_works_without_advisory_provider() -> None:
    """Coordinator should work fine when tool_advisory_provider is None."""
    decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="greeting",
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
    """web-search and find-relevant-tools should be appended when tool-calling is active."""
    decider = _FakeContextDecider(
        RouteDecision(
            profile="coding",
            graph_shape="tool_loop",
            complexity="simple",
            tools=["bash"],
            reasoning="run command",
        )
    )
    decider.tool_registry = _FakeToolRegistry(
        ["bash", "web-search", "find-relevant-tools", "file_read"]
    )

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
    assert "find-relevant-tools" in decision.tools


@pytest.mark.asyncio
async def test_coordinator_reranks_shortlist_and_skips_open_breaker_fallbacks() -> None:
    decider = _FakeContextDecider(
        RouteDecision(
            profile="coding",
            graph_shape="tool_loop",
            complexity="simple",
            tools=["bash", "web-search"],
            reasoning="run command",
        )
    )
    decider.tool_registry = _FakeToolRegistry(["bash", "web-search", "find-relevant-tools"])

    async def advisory_provider(task_context=None, tool_names=None, limit=10):
        if tool_names is None:
            return []
        assert tool_names == ["bash", "web-search", "find-relevant-tools"]
        return [
            {
                "tool_name": "bash",
                "available": True,
                "breaker_state": "closed",
                "success_rate": 0.55,
                "total_attempts": 4,
                "strategy_hint": None,
                "context_fit": 0.2,
                "risk_note": None,
            },
            {
                "tool_name": "web-search",
                "available": False,
                "breaker_state": "open",
                "success_rate": 0.1,
                "total_attempts": 7,
                "strategy_hint": None,
                "context_fit": 0.0,
                "risk_note": "Circuit breaker open",
            },
            {
                "tool_name": "find-relevant-tools",
                "available": True,
                "breaker_state": "closed",
                "success_rate": 0.93,
                "total_attempts": 8,
                "strategy_hint": "Use when the current toolset is missing a next-step capability.",
                "context_fit": 0.9,
                "risk_note": None,
            },
        ]

    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        tool_advisory_provider=advisory_provider,
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

    assert decision.tools == ["find-relevant-tools", "bash"]


@pytest.mark.asyncio
async def test_coordinator_does_not_inject_fallback_tools_for_chat() -> None:
    """Pure chat (no tools) should stay tool-free — no fallback injection."""
    decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=[],
            reasoning="greeting",
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


@pytest.mark.asyncio
async def test_coordinator_reply_shape_drops_tools_to_avoid_request_handler_mismatch() -> None:
    """Regression for the dispatch-axis split introduced in Phase C.

    If the router emits graph_shape='reply' but also non-empty tools, the
    coordinator must NOT build a FunctionCallingRequest — the GraphBuilder
    will pick ReplyNode (which delegates to DirectLLMHandler, requiring a
    DirectLLMRequest with .messages). The two axes (request shape +
    node selection) must agree on a single mode.

    Failure mode before the fix: '[error] FunctionCallingRequest object has
    no attribute messages' bubbled up through NodeSequenceRunner.
    """
    decider = _FakeContextDecider(
        RouteDecision(
            profile="chat",
            graph_shape="reply",
            complexity="simple",
            tools=["web-search"],  # router opined a tool but chose reply shape
            reasoning="reply with optional tool",
        )
    )
    decider.tool_registry = _FakeToolRegistry(["web-search", "find-relevant-tools"])

    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )

    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "hi"},
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
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    # graph_shape='reply' must map to DIRECT_LLM (so build_request returns
    # DirectLLMRequest), and tools must be dropped (so they can't sneak the
    # mode to FUNCTION_CALLING).
    assert decision.execution_mode == ExecutionMode.DIRECT_LLM
    assert decision.tools == []
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "reply"
