from __future__ import annotations

import pytest

from magi.agent.task_agents.handlers import ChatRuntimeContext, ExecutionMode, UserMessagePayload
from magi.agent.task_agents.handlers import ExecutionHandlerRegistry
from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.chat.task_agent.fact_classifier import ChatFactClassifier, IncomingFactKind
from magi.agent.runtime.contracts import FactRecord
from magi.config.models import ThinkingDepth
from magi.events.events import EventTypes
from magi.llm.streaming_events import LLMStreamEvent
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.glob_tool import GlobTool
from magi.tools.builtin.grep_tool import GrepTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.context_routing import RouteDecision
from magi.tools.registry import ToolRegistry
from magi_plugin_sdk.delivery import DeliveryContent


class _FakeToolRegistry:
    """Minimal stub so the coordinator can call ``tool_registry.list_tools()``."""

    def __init__(self, tools: list[str] | None = None) -> None:
        self._tools = tools or []

    def list_tools(self) -> list[str]:
        return list(self._tools)


def _build_delivery_dispatcher(
    registry,
    *,
    user_prefs_provider=None,
    receipts_store=None,
):
    return ChatDeliveryDispatcher.from_registry(
        channel_registry=registry,
        user_prefs_provider=user_prefs_provider,
        receipts_store=receipts_store,
    )


class _EmptyChannelRegistry:
    def get(self, _channel_type):
        return None


class _FakeExecutionOutcome:
    def __init__(self, result, *, used_graph: bool = True) -> None:
        self.result = result
        self.used_graph = used_graph


class _FakeExecutionEngine:
    def __init__(self, result, *, used_graph: bool = True) -> None:
        self.result = result
        self.used_graph = used_graph
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return _FakeExecutionOutcome(self.result, used_graph=self.used_graph)


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
async def test_coordinator_keeps_tools_when_router_says_reply_but_selects_tools() -> None:
    """Regression (ADR-0005): the router can emit graph_shape='reply' while
    still selecting a tool (e.g. memory_query). The tool must NOT be dropped —
    execution shape is derived from the tool list, so this becomes a
    tool_loop / FUNCTION_CALLING rather than a tool-less DIRECT_LLM reply."""
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="chat",
                graph_shape="reply",
                complexity="simple",
                tools=["memory_query"],
                reasoning="recall browsing history",
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
            "content": "我最近2天在用chrome看什么来着",
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
        latest_user_message="我最近2天在用chrome看什么来着",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert "memory_query" in decision.tools
    assert decision.execution_mode == ExecutionMode.FUNCTION_CALLING
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "tool_loop"


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

    await coordinator.match_intent(context)
    dc = decider.last_decision_context
    assert dc is not None
    assert dc.tool_advisory == []


@pytest.mark.asyncio
async def test_coordinator_keeps_local_tool_route_local() -> None:
    """Local tool routes should not gain network or discovery capabilities."""
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
    assert decision.tools == ["bash"]


