"""Local query relevance over a bounded pool of governed assertions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import RetrievalConfig
from .reranker import build_retrieval_reranker

ASSERTION_CANDIDATE_LIMIT = 256


async def rank_assertions(
    assertions: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    config: RetrievalConfig,
    trace: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rank the entire bounded pool locally before applying the result limit."""
    trace["candidate_count"] = len(assertions)
    if not assertions or not query.strip():
        trace["ranking"] = "not_needed"
        return assertions[:limit]
    ranker = build_retrieval_reranker(replace(
        config, reranker_top_k=ASSERTION_CANDIDATE_LIMIT,
        reranker_layers=("assertion",),
    ))
    candidates = [{
        "id": str(index),
        "content": " | ".join(dict.fromkeys(
            str(item.get(key) or "").strip() for key in (
                "natural_summary", "trait_name", "trait_value", "entity_name", "target_entity_name",
            ) if item.get(key)
        )),
    } for index, item in enumerate(assertions)]
    ranked = await ranker.rerank(
        layer="assertion", results=candidates, query=query, fused_scores={},
    )
    backend = str(ranked[0].get("reranker_backend") or "heuristic")
    trace["ranking"] = "semantic_local" if backend == "cross_encoder" else "lexical"
    if backend != "cross_encoder":
        trace["fallback_reason"] = (
            "local_model_unavailable_or_failed" if config.cross_encoder_enabled else "local_model_disabled"
        )
    output: list[dict[str, Any]] = []
    for item in ranked[:limit]:
        assertion = dict(assertions[int(item["id"])])
        score = max(0.0, float(item.get("reranker_score") or 0.0))
        assertion["_query_relevance_score"] = (
            min(1.0, score) if backend == "cross_encoder" else score / (1.0 + score)
        )
        output.append(assertion)
    trace["selected_count"] = len(output)
    return output
