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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_order,backend",
    [
        ("default", ["a", "b"], "heuristic"),
        ("enabled", ["b", "a"], "cross_encoder"),
        ("missing_model", ["a", "b"], "heuristic"),
    ],
)
async def test_factory_configuration_controls_actual_scoring(
    mode, expected_order, backend, tmp_path
):
    from unittest.mock import AsyncMock, patch

    config = (
        RetrievalConfig()
        if mode == "default"
        else RetrievalConfig(cross_encoder_enabled=True, cross_encoder_model_id="test-model")
    )
    scorer = AsyncMock()
    scorer.score_pairs.return_value = [0.2, 0.9]
    items = [{"event_id": key, "content": "orchard", "author_type": "user"} for key in ("a", "b")]
    with patch(
        "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_paths",
        return_value=None if mode == "missing_model" else (tmp_path, tmp_path / "model.onnx"),
    ) as resolve, patch(
        "magi.memory.hybrid_retrieval.cross_encoder._get_or_create_scorer",
        new_callable=AsyncMock,
        return_value=scorer,
    ):
        result = await build_retrieval_reranker(config).rerank(
            layer="L1", results=items, query="orchard", fused_scores={"a": 0.8, "b": 0.5}
        )
    assert [item["event_id"] for item in result] == expected_order
    assert [item["reranker_backend"] for item in result] == [backend, backend]
    if mode == "enabled":
        scorer.score_pairs.assert_awaited_once_with(
            [("orchard", "author_type: user\nsource: \ntimestamp: \norchard")] * 2
        )
        assert [item["retrieval_score"] for item in result] == pytest.approx([1.25, 0.55])
    else:
        scorer.score_pairs.assert_not_awaited()
        assert [item["retrieval_score"] for item in result] == pytest.approx([2.15, 1.85])
    if mode == "default":
        resolve.assert_not_called()
    else:
        resolve.assert_called_once_with(config)


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
        fused_scores={"a": 0.2, "b": 0.9},
    )
    assert [r["event_id"] for r in result] == ["a", "b"]
    assert [item["retrieval_score"] for item in result] == [0.2, 0.9]
    assert items == [{"event_id": "a", "content": "first"}, {"event_id": "b", "content": "second"}]


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
@pytest.mark.parametrize(
    "author,expected_order,penalty",
    [("assistant", ["short", "long"], 0.25), ("user", ["long", "short"], 0.0)],
)
async def test_verbosity_penalty_changes_ranking_only_for_assistant_messages(
    author, expected_order, penalty
):
    items = [
        {"event_id": key, "content": "orchard " * repetitions, "author_type": author}
        for key, repetitions in [("long", 60), ("short", 1)]
    ]
    result = await HeuristicRetrievalReranker(RetrievalConfig()).rerank(
        layer="L1", results=items, query="orchard", fused_scores={"long": 0.5, "short": 0.5}
    )
    assert [item["event_id"] for item in result] == expected_order
    by_id = {item["event_id"]: item for item in result}
    assert by_id["long"]["retrieval_trace"]["verbosity_penalty"] == penalty
    assert by_id["short"]["retrieval_trace"]["verbosity_penalty"] == 0
    assert by_id["short"]["retrieval_score"] - by_id["long"]["retrieval_score"] == pytest.approx(
        penalty
    )
    for field in ["role_bias", "token_overlap", "phrase_hits", "recency_bonus", "evidence_weight"]:
        assert by_id["long"]["retrieval_trace"][field] == by_id["short"]["retrieval_trace"][field]


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


def test_recency_bonus_is_nonnegative_bounded_and_decays_at_a_fixed_clock():
    now = 1_800_000_000
    bonuses = [_recency_bonus(now - days * 86400, now=now) for days in [-1, 0, 30, 90, 180]]
    assert bonuses == pytest.approx([0.15, 0.15, 0.06098544896, 0.01008082691, 0.00067748714])
    assert all(0 <= value <= 0.15 for value in bonuses)
    assert bonuses[1] > bonuses[2] > bonuses[3] > bonuses[4]


@pytest.mark.parametrize("timestamp", [None, 0])
def test_missing_timestamp_has_no_recency_bonus(timestamp):
    assert _recency_bonus(timestamp) == 0.0


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
