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
