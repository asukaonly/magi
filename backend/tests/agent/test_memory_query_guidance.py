"""Verify memory-query guidance stays in the right layer.

The memory_query tool schema owns tool-specific parameter rules such as
passing the user's query verbatim and choosing query_mode. The chat prompt keeps
only turn-level guidance about source-of-truth handling and tool ordering.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_memory_query_tool_schema_carries_query_contract():
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    schema = MemoryQueryTool().get_schema()
    query_param = next(p for p in schema.parameters if p.name == "query")
    query_mode_param = next(p for p in schema.parameters if p.name == "query_mode")

    query_description = query_param.description.lower()
    assert "verbatim" in query_description
    assert "do not distill" in query_description

    mode_description = query_mode_param.description.lower()
    assert "shape of the answer" in mode_description
    assert "cross_session" in mode_description
    assert "current_state" in mode_description


def test_memory_query_turn_guidance_stays_turn_level():
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )

    block = MEMORY_QUERY_GUIDANCE_BLOCK.lower()
    assert "source of truth" in block
    assert "broader search" in block
    assert "verbatim" not in block
    assert "do not paraphrase" not in block
    assert "query_mode" not in block
    assert "cross_session" not in block
    assert "current_state" not in block
    assert "not proof" in block


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
async def test_guidance_attached_when_memory_query_is_selected():
    """Selecting memory_query attaches turn guidance."""
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
                tools=["memory_query"],
                reasoning="recall",
            ),
        )
    )
    assert MEMORY_QUERY_GUIDANCE_BLOCK in request.working_context


@pytest.mark.asyncio
async def test_guidance_attached_with_other_selected_tools():
    """memory_query guidance remains attached beside other capabilities."""
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
                reasoning="tool use",
            ),
            capabilities=CapabilitySelection(
                tools=["memory_query", "web-search"],
                reasoning="tool use",
            ),
        )
    )
    assert MEMORY_QUERY_GUIDANCE_BLOCK in request.working_context, (
        "Turn guidance must be attached whenever memory_query is in selected_tools, "
        "regardless of other selected capabilities."
    )


@pytest.mark.asyncio
async def test_guidance_not_attached_when_memory_query_not_selected():
    """Sanity guard: when memory_query is NOT among selected_tools, the
    guidance must NOT be attached."""
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
                reasoning="search",
            ),
            capabilities=CapabilitySelection(
                tools=["web-search"],
                reasoning="search",
            ),
        )
    )
    assert MEMORY_QUERY_GUIDANCE_BLOCK not in request.system_prompt


def test_turn_guidance_does_not_duplicate_query_mode_enum():
    from magi.agent.task_agents.handlers.handler_helpers import MEMORY_QUERY_GUIDANCE_BLOCK

    assert "query_mode" not in MEMORY_QUERY_GUIDANCE_BLOCK
    assert "cross_session" not in MEMORY_QUERY_GUIDANCE_BLOCK
    assert "current_state" not in MEMORY_QUERY_GUIDANCE_BLOCK