@pytest.mark.asyncio
async def test_coordinator_enters_tool_loop_when_route_needs_tool_discovery() -> None:
    decider = _FakeContextDecider(
        RouteDecision(
            profile="research",
            graph_shape="reply",
            complexity="simple",
            tool_need="discover",
            tools=[],
            reasoning="needs runtime tool discovery",
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
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": "帮我找一个能解析日历的工具",
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
        latest_user_message="帮我找一个能解析日历的工具",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.FUNCTION_CALLING
    assert decision.tools == ["find-relevant-tools"]


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
        assert tool_names == ["bash", "web-search"]
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

    assert decision.tools == ["bash"]


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
async def test_coordinator_derives_consistent_shape_and_mode_for_reply_with_tools() -> None:
    """ADR-0005: graph_shape and execution_mode must stay on a single mode so
    the GraphBuilder's node and the request shape never mismatch (a ReplyNode
    receiving a FunctionCallingRequest crashes with 'no attribute messages').

    Pre-ADR-0005 this was enforced by DROPPING tools when the router said
    'reply'. Now the shape is DERIVED from the tools instead: a router that
    opines 'reply' yet selects a tool yields tool_loop + FUNCTION_CALLING, with
    decision.graph_shape rewritten to match. The two axes are sourced from the
    same derivation and cannot disagree — and the tool is preserved, not lost.
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

    # Tools present → shape derives to tool_loop, mode to FUNCTION_CALLING, and
    # decision.graph_shape is rewritten to match. Two axes agree; tool survives.
    assert decision.execution_mode == ExecutionMode.FUNCTION_CALLING
    assert "web-search" in decision.tools
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "tool_loop"


# ---------------------------------------------------------------------------
# Phase G+1 / Task 7: ChatExecutionCoordinator.dispatch_stream_chunk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_stream_chunk_routes_to_chat_sse_channel_when_registry_wired():
    class _RecordingChunkChannel:
        channel_type = "chat_sse"
        # Opt into streaming so DeliveryRouter.fanout_chunk doesn't skip us.
        supports_streaming = True
        def __init__(self): self.chunks = []
        async def deliver_chunk(self, target, chunk):
            self.chunks.append((target, chunk))
    class _Registry:
        def __init__(self, ch): self._ch = ch
        def get(self, k): return self._ch if k == "chat_sse" else None
    rec = _RecordingChunkChannel()
    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(_Registry(rec)),
    )
    await coordinator.dispatch_stream_chunk(
        session_id="s1", user_id="u1", text="hello",
        is_final=False, seq=0,
    )
    assert len(rec.chunks) == 1
    target, chunk = rec.chunks[0]
    assert target.channel_type == "chat_sse"  # scheme-only
    assert target.magi_session_id == "s1"  # per-run context rides on dedicated field
    assert chunk.text == "hello"
    assert chunk.is_final is False
    assert chunk.seq == 0


@pytest.mark.asyncio
async def test_dispatch_stream_chunk_noop_when_no_router():
    """When channel_registry is None, dispatch_stream_chunk must not crash
    and must do nothing."""
    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        # no delivery_dispatcher -> no delivery fanout
    )
    # Should be a no-op — would raise AttributeError if accessed
    await coordinator.dispatch_stream_chunk(
        session_id="s1", user_id="u1", text="hi",
        is_final=False, seq=0,
    )


@pytest.mark.asyncio
async def test_dispatch_stream_chunk_noop_when_session_id_empty():
    """Empty session_id → no-op (can't route without it)."""
    class _RecordingChunkChannel:
        channel_type = "chat_sse"
        def __init__(self): self.chunks = []
        async def deliver_chunk(self, target, chunk):
            self.chunks.append((target, chunk))
    class _Registry:
        def __init__(self, ch): self._ch = ch
        def get(self, k): return self._ch if k == "chat_sse" else None
    rec = _RecordingChunkChannel()
    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(_Registry(rec)),
    )
    await coordinator.dispatch_stream_chunk(
        session_id="", user_id="u1", text="hello",
        is_final=False, seq=0,
    )
    assert len(rec.chunks) == 0


@pytest.mark.asyncio
async def test_dispatch_stream_chunk_carries_event_and_persona_on_delivery_chunk():
    """Phase G+1 Step 2: when dispatch_stream_chunk is handed a full
    LLMStreamEvent, the DeliveryChunk must carry ``event.to_wire_dict()`` and
    ``persona_id`` so ChatSseChannel.deliver_chunk can forward EVERY
    stream-event kind (tool_call / reasoning / status / text_flush), not just
    the legacy text_delta shape."""
    class _RecordingChunkChannel:
        channel_type = "chat_sse"
        supports_streaming = True
        def __init__(self): self.chunks = []
        async def deliver_chunk(self, target, chunk):
            self.chunks.append((target, chunk))
    class _Registry:
        def __init__(self, ch): self._ch = ch
        def get(self, k): return self._ch if k == "chat_sse" else None
    rec = _RecordingChunkChannel()
    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(_Registry(rec)),
    )
    event = LLMStreamEvent(
        kind="tool_call_start", tool_call_id="tc1", tool_name="web-search",
    )
    await coordinator.dispatch_stream_chunk(
        session_id="s1", user_id="u1", text="", is_final=False, seq=0,
        turn_id="t1", event=event, persona_id="p1",
    )
    assert len(rec.chunks) == 1
    _, chunk = rec.chunks[0]
    assert chunk.event == {
        "kind": "tool_call_start",
        "tool_call_id": "tc1",
        "tool_name": "web-search",
    }
    assert chunk.persona_id == "p1"
    assert chunk.turn_id == "t1"


# ---------------------------------------------------------------------------
# Phase G+1 / Task 9: user_prefs_provider injection for final-delivery fanout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_user_prefs_returns_empty_when_no_provider():
    """No provider wired → returns empty dict, no error."""
    dispatcher = _build_delivery_dispatcher(_EmptyChannelRegistry())
    prefs = await dispatcher._resolve_user_prefs("u-1")
    assert prefs == {}


@pytest.mark.asyncio
async def test_resolve_user_prefs_returns_empty_when_user_id_blank():
    """Blank user_id → skip provider call, return empty."""
    calls = []

    async def provider(user_id):
        calls.append(user_id)
        return {"delivery_channels": ["chat_sse", "telegram"]}

    dispatcher = _build_delivery_dispatcher(
        _EmptyChannelRegistry(),
        user_prefs_provider=provider,
    )
    prefs = await dispatcher._resolve_user_prefs("")
    assert prefs == {}
    assert calls == []


@pytest.mark.asyncio
async def test_resolve_user_prefs_returns_provider_result():
    """Provider returns dict → returned as-is."""
    async def provider(user_id):
        assert user_id == "u-7"
        return {"delivery_channels": ["chat_sse", "telegram"]}

    dispatcher = _build_delivery_dispatcher(
        _EmptyChannelRegistry(),
        user_prefs_provider=provider,
    )
    prefs = await dispatcher._resolve_user_prefs("u-7")
    assert prefs == {"delivery_channels": ["chat_sse", "telegram"]}


@pytest.mark.asyncio
async def test_resolve_user_prefs_swallows_provider_errors():
    """Provider raises → returns empty dict (delivery must not crash)."""
    async def bad_provider(user_id):
        raise RuntimeError("user-pref store down")

    dispatcher = _build_delivery_dispatcher(
        _EmptyChannelRegistry(),
        user_prefs_provider=bad_provider,
    )
    prefs = await dispatcher._resolve_user_prefs("u-7")
    assert prefs == {}


@pytest.mark.asyncio
async def test_execute_defers_fanout_until_postprocess():
    """Execution returns the result without sending before persistence.

    The postprocess delivery seam then fans the durable result out to every
    configured target.
    """
    from magi.agent.task_agents.common.contracts import (
        ExecutionRequest, ExecutionResult, ExecutionMode,
    )
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
    from magi.tools.context_routing import RouteDecision

    class _Rec(Channel):
        def __init__(self, ctype):
            self._t = ctype
            self.delivered = []
        @property
        def channel_type(self):
            return self._t
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.delivered.append((target, content))
            return DeliveryReceipt(
                channel_id=self._t,
                external_message_id=f"{self._t}_1",
                delivered_at_ms=1000,
            )
        async def retract(self, receipt): pass

    sse = _Rec("chat_sse")
    telegram = _Rec("telegram")

    class _Registry:
        def __init__(self, m): self._m = m
        def get(self, k): return self._m.get(k)

    registry = _Registry({"chat_sse": sse, "telegram": telegram})

    async def provider(user_id):
        assert user_id == "u-9"
        return {"delivery_channels": ["chat_sse", "telegram"]}

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            registry,
            user_prefs_provider=provider,
        ),
    )

    # Stub the execution engine so execute() short-circuits with a fixed result.
    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM, response_text="hello world",
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    # Build a real-shaped request with route_decision so execute() takes the
    # node-sequence path.
    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    fact = FactRecord(
        agent_id="chat:u-9",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-9", "session_id": "s-9", "content": "hi"},
    )
    context = ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id="u-9",
        agent_type="chat",
        runtime_key="chat:u-9",
        user_id="u-9",
        session_id="s-9",
        history_key="u-9::s-9",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-9"),
        session_run_id="run-9",
    )
    from magi.agent.task_agents.handlers.contracts import IntentDecision
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    from magi.agent.task_agents.common.contracts import ToolSelection
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)
    assert result is canned_result

    # No final channel sees an answer before chat post-processing persists it.
    assert len(sse.delivered) == 0
    assert len(telegram.delivered) == 0

    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(text=result.response_text),
    )

    assert len(sse.delivered) == 1
    assert len(telegram.delivered) == 1
    assert telegram.delivered[0][1].text == "hello world"


