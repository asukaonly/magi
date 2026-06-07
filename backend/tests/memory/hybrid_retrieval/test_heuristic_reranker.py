"""Tests for evidence-weight aware reranking in HeuristicRetrievalReranker.

The reranker reads ``evidence_class`` from L2 edge dicts and multiplies the
score by a layer-aware evidence weight prior. This causes equal-fused L2
candidates to resolve in favor of more authoritative evidence.
"""

from __future__ import annotations

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.heuristic_reranker import HeuristicRetrievalReranker
from magi.memory.hybrid_retrieval.models import RetrievalConfig


@pytest.mark.asyncio
async def test_reranker_prefers_higher_evidence_weight():
    """Given two L2 edges with equal fused score, the one with
    USER_SELF_REPORT (weight=1.0) must outrank EXTERNAL_OBSERVATION (weight=0.7).
    """
    config = RetrievalConfig(reranker_layers=("L2",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)

    results = [
        {
            "id": "a",
            "triple_id": "a",
            "evidence_class": EvidenceClass.EXTERNAL_OBSERVATION.label,
            "predicate": "INTERESTED_IN",
            "subject_id": "user:u",
            "object_id": "org:x",
        },
        {
            "id": "b",
            "triple_id": "b",
            "evidence_class": EvidenceClass.USER_SELF_REPORT.label,
            "predicate": "LIKES",
            "subject_id": "user:u",
            "object_id": "topic:rust",
        },
    ]
    fused_scores = {"a": 1.0, "b": 1.0}

    ranked = await reranker.rerank(
        layer="L2", results=results, query="test", fused_scores=fused_scores,
    )
    assert ranked[0]["triple_id"] == "b"


@pytest.mark.asyncio
async def test_reranker_default_weight_for_null_evidence_class():
    """NULL evidence_class (pre-backfill rows) uses default weight 0.5 —
    must outrank ASSISTANT_QUOTE (0.0) and lose to USER_SELF_REPORT (1.0)."""
    config = RetrievalConfig(reranker_layers=("L2",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)

    results = [
        {
            "id": "null_row",
            "triple_id": "null_row",
            "evidence_class": None,
            "predicate": "LIKES",
            "subject_id": "user:u",
            "object_id": "topic:x",
        },
        {
            "id": "quote",
            "triple_id": "quote",
            "evidence_class": EvidenceClass.ASSISTANT_QUOTE.label,
            "predicate": "LIKES",
            "subject_id": "user:u",
            "object_id": "topic:y",
        },
        {
            "id": "declared",
            "triple_id": "declared",
            "evidence_class": EvidenceClass.USER_SELF_REPORT.label,
            "predicate": "LIKES",
            "subject_id": "user:u",
            "object_id": "topic:z",
        },
    ]
    fused_scores = {"null_row": 1.0, "quote": 1.0, "declared": 1.0}

    ranked = await reranker.rerank(
        layer="L2", results=results, query="test", fused_scores=fused_scores,
    )
    triple_ids = [r["triple_id"] for r in ranked]
    assert triple_ids == ["declared", "null_row", "quote"]


@pytest.mark.asyncio
async def test_l1_evidence_weight_ranks_self_report_above_external_observation():
    """Two L1 events with identical text/author_type/fused-score: the one with
    user_self_report (weight=1.0) must outrank external_observation (weight=0.7)
    via the evidence_weight prior alone — author_type is the same so role_bias
    is not the deciding factor."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {"event_id": "obs", "content": "杭州 明天 下雨", "author_type": "user",
         "evidence_class": "external_observation", "timestamp": 1.0},
        {"event_id": "self", "content": "杭州 明天 下雨", "author_type": "user",
         "evidence_class": "user_self_report", "timestamp": 1.0},
    ]
    fused = {"obs": 0.2, "self": 0.2}
    ranked = await reranker.rerank(layer="L1", results=items, query="杭州 明天 下雨", fused_scores=fused)
    assert ranked[0]["event_id"] == "self"
    assert ranked[0]["retrieval_score"] >= ranked[1]["retrieval_score"]


@pytest.mark.asyncio
async def test_l1_evidence_weight_does_not_penalize_unknown_rows():
    """Un-backfilled rows (missing/unknown evidence_class) keep weight 1.0 so they
    are not down-ranked relative to a self-report with the same signal."""
    config = RetrievalConfig(reranker_layers=("L1",), reranker_top_k=10)
    reranker = HeuristicRetrievalReranker(config)
    items = [
        {"event_id": "legacy", "content": "杭州 下雨", "author_type": "user", "timestamp": 1.0},
        {"event_id": "self", "content": "杭州 下雨", "author_type": "user",
         "evidence_class": "user_self_report", "timestamp": 1.0},
    ]
    fused = {"legacy": 0.2, "self": 0.2}
    ranked = await reranker.rerank(layer="L1", results=items, query="杭州 下雨", fused_scores=fused)
    scores = {r["event_id"]: r["retrieval_score"] for r in ranked}
    assert scores["legacy"] == pytest.approx(scores["self"])
