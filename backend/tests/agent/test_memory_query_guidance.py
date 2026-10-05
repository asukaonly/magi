"""Verify memory-query guidance stays in the right layer.

The memory_query tool schema owns tool-specific parameter rules such as
passing the user's query verbatim and choosing query_mode. The chat prompt keeps
only turn-level guidance about source-of-truth handling and tool ordering.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# The short turn-level guidance block is attached whenever memory_query is in
# the selected tools, regardless of how the upstream router classified the turn.
# Tool-specific parameter details stay in the tool schema.
# ---------------------------------------------------------------------------


class _FakeContextService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def build_prompt_package(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            prompt_context={},
            system_prompt="sys",
            runtime_world_state="world",
            working_context="working",
        )


class _FakePromptService:
    def augment_working_context_with_reply_context(
        self,
        *,
        working_context,
        reply_context=None,
        recent_tool_state=None,
    ):
        _ = (reply_context, recent_tool_state)
        return working_context


def _build_context(message: str = "do you remember when we talked about X"):
    from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext
    from magi.agent.task_agents.common import (
        IncomingFactKind,
        UserMessagePayload,
    )

    return ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        recent_tool_errors=[],
        latest_user_message=message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content=message,
            turn_id="turn-1",
        ),
    )


def _build_handler():
    from magi.agent.task_agents.handlers.handlers import AgentRunHandler

    return AgentRunHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_tools", [["memory_query"], ["web-search"], []])
async def test_selected_capabilities_control_guidance_in_prepared_working_context(selected_tools):
    from magi.agent.task_agents.handlers.contracts import TurnAdmissionDecision
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    from magi.agent.task_agents.common import CapabilitySelection

    handler = _build_handler()
    request = await handler.build_request(
        SimpleNamespace(
            mode=None,
            context=_build_context(),
            admission=TurnAdmissionDecision(
                run_kind="unified_agent_run",
                execution_mode=None,
                reasoning="recall",
            ),
            capabilities=CapabilitySelection(
                tools=selected_tools,
                reasoning="recall",
            ),
        )
    )
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    expected_count = 1 if "memory_query" in selected_tools else 0
    assert request.working_context.count(MEMORY_QUERY_GUIDANCE_BLOCK) == expected_count
    assert request.working_context.startswith("working")
    assert MEMORY_QUERY_GUIDANCE_BLOCK not in request.system_prompt
    assert MEMORY_QUERY_GUIDANCE_BLOCK not in request.runtime_world_state
    assert request.selected_tools == selected_tools
    assert handler._deps.context_service.calls[0]["tools"] == selected_tools
    schema = MemoryQueryTool().to_claude_format()["input_schema"]
    for parameter in ("query", "query_mode"):
        description = schema["properties"][parameter]["description"]
        assert description not in request.working_context
        assert description not in request.system_prompt
    if expected_count:
        assert "source of truth" in request.working_context
        assert "not proof" in request.working_context
