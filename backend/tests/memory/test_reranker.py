"""Tests for retrieval reranker backends."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalConfig
from magi.memory.hybrid_retrieval.reranker import HeuristicRetrievalReranker, LLMRetrievalReranker


@pytest.mark.asyncio
async def test_llm_reranker_reorders_candidates_with_model_scores(monkeypatch: pytest.MonkeyPatch):
    config = RetrievalConfig(
        reranker_enabled=True,
        reranker_backend="llm",
        reranker_layers=("L1",),
        reranker_top_k=2,
        reranker_mode="remote",
        reranker_remote_provider_id="openai",
        reranker_remote_model="gpt-4o-mini",
    )
    bridge = SimpleNamespace(
        chat_response=AsyncMock(
            side_effect=[
                SimpleNamespace(content='{"score": 0.05}'),
                SimpleNamespace(content='{"score": 0.95}'),
            ]
        )
    )
    base_results = [
        {
            "event_id": "user-fact",
            "content": "The GPS failed after the first service.",
            "timestamp": 2000.0,
            "retrieval_score": 0.8,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.8},
        },
        {
            "event_id": "assistant-answer",
            "content": "The first issue after service was the GPS problem.",
            "timestamp": 2100.0,
            "retrieval_score": 0.4,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.4},
        },
    ]

    async def _fake_base_rerank(self, *, layer, results, query, fused_scores):  # type: ignore[no-untyped-def]
        return list(base_results)

    monkeypatch.setattr(HeuristicRetrievalReranker, "rerank", _fake_base_rerank)

    reranker = LLMRetrievalReranker(config, bridge_builder=lambda _config: bridge)

    results = await reranker.rerank(
        layer="L1",
        results=[
            {"event_id": "user-fact", "content": "The GPS failed after the first service.", "timestamp": 2000.0},
            {"event_id": "assistant-answer", "content": "The first issue after service was the GPS problem.", "timestamp": 2100.0},
        ],
        query="What was the first issue after the first service?",
        fused_scores={"user-fact": 0.8, "assistant-answer": 0.4},
    )

    assert [item["event_id"] for item in results] == ["assistant-answer", "user-fact"]
    assert results[0]["retrieval_trace"]["backend"] == "llm"
    assert results[0]["retrieval_trace"]["llm_score"] == 0.95
    assert results[0]["reranker_backend"] == "llm"


@pytest.mark.asyncio
async def test_llm_reranker_falls_back_when_bridge_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    config = RetrievalConfig(
        reranker_enabled=True,
        reranker_backend="llm",
        reranker_layers=("L1",),
        reranker_top_k=2,
        reranker_mode="remote",
        reranker_remote_provider_id="openai",
        reranker_remote_model="gpt-4o-mini",
    )
    base_results = [
        {
            "event_id": "user-fact",
            "content": "The GPS failed after the first service.",
            "timestamp": 2000.0,
            "retrieval_score": 0.8,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.8},
        },
        {
            "event_id": "assistant-answer",
            "content": "The first issue after service was the GPS problem.",
            "timestamp": 2100.0,
            "retrieval_score": 0.4,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.4},
        },
    ]

    async def _fake_base_rerank(self, *, layer, results, query, fused_scores):  # type: ignore[no-untyped-def]
        return list(base_results)

    monkeypatch.setattr(HeuristicRetrievalReranker, "rerank", _fake_base_rerank)

    reranker = LLMRetrievalReranker(config, bridge_builder=lambda _config: None)

    results = await reranker.rerank(
        layer="L1",
        results=[
            {"event_id": "user-fact", "content": "The GPS failed after the first service.", "timestamp": 2000.0},
            {"event_id": "assistant-answer", "content": "The first issue after service was the GPS problem.", "timestamp": 2100.0},
        ],
        query="What was the first issue after the first service?",
        fused_scores={"user-fact": 0.8, "assistant-answer": 0.4},
    )

    assert [item["event_id"] for item in results] == ["user-fact", "assistant-answer"]
    assert results[0]["retrieval_trace"]["backend"] == "heuristic"
    assert results[0]["retrieval_trace"]["llm_fallback_reason"] == "bridge_unavailable"
