"""Scope guidance is wrong-register for emotional / crisis turns.

The scope guidance block tells the model how to choose between local-
workspace search and external web search (target locality, resolution
order, prefer-web-first hints). It is task-routing language. In
emotional / crisis turns there is no scope decision to make — the
guidance is just noise that nudges the model toward problem-solving
when the user just wants to be heard.

Memory guidance is intentionally NOT suppressed: memory recall in
casual chat ("你还记得我说过...") is common and the guidance is
already opt-in via memory_query being in selected_tools.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.task_agents.chat.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.chat.handlers import FunctionCallingHandler
from magi.agent.task_agents.common import (
    ExecutionMode,
    IncomingFactKind,
    OrchestrationPlan,
    ToolSelection,
    UserMessagePayload,
)
from magi.personality.turn_planner import PersonaRoutingHint


class _FakeContextService:
    async def build_prompt_package(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return SimpleNamespace(prompt_context={}, system_prompt="sys")


class _FakePromptService:
    def augment_system_prompt_with_reply_context(
        self,
        *,
        system_prompt,
        reply_context=None,
        recent_tool_state=None,
    ):
        _ = (reply_context, recent_tool_state)
        return system_prompt


def _ctx() -> ChatRuntimeContext:
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
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hi",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hi",
            turn_id="turn-1",
        ),
    )


def _intent_with(*, register: str | None, task_hint: dict | None = None) -> IntentDecision:
    return IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.FUNCTION_CALLING,
        reasoning="test",
        memory_route="none",
        task_hint=task_hint or {
            "target_locality": "ambiguous_external_reference",
            "preferred_resolution_order": "ask_or_web_before_external_scan",
            "requires_clarification": True,
        },
        persona_routing_hint=PersonaRoutingHint(register=register) if register else None,
    )


@pytest.mark.asyncio
async def test_scope_guidance_fires_for_task_register() -> None:
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_ctx(),
            intent=_intent_with(register="task"),
            tool_selection=ToolSelection(tools=["web-search", "file_read"], reasoning="t", task_hint={}),
        )
    )
    assert "# Scope Guidance" in request.system_prompt


@pytest.mark.asyncio
async def test_scope_guidance_fires_for_casual_register() -> None:
    """Casual chat that triggers scope guidance (rare but possible —
    '查下这个文件' in casual register) still gets it. Only emotional /
    crisis suppress."""
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_ctx(),
            intent=_intent_with(register="casual"),
            tool_selection=ToolSelection(tools=["web-search"], reasoning="t", task_hint={}),
        )
    )
    assert "# Scope Guidance" in request.system_prompt


@pytest.mark.asyncio
async def test_scope_guidance_suppressed_for_emotional_register() -> None:
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_ctx(),
            intent=_intent_with(register="emotional"),
            tool_selection=ToolSelection(tools=["web-search"], reasoning="t", task_hint={}),
        )
    )
    assert "# Scope Guidance" not in request.system_prompt


@pytest.mark.asyncio
async def test_scope_guidance_suppressed_for_crisis_register() -> None:
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_ctx(),
            intent=_intent_with(register="crisis"),
            tool_selection=ToolSelection(tools=["web-search"], reasoning="t", task_hint={}),
        )
    )
    assert "# Scope Guidance" not in request.system_prompt


@pytest.mark.asyncio
async def test_scope_guidance_fires_when_no_routing_hint() -> None:
    """Backward compat: if the router didn't supply a hint, behave as
    before — append scope guidance whenever the block is non-empty."""
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_ctx(),
            intent=_intent_with(register=None),
            tool_selection=ToolSelection(tools=["web-search"], reasoning="t", task_hint={}),
        )
    )
    assert "# Scope Guidance" in request.system_prompt


@pytest.mark.asyncio
async def test_memory_guidance_not_suppressed_by_emotional_register() -> None:
    """Memory guidance stays register-agnostic: user might recall something
    mid-vent ('上次我难受的时候你说啥来着') and memory_query is the only
    way to get there. The guidance is already opt-in via tool selection."""
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    intent = IntentDecision(
        intent="chat",
        difficulty="normal",
        execution_mode=ExecutionMode.FUNCTION_CALLING,
        reasoning="memory recall",
        memory_route="explicit_query",  # required for memory guidance to fire
        persona_routing_hint=PersonaRoutingHint(register="emotional"),
    )
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_ctx(),
            intent=intent,
            tool_selection=ToolSelection(tools=["memory_query"], reasoning="t", task_hint={}),
        )
    )
    # Memory guidance content is dynamic, so check for the section header.
    assert "memory_query" in request.system_prompt.lower() or "memory" in request.system_prompt.lower()
    # Critical assertion: memory_query is reordered to the front of selected_tools.
    assert request.selected_tools[0] == "memory_query"