@pytest.mark.asyncio
async def test_deliver_final_chat_response_delivers_rich_content_to_all_targets():
    """The postprocess seam fans one rich durable response to every target."""
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

    class _Rec(Channel):
        def __init__(self, ctype):
            self._t = ctype
            self.received = []
        @property
        def channel_type(self):
            return self._t
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.received.append(content)
            return DeliveryReceipt(
                channel_id=self._t, external_message_id=None,
                delivered_at_ms=1000, magi_session_id=target.magi_session_id,
            )
        async def retract(self, receipt): pass

    sse = _Rec("chat_sse")
    telegram = _Rec("telegram")

    class _Registry:
        def __init__(self, m): self._m = m
        def get(self, k): return self._m.get(k)

    saved_receipts: list[dict] = []

    class _RecReceiptsStore:
        async def save_receipts(self, *, session_id, run_id, revision, receipts):
            saved_receipts.append(
                {"session_id": session_id, "run_id": run_id,
                 "revision": revision, "receipts": list(receipts)}
            )

    async def _provider(user_id):
        return {"delivery_channels": ["chat_sse", "telegram"]}

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            _Registry({"chat_sse": sse, "telegram": telegram}),
            user_prefs_provider=_provider,
            receipts_store=_RecReceiptsStore(),
        ),
    )

    fact = FactRecord(
        agent_id="chat:u-1",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-1", "session_id": "s-1", "content": "hi"},
    )
    context = ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id="u-1",
        agent_type="chat",
        runtime_key="chat:u-1",
        user_id="u-1",
        session_id="s-1",
        history_key="u-1::s-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-1"),
        session_run_id="run-1",
        session_run_revision=7,
    )
    content = DeliveryContent(
        text="final answer",
        turn_id="t-1",
        message_id="m-1",
        message_kind="assistant_final",
        persona_id="p-1",
        trace_summary={"turn_id": "t-1"},
        trace_available=True,
        ux_plan={"assistant_surface_mode": "final_only"},
        message_payload={"k": "v"},
        orchestration_id="o-1",
    )

    delivery_result = await coordinator.deliver_final_chat_response(
        context,
        content=content,
    )

    assert len(sse.received) == 1
    assert len(telegram.received) == 1
    delivered = sse.received[0]
    assert delivered.text == "final answer"
    assert delivered.turn_id == "t-1"
    assert delivered.message_id == "m-1"
    assert delivered.message_kind == "assistant_final"
    assert delivered.persona_id == "p-1"
    assert delivered.trace_summary == {"turn_id": "t-1"}
    assert delivered.trace_available is True
    assert delivered.ux_plan == {"assistant_surface_mode": "final_only"}
    assert delivered.message_payload == {"k": "v"}
    assert delivered.orchestration_id == "o-1"

    # Both receipts are persisted against the exact run revision.
    assert len(delivery_result.receipts) == 2
    assert {receipt.channel_id for receipt in delivery_result.receipts} == {
        "chat_sse",
        "telegram",
    }
    assert len(saved_receipts) == 1
    assert saved_receipts[0]["session_id"] == "s-1"
    assert saved_receipts[0]["run_id"] == "run-1"
    assert saved_receipts[0]["revision"] == 7


