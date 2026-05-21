"""Verify memory_query tool exposes conversation_context parameter and
plumbs it through to the RetrievalQuery."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


def test_memory_query_schema_includes_conversation_context_parameter():
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    tool = MemoryQueryTool()
    schema = tool.get_schema()
    param_names = {p.name for p in schema.parameters}
    assert "conversation_context" in param_names, (
        f"expected conversation_context in schema; got {param_names}"
    )
    cc_param = next(p for p in schema.parameters if p.name == "conversation_context")
    assert cc_param.required is False  # optional — auto-injected by runtime


@pytest.mark.asyncio
async def test_memory_query_passes_conversation_context_to_retrieval_query():
    """When the tool executor receives conversation_context in parameters,
    it must propagate to the RetrievalQuery passed to the service."""
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.tools.schema import ToolExecutionContext

    tool = MemoryQueryTool()
    fake_service = AsyncMock()
    fake_service.query = AsyncMock(return_value=AsyncMock(
        l0_workbench=[], l1_events=[], l1_evidence_bundles=[],
        l1_timeline_summary=[], l2_entity_cards=[], l2_relationships=[],
        l2_assertions=[], l3_reflections=[], l4_procedures=[], trace={},
    ))

    with patch.object(tool, "_get_service", return_value=fake_service):
        await tool.execute(
            parameters={
                "query": "当时我说什么",
                "query_mode": "exact_fact",
                "conversation_context": [
                    {"role": "user", "content": "hi", "timestamp": 1.0},
                    {"role": "assistant", "content": "hello", "timestamp": 2.0},
                ],
            },
            context=ToolExecutionContext(
                agent_id="agent-1",
                workspace="/tmp",
                env_vars={"user_id": "u1", "session_id": ""},
                permissions=[],
            ),
        )

    call = fake_service.query.await_args
    request = call.args[0] if call.args else call.kwargs["request"]
    assert request.conversation_context is not None
    assert len(request.conversation_context) == 2
    assert request.conversation_context[0].role == "user"
    assert request.conversation_context[0].content == "hi"


# ---------------------------------------------------------------------------
# T6: dispatcher-side helper that auto-injects conversation_context.
# ---------------------------------------------------------------------------


def test_inject_memory_query_context_when_missing():
    """memory_query call with no explicit conversation_context gets the last
    N=4 turns from recent session messages."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {"role": "user", "content": "hi", "timestamp": 1.0},
        {"role": "assistant", "content": "hello", "timestamp": 2.0},
        {"role": "user", "content": "again", "timestamp": 3.0},
        {"role": "assistant", "content": "again hello", "timestamp": 4.0},
        {"role": "user", "content": "当时我说了什么", "timestamp": 5.0},
    ]
    params = {"query": "当时我说了什么", "query_mode": "exact_fact"}

    enriched = _inject_memory_query_context("memory_query", params, recent)

    assert "conversation_context" in enriched
    # Only the last 4 turns from a 5-turn history.
    assert len(enriched["conversation_context"]) == 4
    assert enriched["conversation_context"][-1]["content"] == "当时我说了什么"
    assert enriched["conversation_context"][-1]["role"] == "user"
    assert enriched["conversation_context"][-1]["timestamp"] == 5.0
    # Earliest turn preserved is the second turn of the original window.
    assert enriched["conversation_context"][0]["content"] == "hello"
    # Original parameters must remain untouched (no mutation).
    assert "conversation_context" not in params


def test_inject_does_not_overwrite_explicit_context():
    """When the caller explicitly passed conversation_context the helper
    must respect it and skip the auto-injection."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    params = {
        "query": "q",
        "conversation_context": [
            {"role": "user", "content": "explicit", "timestamp": 99.0}
        ],
    }
    enriched = _inject_memory_query_context(
        "memory_query",
        params,
        [{"role": "user", "content": "auto", "timestamp": 1.0}],
    )

    assert len(enriched["conversation_context"]) == 1
    assert enriched["conversation_context"][0]["content"] == "explicit"


def test_inject_skips_for_other_tools():
    """Non memory_query tools must never receive conversation_context."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    params = {"query": "q"}
    enriched = _inject_memory_query_context(
        "web_search",
        params,
        [{"role": "user", "content": "hi", "timestamp": 1.0}],
    )
    assert "conversation_context" not in enriched


def test_inject_handles_no_history():
    """No-op when there are no recent messages to inject."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    params = {"query": "q"}
    enriched_empty = _inject_memory_query_context("memory_query", params, [])
    enriched_none = _inject_memory_query_context("memory_query", params, None)
    assert "conversation_context" not in enriched_empty
    assert "conversation_context" not in enriched_none


def test_inject_handles_structured_content_blocks():
    """Messages whose content is a list of typed blocks (text/image) must
    have their text concatenated for the indexical resolver to read."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this"},
                {"type": "image", "mime_type": "image/png", "data": "..."},
            ],
            "timestamp": 1.5,
        },
        {"role": "assistant", "content": "a sunset", "timestamp": 2.5},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "当时的内容是什么"}, recent
    )

    assert len(enriched["conversation_context"]) == 2
    assert enriched["conversation_context"][0]["content"] == "describe this"
    assert enriched["conversation_context"][0]["timestamp"] == 1.5


def test_inject_skips_messages_with_empty_content():
    """Empty content (after coercion) is dropped so the resolver never sees
    placeholder turns."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {"role": "user", "content": "", "timestamp": 1.0},
        {"role": "assistant", "content": "   ", "timestamp": 2.0},
        {"role": "user", "content": "real text", "timestamp": 3.0},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "q"}, recent
    )

    assert "conversation_context" in enriched
    assert len(enriched["conversation_context"]) == 1
    assert enriched["conversation_context"][0]["content"] == "real text"


def test_inject_tolerates_missing_or_invalid_timestamp():
    """Messages without a timestamp or with non-numeric timestamps default
    to 0.0 rather than raising."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {"role": "user", "content": "no stamp"},
        {"role": "assistant", "content": "bad stamp", "timestamp": "not-a-number"},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "q"}, recent
    )

    assert len(enriched["conversation_context"]) == 2
    assert enriched["conversation_context"][0]["timestamp"] == 0.0
    assert enriched["conversation_context"][1]["timestamp"] == 0.0
