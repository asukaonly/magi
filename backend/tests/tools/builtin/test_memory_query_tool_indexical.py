"""Verify memory_query tool exposes conversation_context parameter and
plumbs it through to the RetrievalQuery."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.core.tool_capabilities import ToolCapabilities


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


@pytest.fixture
def query_runtime(monkeypatch):
    from agent.permission_helpers import AllowAllPermissionGateway
    from magi.agent.execution.function_calling import FunctionCallingOrchestrator
    from magi.tools.registry import ToolRegistry
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.memory.hybrid_retrieval.models import RetrievalPayload

    mq = _make_fake_mq(RetrievalPayload())
    registry = ToolRegistry()
    registry.register(MemoryQueryTool)
    monkeypatch.setattr(
        "magi.agent.execution.function_calling._registered_tool_execution.build_tool_capabilities",
        lambda: ToolCapabilities(memory_query=mq),
    )
    monkeypatch.setattr("magi.events.tracing._resolve_event_bus", lambda: None)
    runtime = FunctionCallingOrchestrator(
        tool_registry=registry, permission_gateway=AllowAllPermissionGateway()
    )
    return runtime, mq


async def _dispatch_query(query_runtime, tmp_path, recent):
    from copy import deepcopy
    from magi.agent.execution.function_calling import ToolCall
    from magi.events.tracing import drain_pending

    runtime, mq = query_runtime
    arguments = {"query": "当时我说了什么", "query_mode": "exact_fact"}
    original = deepcopy(recent)
    result = await runtime._execute_tool_call(
        tool_call=ToolCall(id="recall-call", name="memory_query", arguments=arguments),
        user_id="u1",
        session_id="s1",
        turn_id="t1",
        execution_preset="chat",
        execution_agent_id="chat:u1",
        execution_workspace=str(tmp_path),
        run_id="r1",
        recent_messages=recent,
    )
    await drain_pending()
    assert result.success is True, result.error
    mq.query.assert_awaited_once()
    assert arguments == {"query": "当时我说了什么", "query_mode": "exact_fact"}
    assert recent == original
    return mq.query.await_args.args[0]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_count", [2, 5])
async def test_dispatcher_delivers_only_bounded_prior_turns_to_retrieval(
    query_runtime, tmp_path, prior_count
):
    from dataclasses import asdict

    prior = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"prior-{i}",
            "timestamp": 1_700_000_000.0 + i * 30,
        }
        for i in range(prior_count)
    ]
    recent = [
        *prior,
        {"role": "user", "content": "当时我说了什么", "timestamp": 1_700_001_000.0},
        {"role": "assistant", "content": "Searching now", "timestamp": 1_700_001_001.0},
    ]
    request = await _dispatch_query(query_runtime, tmp_path, recent)
    assert [asdict(turn) for turn in request.conversation_context] == prior[-4:]
    assert request.user_id == "u1"
    assert request.query_mode == "exact_fact"


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


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [None, []])
async def test_dispatcher_queries_without_history(query_runtime, tmp_path, history):
    request = await _dispatch_query(query_runtime, tmp_path, history)
    assert request.conversation_context is None


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


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp", [{}, {"timestamp": "not-a-number"}, {"timestamp": None}])
async def test_dispatcher_normalizes_invalid_timestamp_without_losing_prior_text(
    query_runtime, tmp_path, timestamp
):
    from dataclasses import asdict

    request = await _dispatch_query(
        query_runtime,
        tmp_path,
        [
            {"role": "assistant", "content": "Earlier answer", **timestamp},
            {"role": "user", "content": "当时我说了什么", "timestamp": 1_700_000_000.0},
        ],
    )
    assert [asdict(turn) for turn in request.conversation_context] == [
        {"role": "assistant", "content": "Earlier answer", "timestamp": 0.0}
    ]


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