@pytest.mark.asyncio
async def test_execute_swallows_user_prefs_provider_errors_and_uses_default_target():
    """A preference lookup failure does not make execution fail."""
    from magi.agent.task_agents.common.contracts import (
        ExecutionRequest, ExecutionResult, ExecutionMode, ToolSelection,
    )
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryReceipt
    from magi.tools.context_routing import RouteDecision
    from magi.agent.task_agents.handlers.contracts import IntentDecision

    class _Rec(Channel):
        def __init__(self, ctype):
            self._t = ctype
            self.delivered = []
        @property
        def channel_type(self):
            return self._t
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.delivered.append((target, content))
            return DeliveryReceipt(
                channel_id=self._t,
                external_message_id=f"{self._t}_1",
                delivered_at_ms=1000,
            )
        async def retract(self, receipt): pass

    sse = _Rec("chat_sse")

    class _Registry:
        def __init__(self, m): self._m = m
        def get(self, k): return self._m.get(k)

    registry = _Registry({"chat_sse": sse})

    async def bad_provider(user_id):
        raise RuntimeError("store down")

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            registry,
            user_prefs_provider=bad_provider,
        ),
    )

    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM, response_text="fallback ok",
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    fact = FactRecord(
        agent_id="chat:u-bad",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-bad", "session_id": "s-bad", "content": "hi"},
    )
    context = ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id="u-bad",
        agent_type="chat",
        runtime_key="chat:u-bad",
        user_id="u-bad",
        session_id="s-bad",
        history_key="u-bad::s-bad",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-bad"),
        session_run_id="run-bad",
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)
    assert result is canned_result

    # The provider error is swallowed and execution still avoids early fanout.
    assert len(sse.delivered) == 0


