"""Phase 3 north star: indexical query + conversation_context produces
authoritative routing overrides (episode_recall + conversation_only +
temporal anchor), bypassing the LLMIntentDecider chain that would otherwise
send the query to L2 KG."""

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
    Resolver must return is_indexical=True with anchor from the assistant turn."""
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
    assert result.temporal_anchor is not None
    start, end = result.temporal_anchor
    # Anchor on the assistant turn ±120s
    assert start == T_ASSISTANT - 120.0
    assert end == T_ASSISTANT + 120.0
    assert result.cue_matched == "当时"
    assert result.confidence >= 0.9


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


@pytest.mark.asyncio
async def test_service_marks_orphaned_cue_when_no_assistant_turn():
    """Cue present but no assistant turn in context → resolver returns
    is_indexical=False with cue_matched populated. Service must surface the
    orphan annotation without forcing episode_recall."""
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
