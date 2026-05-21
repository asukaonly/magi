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