@pytest.mark.asyncio
async def test_execute_passes_runner_attachments_through_to_delivery_content():
    """Phase A media-outbound: ExecutionResult.attachments (produced by
    image_generation_tool / prepare_chat_attachments / photo_library /
    screenshot_timeline) MUST ride along on the DeliveryContent the
    coordinator hands to fanout_deliver. Before this fix, the call site
    only passed text, so external channels (telegram/weixin) could never
    have known the agent wanted to attach images — even with downstream
    channel-side support, the data was lost at this layer."""
    from magi.agent.task_agents.common.contracts import (
        ExecutionRequest, ExecutionResult, ExecutionMode, ToolSelection,
    )
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryReceipt
    from magi.tools.context_routing import RouteDecision
    from magi.agent.task_agents.handlers.contracts import IntentDecision

    class _Capture(Channel):
        def __init__(self, ctype):
            self._t = ctype
            self.received = []  # list of DeliveryContent
        @property
        def channel_type(self):
            return self._t
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.received.append(content)
            return DeliveryReceipt(
                channel_id=self._t,
                external_message_id=f"{self._t}_1",
                delivered_at_ms=1000,
            )
        async def retract(self, receipt): pass

    # The durable postprocess seam must preserve outbound attachments.
    tg = _Capture("telegram")

    class _Registry:
        def __init__(self, m): self._m = m
        def get(self, k): return self._m.get(k)

    registry = _Registry({"telegram": tg})

    async def _provider(user_id):
        return {"delivery_channels": ["telegram"]}

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            registry,
            user_prefs_provider=_provider,
        ),
    )

    image_attachment = {
        "attachment_id": "att-img-1",
        "kind": "image",
        "original_name": "cyberpunk.png",
        "mime_type": "image/png",
        "size_bytes": 4096,
        "storage_path": "/tmp/magi-att/cyberpunk.png",
        "sha256": "deadbeef",
    }
    pdf_attachment = {
        "attachment_id": "att-doc-1",
        "kind": "document",
        "original_name": "spec.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 12345,
        "storage_path": "/tmp/magi-att/spec.pdf",
        "sha256": "cafebabe",
    }
    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="here's what you asked for",
        attachments=[image_attachment, pdf_attachment],
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    fact = FactRecord(
        agent_id="chat:u-att",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-att", "session_id": "s-att", "content": "show"},
    )
    context = ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id="u-att",
        agent_type="chat",
        runtime_key="chat:u-att",
        user_id="u-att",
        session_id="s-att",
        history_key="u-att::s-att",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="show",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-att"),
        session_run_id="run-att",
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)

    assert tg.received == []
    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(
            text=result.response_text,
            attachments=tuple(result.attachments),
        ),
    )

    assert len(tg.received) == 1
    delivered = tg.received[0]
    # Text is unchanged.
    assert delivered.text == "here's what you asked for"
    # Attachments arrived intact, in order, as a tuple of dicts.
    assert len(delivered.attachments) == 2
    assert delivered.attachments[0]["attachment_id"] == "att-img-1"
    assert delivered.attachments[0]["kind"] == "image"
    assert delivered.attachments[0]["storage_path"] == "/tmp/magi-att/cyberpunk.png"
    assert delivered.attachments[1]["attachment_id"] == "att-doc-1"
    assert delivered.attachments[1]["kind"] == "document"


