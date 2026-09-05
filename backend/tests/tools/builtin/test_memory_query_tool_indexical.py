"""Verify memory_query tool exposes conversation_context parameter and
plumbs it through to the RetrievalQuery."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi_plugin_sdk.capabilities import ToolCapabilities


def _make_fake_mq(fake_payload=None):
    """Build a minimal fake MemoryQueryPort."""
    if fake_payload is None:
        fake_payload = AsyncMock(
            l0_workbench=[], l1_events=[], l1_evidence_bundles=[],
            l1_timeline_summary=[], l2_entity_cards=[], l2_relationships=[],
            l2_assertions=[], l3_reflections=[], l4_procedures=[], trace={},
        )

    def _build_query(**kwargs):
        from magi.memory.hybrid_retrieval import build_query
        return build_query(**kwargs)

    def _make_turn(**kwargs):
        from magi.memory.hybrid_retrieval.models import ConversationTurn
        return ConversationTurn(**kwargs)

    def _project(**kwargs):
        from magi.memory.retrieval_projection import project_historical_recall
        return project_historical_recall(**kwargs)

    mq = MagicMock(name="memory_query_port")
    mq.build_query.side_effect = _build_query
    mq.query = AsyncMock(return_value=fake_payload)
    mq.get_canonical_names = AsyncMock(return_value={})
    mq.project_historical_recall.side_effect = _project
    mq.make_conversation_turn.side_effect = _make_turn
    return mq


def _make_context(fake_mq, **kwargs):
    from magi.tools.schema import ToolExecutionContext
    caps = ToolCapabilities(memory_query=fake_mq)
    return ToolExecutionContext(agent_id="agent-1", capabilities=caps, **kwargs)


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

    tool = MemoryQueryTool()
    fake_mq = _make_fake_mq()

    await tool.execute(
        parameters={
            "query": "当时我说什么",
            "query_mode": "exact_fact",
            "conversation_context": [
                {"role": "user", "content": "hi", "timestamp": 1.0},
                {"role": "assistant", "content": "hello", "timestamp": 2.0},
            ],
        },
        context=_make_context(
            fake_mq,
            workspace="/tmp",
            env_vars={"user_id": "u1", "session_id": ""},
            permissions=[],
        ),
    )

    call = fake_mq.query.await_args
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
    N=4 PRIOR turns from recent session messages — the current user turn
    (the one that triggered this tool call) is excluded since it IS the
    indexical query."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {"role": "user", "content": "first", "timestamp": 0.5},
        {"role": "user", "content": "hi", "timestamp": 1.0},
        {"role": "assistant", "content": "hello", "timestamp": 2.0},
        {"role": "user", "content": "again", "timestamp": 3.0},
        {"role": "assistant", "content": "again hello", "timestamp": 4.0},
        {"role": "user", "content": "当时我说了什么", "timestamp": 5.0},
    ]
    params = {"query": "当时我说了什么", "query_mode": "exact_fact"}

    enriched = _inject_memory_query_context("memory_query", params, recent)

    assert "conversation_context" in enriched
    # Last 4 PRIOR turns (excluding the current user turn at idx 5).
    assert len(enriched["conversation_context"]) == 4
    # Current turn must NOT appear in the context.
    contents = [t["content"] for t in enriched["conversation_context"]]
    assert "当时我说了什么" not in contents
    # Last preserved turn is the assistant's prior reply.
    assert enriched["conversation_context"][-1]["content"] == "again hello"
    assert enriched["conversation_context"][-1]["role"] == "assistant"
    assert enriched["conversation_context"][-1]["timestamp"] == 4.0
    # Earliest preserved turn is "hi" at the start of the 4-turn window.
    assert enriched["conversation_context"][0]["content"] == "hi"
    # Original parameters must remain untouched (no mutation).
    assert "conversation_context" not in params


def test_inject_excludes_current_user_turn():
    """Round 5 I5: the most recent user message is the current query and
    must not be re-injected as conversation_context."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {"role": "user", "content": "earlier", "timestamp": 1.0},
        {"role": "assistant", "content": "earlier reply", "timestamp": 2.0},
        {"role": "user", "content": "上次我说了什么", "timestamp": 3.0},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "上次我说了什么"}, recent
    )

    cc = enriched["conversation_context"]
    # Only the two prior turns; the current user query is dropped.
    assert len(cc) == 2
    assert cc[0]["content"] == "earlier"
    assert cc[1]["content"] == "earlier reply"
    assert all(t["content"] != "上次我说了什么" for t in cc)


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
        # Current user turn (the indexical query itself) — excluded from
        # injection per Round 5 I5.
        {"role": "user", "content": "当时的内容是什么", "timestamp": 3.5},
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
        {"role": "assistant", "content": "ok", "timestamp": 4.0},
        # Current user turn — excluded from injection per Round 5 I5.
        {"role": "user", "content": "q", "timestamp": 5.0},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "q"}, recent
    )

    assert "conversation_context" in enriched
    # "real text" and "ok" survive; the two empty messages are dropped and
    # the current user turn at idx 4 is excluded.
    contents = [t["content"] for t in enriched["conversation_context"]]
    assert contents == ["real text", "ok"]


