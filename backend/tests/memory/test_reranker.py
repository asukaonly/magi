"""Tests for retrieval reranker backends."""

from __future__ import annotations

import time

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalConfig
from magi.memory.hybrid_retrieval.reranker import (
    HeuristicRetrievalReranker,
    NoopRetrievalReranker,
    _recency_bonus,
    build_retrieval_reranker,
)


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_build_retrieval_reranker_returns_heuristic_by_default():
    config = RetrievalConfig()
    reranker = build_retrieval_reranker(config)
    assert isinstance(reranker, HeuristicRetrievalReranker)


def test_build_retrieval_reranker_returns_cross_encoder_when_enabled():
    config = RetrievalConfig(
        cross_encoder_enabled=True,
        cross_encoder_model_id="bge-reranker-v2-m3",
    )
    reranker = build_retrieval_reranker(config)
    from magi.memory.hybrid_retrieval.cross_encoder import CrossEncoderReranker

    assert isinstance(reranker, CrossEncoderReranker)


# ---------------------------------------------------------------------------
# Noop reranker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noop_reranker_preserves_order():
    config = RetrievalConfig()
    reranker = NoopRetrievalReranker(config)
    items = [
        {"event_id": "a", "content": "first"},
        {"event_id": "b", "content": "second"},
    ]
    result = await reranker.rerank(
        layer="L1",
        results=items,
        query="anything",
        fused_scores={"a": 0.8, "b": 0.5},
    )
    assert [r["event_id"] for r in result] == ["a", "b"]
    assert result[0]["retrieval_score"] == 0.8


# ---------------------------------------------------------------------------
# Heuristic reranker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heuristic_reranker_boosts_user_messages():
    """User-authored messages should rank higher than assistant messages."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {
            "event_id": "assistant-msg",
            "content": "I like crab.",
            "author_type": "assistant",
            "timestamp": 1000.0,
        },
        {
            "event_id": "user-msg",
            "content": "I like fish because it is tender and fresh.",
            "author_type": "user",
            "timestamp": 1001.0,
        },
    ]
    result = await reranker.rerank(
        layer="L1",
        results=items,
        query="what food do I like",
        fused_scores={"assistant-msg": 0.6, "user-msg": 0.5},
    )
    assert result[0]["event_id"] == "user-msg"


@pytest.mark.asyncio
async def test_heuristic_reranker_penalizes_verbose_assistant():
    """Long assistant responses should be penalized."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    short_content = "The meeting is at 3pm."
    long_content = "Here is some general advice. " * 30
    items = [
        {
            "event_id": "long",
            "content": long_content,
            "author_type": "assistant",
            "timestamp": 1000.0,
        },
        {
            "event_id": "short",
            "content": short_content,
            "author_type": "user",
            "timestamp": 1001.0,
        },
    ]
    result = await reranker.rerank(
        layer="L1",
        results=items,
        query="when is the meeting",
        fused_scores={"long": 0.8, "short": 0.7},
    )
    assert result[0]["event_id"] == "short"


@pytest.mark.asyncio
async def test_heuristic_reranker_skips_non_enabled_layers():
    """Layers not in reranker_layers should get noop treatment."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {"summary_id": "a", "content": "summary A"},
        {"summary_id": "b", "content": "summary B"},
    ]
    result = await reranker.rerank(
        layer="L3",
        results=items,
        query="test",
        fused_scores={"a": 0.5, "b": 0.8},
    )
    assert result[0]["summary_id"] == "a"
    assert result[0]["retrieval_score"] == 0.5


@pytest.mark.asyncio
async def test_heuristic_reranker_respects_top_k():
    """Only top_k items should be rescored; remainder keeps original order."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=1)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {"event_id": "a", "content": "hello", "author_type": "user", "timestamp": 1.0},
        {"event_id": "b", "content": "world", "author_type": "user", "timestamp": 2.0},
    ]
    result = await reranker.rerank(
        layer="L1",
        results=items,
        query="hello",
        fused_scores={"a": 0.9, "b": 0.1},
    )
    assert result[0]["reranker_backend"] == "heuristic"
    assert result[1]["reranker_backend"] == "noop"


@pytest.mark.asyncio
async def test_heuristic_reranker_l3_scoring():
    """L3 layer items use generic text scoring."""
    config = RetrievalConfig(reranker_layers=("L3",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {
            "summary_id": "general",
            "content": "General broad advice about life",
            "summary_type": "topic",
            "summary_category": "general",
        },
        {
            "summary_id": "specific",
            "content": "You went hiking on Saturday and sprained your ankle",
            "summary_type": "daily",
            "summary_category": "activity",
        },
    ]
    result = await reranker.rerank(
        layer="L3",
        results=items,
        query="what happened on Saturday hiking",
        fused_scores={"general": 0.6, "specific": 0.5},
    )
    assert result[0]["summary_id"] == "specific"


# ---------------------------------------------------------------------------
# Recency boost tests
# ---------------------------------------------------------------------------


def test_recency_bonus_recent_item_gets_max_boost():
    """An item from right now should get close to alpha (0.15)."""
    bonus = _recency_bonus(time.time())
    assert 0.14 < bonus <= 0.15


def test_recency_bonus_old_item_gets_near_zero():
    """An item from 180 days ago should get negligible bonus."""
    old_ts = time.time() - (180 * 86400)
    bonus = _recency_bonus(old_ts)
    assert bonus < 0.01


def test_recency_bonus_none_returns_zero():
    assert _recency_bonus(None) == 0.0


def test_recency_bonus_zero_timestamp_returns_zero():
    assert _recency_bonus(0) == 0.0


def test_recency_bonus_invalid_returns_zero():
    assert _recency_bonus("not-a-number") == 0.0


@pytest.mark.asyncio
async def test_heuristic_reranker_includes_recency_in_trace():
    """Recency bonus should appear in the retrieval trace."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {
            "event_id": "recent",
            "content": "I ate pizza",
            "author_type": "user",
            "timestamp": time.time(),
        },
    ]
    result = await reranker.rerank(
        layer="L1",
        results=items,
        query="what did I eat",
        fused_scores={"recent": 0.5},
    )
    assert "recency_bonus" in result[0]["retrieval_trace"]
    assert result[0]["retrieval_trace"]["recency_bonus"] > 0.1


@pytest.mark.asyncio
async def test_recency_boost_prefers_recent_over_old():
    """Given equal RRF scores, recent items should rank higher."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {
            "event_id": "old",
            "content": "I went to the park",
            "author_type": "user",
            "timestamp": time.time() - (90 * 86400),
        },
        {
            "event_id": "recent",
            "content": "I went to the park",
            "author_type": "user",
            "timestamp": time.time(),
        },
    ]
    result = await reranker.rerank(
        layer="L1",
        results=items,
        query="park",
        fused_scores={"old": 0.5, "recent": 0.5},
    )
    assert result[0]["event_id"] == "recent"