@pytest.mark.asyncio
async def test_execute_passes_empty_attachments_when_runner_has_none():
    """When ExecutionResult.attachments is empty (the common case for
    text-only replies), DeliveryContent.attachments must be an empty
    tuple — not crash, not leak a None into channel.deliver."""
    from magi.agent.task_agents.common.contracts import (
        ExecutionRequest, ExecutionResult, ExecutionMode, ToolSelection,
    )
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryReceipt
    from magi.tools.context_routing import RouteDecision
    from magi.agent.task_agents.handlers.contracts import IntentDecision

    # The durable postprocess seam normalizes an empty attachment list.
    class _Capture(Channel):
        def __init__(self): self.received = []
        @property
        def channel_type(self): return "telegram"
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.received.append(content)
            return DeliveryReceipt(channel_id="telegram", external_message_id="x", delivered_at_ms=1)
        async def retract(self, receipt): pass

    sse = _Capture()

    class _Registry:
        def get(self, k): return sse if k == "telegram" else None

    async def _prov(user_id):
        return {"delivery_channels": ["telegram"]}

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple", tools=[], reasoning="",
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            _Registry(),
            user_prefs_provider=_prov,
        ),
    )
    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM,
        response_text="just words",
        # attachments defaults to [] via dataclass field factory
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    fact = FactRecord(
        agent_id="chat:u",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u", "session_id": "s", "content": "hi"},
    )
    context = ChatRuntimeContext(
        latest_fact=fact, recent_facts=[fact], batch_facts=[fact],
        agent_id="u", agent_type="chat", runtime_key="chat:u",
        user_id="u", session_id="s", history_key="u::s",
        history=[], conversation_history=[], active_orchestrations=[],
        latest_user_message="hi", incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u"),
        session_run_id="r",
    )
    intent = IntentDecision(
        intent="chat", difficulty="normal", execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=RouteDecision(profile="chat", graph_shape="reply", complexity="simple", tools=[], reasoning=""),
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM, context=context, intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)
    assert sse.received == []
    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(
            text=result.response_text,
            attachments=tuple(result.attachments),
        ),
    )
    assert len(sse.received) == 1
    assert sse.received[0].attachments == ()