def test_inject_tolerates_missing_or_invalid_timestamp():
    """Messages without a timestamp or with non-numeric timestamps default
    to 0.0 rather than raising."""
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    recent = [
        {"role": "user", "content": "no stamp"},
        {"role": "assistant", "content": "bad stamp", "timestamp": "not-a-number"},
        # Current user turn — excluded from injection per Round 5 I5.
        {"role": "user", "content": "current query", "timestamp": 99.0},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "q"}, recent
    )

    assert len(enriched["conversation_context"]) == 2
    assert enriched["conversation_context"][0]["timestamp"] == 0.0
    assert enriched["conversation_context"][1]["timestamp"] == 0.0


def test_inject_preserves_realistic_unix_timestamps():
    """Regression guard for the real-timestamps contract: when the upstream
    threads realistic unix-second timestamps through ``recent_messages``,
    the helper must preserve them so the indexical resolver can produce a
    correct temporal anchor. (When timestamps are missing — see the test
    above — the resolver's epoch-guard kicks in and drops the anchor.)
    """
    from magi.agent.execution.function_calling.tool_execution import (
        _inject_memory_query_context,
    )

    t_real = 1_700_000_100.0  # 2023-11-14
    recent = [
        {"role": "user", "content": "q", "timestamp": t_real - 30},
        {"role": "assistant", "content": "a", "timestamp": t_real},
        # Current user turn — excluded from injection per Round 5 I5.
        {"role": "user", "content": "当时我说什么", "timestamp": t_real + 60},
    ]
    enriched = _inject_memory_query_context(
        "memory_query", {"query": "当时我说什么"}, recent
    )

    cc = enriched["conversation_context"]
    assert all(item["timestamp"] > 1_000_000_000.0 for item in cc), (
        f"timestamps should be realistic unix seconds; got "
        f"{[item['timestamp'] for item in cc]}"
    )
    # Two PRIOR turns preserved; current user turn dropped.
    assert len(cc) == 2
    assert cc[0]["timestamp"] == t_real - 30
    assert cc[1]["timestamp"] == t_real


def test_memory_query_schema_query_mode_is_optional():
    """Phase 4: query_mode parameter must be optional (required=False)."""
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    tool = MemoryQueryTool()
    schema = tool.get_schema()
    qm_param = next(p for p in schema.parameters if p.name == "query_mode")
    assert qm_param.required is False


@pytest.mark.asyncio
async def test_memory_query_executes_without_query_mode():
    """Tool must not crash when parameters dict omits query_mode."""
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool

    tool = MemoryQueryTool()
    fake_mq2 = _make_fake_mq(
        fake_payload=AsyncMock(
            l0_workbench=[], l1_events=[], l1_evidence_bundles=[],
            l1_timeline_summary=[], l2_entity_cards=[], l2_relationships=[],
            l2_assertions=[], l3_reflections=[], l4_procedures=[], trace={},
        )
    )
    result = await tool.execute(
        parameters={"query": "who is asuka"},  # NO query_mode
        context=_make_context(
            fake_mq2,
            workspace="/tmp",
            env_vars={"user_id": "u1", "session_id": ""},
            permissions=[],
        ),
    )

    assert result.success is True
    call = fake_mq2.query.await_args
    request = call.args[0] if call.args else call.kwargs["request"]
    assert request.query_mode is None


@pytest.mark.asyncio
async def test_memory_query_resolves_canonical_names_before_projection():
    """The tool executor must collect entity_ids from the retrieval payload,
    batch-resolve them via get_canonical_names, and pass the resolved dict
    into project_historical_recall.

    We verify by:
    1. Mocking get_canonical_names on the port to return a fixed canonical-name map
    2. Mocking the port to return a payload with l2_relationships referencing
       a specific entity_id
    3. Asserting the resulting envelope's findings use the canonical name
       (not the raw id)"""
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.memory.hybrid_retrieval.models import RetrievalPayload

    tool = MemoryQueryTool()
    fake_payload = RetrievalPayload(
        l2_relationships=[
            {
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "74f953b57f75",
                "confidence": 0.99,
                "status": "active",
            }
        ],
    )

    fake_mq = _make_fake_mq()
    fake_mq.query = AsyncMock(return_value=fake_payload)

    async def fake_lookup(entity_ids):
        return {"user:local_user": "asuka", "74f953b57f75": "字节跳动"}

    fake_mq.get_canonical_names = AsyncMock(side_effect=fake_lookup)

    result = await tool.execute(
        parameters={"query": "who am I interested in"},
        context=_make_context(
            fake_mq,
            workspace="/tmp",
            env_vars={"user_id": "u1", "session_id": ""},
            permissions=[],
        ),
    )

    assert result.success is True
    envelope = result.data["historical_recall"]
    findings = envelope["findings"]
    assert any("字节跳动" in f["statement"] for f in findings), (
        f"expected canonical name '字节跳动' in findings; got {findings}"
    )
    assert not any("74f953b57f75" in str(f) for f in findings), (
        f"raw hash leaked into findings: {findings}"
    )
