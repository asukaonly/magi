"""Verify the chat LLM's MEMORY_QUERY_GUIDANCE_BLOCK contains the
do-not-paraphrase instruction so the LLM doesn't rewrite the user's
question before calling memory_query (Phase 4)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_guidance_block_forbids_paraphrasing():
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    block = MEMORY_QUERY_GUIDANCE_BLOCK
    # Must explicitly tell the LLM to pass the original query verbatim
    assert "verbatim" in block.lower() or "do not paraphrase" in block.lower(), (
        f"MEMORY_QUERY_GUIDANCE_BLOCK must explicitly forbid paraphrasing; got:\n{block}"
    )
    # Should teach the LLM to pick query_mode by answer-shape (not say "omit it")
    block_lower = block.lower()
    assert "cross_session" in block_lower or "enumerate" in block_lower, (
        "MEMORY_QUERY_GUIDANCE_BLOCK must mention answer-shape guidance (e.g. cross_session)"
    )
    # Must NOT tell the LLM to omit query_mode as the default action
    assert "omit it. the system auto-detects" not in block_lower, (
        "MEMORY_QUERY_GUIDANCE_BLOCK must not say 'omit it' as the primary instruction"
    )


def test_guidance_block_instructs_to_pick_query_mode_by_answer_shape():
    """P2-T3: guidance block must actively teach the LLM to choose query_mode
    based on the shape of the expected answer, consistent with the tool
    description — not tell it to omit the parameter by default."""
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    block = MEMORY_QUERY_GUIDANCE_BLOCK.lower()
    # Must reference answer-shape modes
    assert "cross_session" in block, "Must mention cross_session mode"
    assert "current_state" in block, "Must mention current_state mode"
    # Must not frame passing query_mode as rare / an override
    assert "only pass query_mode when explicitly overriding" not in block
    assert "only override" not in block


# ---------------------------------------------------------------------------
# Phase 4 follow-up (Fix #6): the guidance block MUST be attached whenever
# memory_query is in the selected tools, regardless of how the upstream
# router classified the turn (memory_route).  Originally Phase 4 only
# attached the block when memory_route == "explicit_query", missing turns
# where the selector pulled in memory_query through other routes (low
# confidence routing, future route values, or any path that bypasses
# apply_memory_guidance).
# ---------------------------------------------------------------------------


class _FakeContextService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def build_prompt_package(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
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
        active_orchestrations=[],
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
    from magi.agent.task_agents.handlers.handlers import FunctionCallingHandler

    return FunctionCallingHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )


@pytest.mark.asyncio
async def test_guidance_attached_when_memory_route_explicit_query():
    """Baseline (Phase 4 T5): explicit_query route + memory_query in tools
    must attach the guidance block."""
    from magi.agent.task_agents.handlers.contracts import IntentDecision
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    from magi.agent.task_agents.common import (
        ExecutionMode,
        OrchestrationPlan,
        ToolSelection,
    )

    handler = _build_handler()
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_build_context(),
            intent=IntentDecision(
                intent="chat",
                difficulty="normal",
                execution_mode=ExecutionMode.FUNCTION_CALLING,
                reasoning="recall",
                memory_route="explicit_query",
            ),
            tool_selection=ToolSelection(
                tools=["memory_query"],
                reasoning="recall",
            ),
        )
    )
    assert MEMORY_QUERY_GUIDANCE_BLOCK in request.system_prompt


@pytest.mark.asyncio
async def test_guidance_attached_when_memory_query_selected_but_route_is_none():
    """Phase 4 follow-up (Fix #6): when the router classified the turn as
    non-explicit (memory_route == 'none') but memory_query still ended up in
    selected_tools, the chat LLM MUST still get the don't-paraphrase
    guidance — otherwise the original paraphrase regression returns."""
    from magi.agent.task_agents.handlers.contracts import IntentDecision
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    from magi.agent.task_agents.common import (
        ExecutionMode,
        OrchestrationPlan,
        ToolSelection,
    )

    handler = _build_handler()
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_build_context(),
            intent=IntentDecision(
                intent="chat",
                difficulty="normal",
                execution_mode=ExecutionMode.FUNCTION_CALLING,
                reasoning="tool use",
                memory_route="none",
            ),
            tool_selection=ToolSelection(
                tools=["memory_query", "web-search"],
                reasoning="tool use",
            ),
        )
    )
    assert MEMORY_QUERY_GUIDANCE_BLOCK in request.system_prompt, (
        "Guidance block must be attached whenever memory_query is in "
        "selected_tools, regardless of memory_route classification."
    )


@pytest.mark.asyncio
async def test_guidance_not_attached_when_memory_query_not_selected():
    """Sanity guard: when memory_query is NOT among selected_tools, the
    guidance must NOT be attached even if memory_route is explicit_query."""
    from magi.agent.task_agents.handlers.contracts import IntentDecision
    from magi.agent.task_agents.handlers.handler_helpers import (
        MEMORY_QUERY_GUIDANCE_BLOCK,
    )
    from magi.agent.task_agents.common import (
        ExecutionMode,
        OrchestrationPlan,
        ToolSelection,
    )

    handler = _build_handler()
    request = await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=_build_context(),
            intent=IntentDecision(
                intent="chat",
                difficulty="normal",
                execution_mode=ExecutionMode.FUNCTION_CALLING,
                reasoning="search",
                memory_route="explicit_query",
            ),
            tool_selection=ToolSelection(
                tools=["web-search"],
                reasoning="search",
            ),
        )
    )
    assert MEMORY_QUERY_GUIDANCE_BLOCK not in request.system_prompt


def test_guidance_only_references_valid_query_modes():
    """Guard: every backtick-quoted mode-like token in MEMORY_QUERY_GUIDANCE_BLOCK
    must be a member of the real query_mode enum from the tool schema.
    This test would have caught the exact_match → exact_fact regression."""
    import re

    from magi.agent.task_agents.handlers.handler_helpers import MEMORY_QUERY_GUIDANCE_BLOCK
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    schema = MemoryQueryTool().get_schema()
    qm_param = next(p for p in schema.parameters if p.name == "query_mode")
    valid = set(qm_param.enum)

    # Extract all backtick-quoted tokens
    candidates = set(re.findall(r"`([a-z_]+)`", MEMORY_QUERY_GUIDANCE_BLOCK))

    # Any token that contains an underscore (mode-name shape) and is NOT in
    # valid and is NOT a known non-mode token is a suspect invalid mode reference.
    non_mode_tokens = {"query_mode", "memory_query"}
    suspects = {
        c for c in candidates
        if "_" in c and c not in valid and c not in non_mode_tokens
    }
    assert not suspects, (
        f"MEMORY_QUERY_GUIDANCE_BLOCK references mode-like token(s) that are "
        f"not in the real query_mode enum {sorted(valid)}: {suspects}"
    )

    # Sanity: at least the anchor modes that the guidance is expected to teach
    # must be present
    assert "cross_session" in candidates, "Guidance must mention cross_session mode"
    assert "current_state" in candidates, "Guidance must mention current_state mode"