@pytest.mark.asyncio
async def test_execute_routes_reply_back_to_origin_channel_from_run_trigger():
    """Phase H+2 (this change): when a run was triggered by an external
    channel (its ``AgentRun.trigger.source_channel`` is e.g. ``"weixin"``),
    the coordinator MUST include that channel in the fanout targets even
    when the user has no ``delivery_channels`` configured.

    Before the fix, a WeChat user sending a message would see the agent
    respond in the Magi chat UI (chat_sse default) but never receive the
    reply on WeChat — the inbound channel identity was lost between
    inbound dispatch and outbound fanout. This test reproduces the bug
    end-to-end through ``coordinator.execute``.
    """
    from magi.agent.task_agents.common.contracts import (
        ExecutionRequest, ExecutionResult, ExecutionMode, ToolSelection,
    )
    from magi.agent.task_agents.handlers.run_contracts import AgentRun
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryReceipt
    from magi_plugin_sdk.run_trigger import RunTrigger
    from magi.tools.context_routing import RouteDecision
    from magi.agent.task_agents.handlers.contracts import IntentDecision

    class _Rec(Channel):
        def __init__(self, ctype):
            self._t = ctype
            self.delivered = []
        @property
        def channel_type(self):
            return self._t
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.delivered.append((target, content))
            return DeliveryReceipt(
                channel_id=self._t,
                external_message_id=f"{self._t}_1",
                delivered_at_ms=1000,
            )
        async def retract(self, receipt): pass

    sse = _Rec("chat_sse")
    weixin = _Rec("weixin")

    class _Registry:
        def __init__(self, m): self._m = m
        def get(self, k): return self._m.get(k)

    registry = _Registry({"chat_sse": sse, "weixin": weixin})

    # Crucially: no user_prefs.delivery_channels — proves the auto-route
    # is driven by RunTrigger.source_channel, NOT by user config.
    async def empty_provider(user_id):
        return {}

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            registry,
            user_prefs_provider=empty_provider,
        ),
    )

    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM, response_text="reply for weixin",
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    fact = FactRecord(
        agent_id="chat:u-wx",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-wx", "session_id": "s-wx", "content": "你好"},
    )
    # The key bit: build an AgentRun carrying the inbound-channel trigger.
    weixin_trigger = RunTrigger(
        trigger_type="external_inbound",
        source_channel="weixin",
        requester="u-wx",
        priority="foreground",
    )
    active_run = AgentRun(
        session_id="s-wx", run_id="run-wx", trigger=weixin_trigger,
    )
    context = ChatRuntimeContext(
        latest_fact=fact,
        recent_facts=[fact],
        batch_facts=[fact],
        agent_id="u-wx",
        agent_type="chat",
        runtime_key="chat:u-wx",
        user_id="u-wx",
        session_id="s-wx",
        history_key="u-wx::s-wx",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="你好",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-wx"),
        session_run_id="run-wx",
        active_run=active_run,
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)
    assert result is canned_result

    assert len(weixin.delivered) == 0
    assert len(sse.delivered) == 0
    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(text=result.response_text),
    )

    # The durable postprocess delivery returns to the source channel carried by
    # the run trigger, while also updating the desktop chat surface.
    assert len(weixin.delivered) == 1, "WeChat channel should have received the reply"
    assert weixin.delivered[0][1].text == "reply for weixin"
    assert len(sse.delivered) == 1


