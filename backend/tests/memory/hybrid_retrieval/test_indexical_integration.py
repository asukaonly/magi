"""Phase 3 north star: indexical query + conversation_context produces
authoritative routing overrides (episode_recall + conversation_only),
bypassing the LLMIntentDecider chain that would otherwise send the query
to L2 KG.

Design correction (2026-05-22): the resolver no longer produces a
temporal_anchor — '当时/那时/上次' typically reference deep historical
context, not the immediate prior turn ±2min. Phase 3 is now pure routing
override; L1 content matching does the actual finding."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from magi.memory.hybrid_retrieval.indexical_resolver import (
    IndexicalResolution,
    resolve,
)
from magi.memory.hybrid_retrieval.models import (
    ConversationTurn,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.service import HybridRetrievalService


def test_resolve_indexical_query_with_assistant_anchor():
    """Mirror the original bug scenario: user follow-up '当时我怎么说的'
    + 2-turn context where the assistant just said something about names.
    Resolver must return is_indexical=True with the routing override
    (episode_recall + conversation_only) — but NO temporal anchor, since
    '当时' typically references deep history, not the immediate prior
    turn ±2min."""
    T_ASSISTANT = 1700000100.0  # arbitrary unix seconds
    turns = [
        ConversationTurn(role="user", content="你知道我是谁吗",
                         timestamp=T_ASSISTANT - 30),
        ConversationTurn(role="assistant", content="子涵或者哈基米。",
                         timestamp=T_ASSISTANT),
        ConversationTurn(role="user", content="用记忆工具去数据库里看看呢，当时我怎么说的",
                         timestamp=T_ASSISTANT + 60),
    ]

    result = resolve(
        query="用记忆工具去数据库里看看呢，当时我怎么说的",
        conversation_context=turns,
    )

    assert result.is_indexical is True, (
        f"expected indexical detection on '当时'; got {result!r}"
    )
    assert result.force_mode == "episode_recall"
    assert result.l1_retrieval_scope == "conversation_only"
    assert result.cue_matched == "当时"
    assert result.confidence >= 0.9
    # Design correction: never a temporal anchor.
    assert "temporal_anchor" not in IndexicalResolution.__dataclass_fields__


def _empty_memory() -> MagicMock:
    """Build an empty unified-memory mock — all layer stores absent so the
    service skips real DB access. Sufficient for verifying trace overrides."""
    mem = MagicMock()
    mem.l0 = None
    mem.l1 = None
    mem.l2 = None
    mem.l2_entity_catalog = None
    mem.l3 = None
    mem.l4 = None
    return mem


@pytest.mark.asyncio
async def test_service_applies_indexical_overrides_to_request():
    """End-to-end: HybridRetrievalService.query() with an indexical query +
    assistant-bearing context must produce a trace where:
      1. indexical_resolved is True
      2. indexical_cue is the matched cue ('当时')
      3. resolved_query_mode is locked to 'episode_recall' (the caller's
         original 'exact_fact' was overridden by the resolver before the
         intent decider chain ran).
      4. l1_retrieval_scopes is the indexical scope ['conversation_only'].

    Design correction (2026-05-22): the resolver no longer mutates
    request.time_range. The intent_decider's raw_time_range trace key
    must therefore reflect the caller's original time_range (None here).
    """
    T = 1700000100.0
    request = RetrievalQuery(
        query="当时我说什么",
        # Caller-supplied mode that MUST be overridden by the resolver
        query_mode="exact_fact",
        conversation_context=[
            ConversationTurn(role="user", content="q", timestamp=T - 30),
            ConversationTurn(role="assistant", content="a", timestamp=T),
        ],
    )

    svc = HybridRetrievalService(
        _empty_memory(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    payload = await svc.query(request)

    assert isinstance(payload, RetrievalPayload)
    # Core contract — indexical wiring fired and is observable in trace.
    assert payload.trace.get("indexical_resolved") is True
    assert payload.trace.get("indexical_cue") == "当时"
    # Mode was overridden before reaching the intent decider chain.
    assert payload.trace.get("resolved_query_mode") == "episode_recall"
    assert payload.trace.get("query_mode") == "episode_recall"
    # L1 scope override applied authoritatively.
    assert payload.trace.get("l1_retrieval_scopes") == ["conversation_only"]
    # Resolver MUST NOT have mutated time_range — it's now pure routing.
    # No time_range-related key should reflect a synthetic anchor.
    assert "time_range" not in payload.trace, (
        "Phase 3 design correction: resolver must not overlay a time_range; "
        f"got trace={payload.trace!r}"
    )


@pytest.mark.asyncio
async def test_service_marks_orphaned_cue_when_no_context():
    """Cue present but NO conversation context at all → resolver returns
    is_indexical=False with cue_matched populated. Service must surface the
    orphan annotation without forcing episode_recall.

    Design correction (2026-05-22): the orphan gate is now "no context",
    not "no assistant turn" — without anchor extraction the role
    distribution doesn't matter, only that *some* prior context exists
    to ground the follow-up vs. a session-start accidental cue match.
    """
    request = RetrievalQuery(
        query="当时我说什么",
        query_mode="exact_fact",
        conversation_context=None,
    )
    svc = HybridRetrievalService(
        _empty_memory(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    payload = await svc.query(request)

    assert payload.trace.get("indexical_resolved") is not True
    assert payload.trace.get("indexical_cue_orphaned") == "当时"
    # Mode untouched — caller-supplied exact_fact still in effect.
    assert payload.trace.get("resolved_query_mode") == "exact_fact"


@pytest.mark.asyncio
async def test_service_passes_through_when_no_indexical_cue():
    """Plain query with no indexical cue → no resolver-related trace keys
    set. This guards against the wiring leaking into unrelated queries."""
    request = RetrievalQuery(
        query="what's the weather today",
        query_mode="exact_fact",
        conversation_context=None,
    )
    svc = HybridRetrievalService(
        _empty_memory(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    payload = await svc.query(request)

    assert "indexical_resolved" not in payload.trace
    assert "indexical_cue" not in payload.trace
    assert "indexical_cue_orphaned" not in payload.trace
    assert payload.trace.get("resolved_query_mode") == "exact_fact"


@pytest.mark.asyncio
async def test_service_infers_query_mode_when_caller_omits():
    """Phase 4 north star: when query_mode is None and no indexical cue,
    the service calls infer_query_mode, sets a resolved mode, and traces
    mode_source='inferred'."""
    request = RetrievalQuery(
        query="总结一下我最近的活动",  # contains '总结' cue → infer "summary"
        query_mode=None,
        conversation_context=None,
    )
    svc = HybridRetrievalService(
        _empty_memory(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    payload = await svc.query(request)

    assert isinstance(payload, RetrievalPayload)
    assert payload.trace.get("mode_source") == "inferred"
    assert payload.trace.get("inferred_mode") == "summary"
    # The inferred mode flows into the standard resolution pipeline.
    assert payload.trace.get("resolved_query_mode") == "summary"


@pytest.mark.asyncio
async def test_service_traces_caller_when_query_mode_explicit():
    """When the caller explicitly supplies query_mode, trace records
    mode_source='caller' and the caller's mode is preserved unchanged
    (no inference, no indexical override)."""
    request = RetrievalQuery(
        query="who is asuka",
        query_mode="exact_fact",
        conversation_context=None,
    )
    svc = HybridRetrievalService(
        _empty_memory(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    payload = await svc.query(request)

    assert isinstance(payload, RetrievalPayload)
    assert payload.trace.get("mode_source") == "caller"
    # inferred_mode key must NOT leak in for caller-supplied path.
    assert "inferred_mode" not in payload.trace
    # Caller mode preserved through the pipeline.
    assert payload.trace.get("resolved_query_mode") == "exact_fact"
