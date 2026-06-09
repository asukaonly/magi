"""Fixtures for ValidateNode tests."""
from __future__ import annotations

from magi.agent.run_control import null_run_control
from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.common.contracts import (
    DirectLLMRequest,
    ExecutionMode,
    IncomingFactKind,
    ToolSelection,
    UserMessagePayload,
)
from magi.config.models import ThinkingDepth
from magi.tools.context_routing import RouteDecision


def build_minimal_request_for_validate() -> DirectLLMRequest:
    """Build a minimal request suitable for ValidateNode.execute().

    ValidateNode reads session_id + workspace from request.context;
    everything else can be defaults. Profile must be 'coding' for
    real production wiring, but the Node itself doesn't gate on profile
    — that's the GraphBuilder's job."""
    payload = UserMessagePayload(
        user_id="user_validate",
        session_id="session_validate",
        content="please fix the bug",
        workspace_path="/tmp/validate_workspace",
    )
    latest_fact = FactRecord(
        agent_id="test-agent",
        event_type="UserMessage",
        payload=payload.to_dict(),
        correlation_id="corr_validate",
    )
    context = ChatRuntimeContext(
        latest_fact=latest_fact,
        recent_facts=[],
        batch_facts=[latest_fact],
        agent_id="test-agent",
        agent_type="chat",
        runtime_key="chat:test",
        user_id="user_validate",
        session_id="session_validate",
        history_key="hk-validate",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        latest_user_message="please fix the bug",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=payload,
        core_model_supports_vision=False,
        control=null_run_control(),
    )
    route = RouteDecision(
        profile="coding", graph_shape="tool_loop", complexity="medium", may_write=True,
    )
    intent = IntentDecision(
        intent="coding",
        execution_mode=ExecutionMode.FUNCTION_CALLING,
        difficulty="normal",
        tools=[],
        route_decision=route,
    )
    return DirectLLMRequest(
        mode=ExecutionMode.FUNCTION_CALLING,
        context=context,
        intent=intent,
        tool_selection=ToolSelection(),
        system_prompt="",
        messages=[],
        thinking_depth=ThinkingDepth.NONE,
    )