@pytest.mark.asyncio
async def test_execute_context_user_prefs_wins_over_provider():
    """When both provider and context.user_prefs supply prefs, context wins
    (request-time override semantics).

    ChatRuntimeContext is a slots dataclass without a user_prefs attribute,
    so this exercises the merge with a duck-typed context substitute to keep
    the override path under test.
    """
    from types import SimpleNamespace
    from magi.agent.task_agents.common.contracts import (
        ExecutionRequest, ExecutionResult, ExecutionMode, ToolSelection,
    )
    from magi_plugin_sdk.channels import Channel
    from magi_plugin_sdk.delivery import DeliveryReceipt
    from magi.tools.context_routing import RouteDecision
    from magi.agent.task_agents.handlers.contracts import IntentDecision

    class _Rec(Channel):
        def __init__(self, ctype):
            self._t = ctype
            self.delivered = []
        @property
        def channel_type(self):
            return self._t
        async def start(self): return None
        async def stop(self): return None
        async def send_message(self, target, content): return None
        async def send_typing_indicator(self, target): return None
        async def deliver(self, target, content):
            self.delivered.append((target, content))
            return DeliveryReceipt(
                channel_id=self._t,
                external_message_id=f"{self._t}_1",
                delivered_at_ms=1000,
            )
        async def retract(self, receipt): pass

    sse = _Rec("chat_sse")
    telegram = _Rec("telegram")
    slack = _Rec("slack")

    class _Registry:
        def __init__(self, m): self._m = m
        def get(self, k): return self._m.get(k)

    registry = _Registry({
        "chat_sse": sse, "telegram": telegram, "slack": slack,
    })

    async def provider(user_id):
        return {"delivery_channels": ["telegram"]}

    decider = _FakeContextDecider(RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning=""
    ))
    coordinator = ChatExecutionCoordinator(
        context_decider=decider,
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        delivery_dispatcher=_build_delivery_dispatcher(
            registry,
            user_prefs_provider=provider,
        ),
    )

    canned_result = ExecutionResult(
        mode=ExecutionMode.DIRECT_LLM, response_text="override",
    )
    coordinator._execution_engine = _FakeExecutionEngine(canned_result)

    route = RouteDecision(
        profile="chat", graph_shape="reply", complexity="simple",
        tools=[], reasoning="",
    )
    # Duck-typed context with the user_prefs attribute so the override branch
    # in execute() actually fires. Only the attrs execute() reads are needed.
    context = SimpleNamespace(
        user_id="u-ctx",
        session_id="s-ctx",
        session_run_id="run-ctx",
        user_prefs={"delivery_channels": ["chat_sse", "slack"]},
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.DIRECT_LLM,
        route_decision=route,
        reasoning="",
    )
    request = ExecutionRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(tools=[], reasoning="", task_hint={}),
    )

    result = await coordinator.execute(request)

    assert len(sse.delivered) == 0
    assert len(slack.delivered) == 0
    assert len(telegram.delivered) == 0
    await coordinator.deliver_final_chat_response(
        context,
        content=DeliveryContent(text=result.response_text),
    )

    # Context's chat_sse + slack should have been used, not provider's telegram.
    assert len(sse.delivered) == 1
    assert len(slack.delivered) == 1
    assert len(telegram.delivered) == 0


@pytest.mark.asyncio
async def test_coordinator_maybe_without_tools_yields_direct_reply() -> None:
    """Advisory maybe-orchestration does not force tools or delegation."""
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="chat",
                graph_shape="reply",
                complexity="simple",
                tools=[],
                needs_orchestration="maybe",
                reasoning="single agent now, may fan out later",
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )
    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "do a big thing"},
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
        latest_user_message="do a big thing",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.DIRECT_LLM
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "reply"
    assert decision.route_decision.needs_orchestration == "maybe"


@pytest.mark.asyncio
async def test_coordinator_required_orchestration_yields_plan_fanout() -> None:
    """P3 (ADR-0005): needs_orchestration='required' derives to plan_fanout /
    ORCHESTRATION_LAUNCH (pre-planned multi-agent fanout)."""
    coordinator = ChatExecutionCoordinator(
        context_decider=_FakeContextDecider(
            RouteDecision(
                profile="chat",
                graph_shape="reply",
                complexity="large",
                tools=[],
                needs_orchestration="required",
                reasoning="decomposable multi-part work",
            )
        ),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
    )
    fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"user_id": "u-chat", "session_id": "s-chat", "content": "decompose this"},
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
        latest_user_message="decompose this",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload.from_dict(dict(fact.payload), fallback_user_id="u-chat"),
    )

    decision = await coordinator.match_intent(context)

    assert decision.execution_mode == ExecutionMode.ORCHESTRATION_LAUNCH
    assert decision.route_decision is not None
    assert decision.route_decision.graph_shape == "plan_fanout"
