"""Local query relevance for each page of governed assertions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..l2.semantic_routing import ObjectRole, assertion_predicate_descriptors
from .models import RetrievalConfig
from .reranker import build_retrieval_reranker

ASSERTION_PAGE_SIZE = 64
# This conservative ranking gate is not a calibrated probability threshold.
# Model-specific quality evaluation must establish its recall/precision tradeoff.
_SEMANTIC_RELEVANCE_FLOOR = 0.5
_TARGET_TRAITS = frozenset(
    item.trait_code for item in assertion_predicate_descriptors()
    if item.object_role in {ObjectRole.TARGET_IDENTITY, ObjectRole.TARGET_ID_OR_TEXT}
)


def _answer_text(assertion: dict[str, Any], *, allow_trait_match: bool) -> str:
    """Use stored fact roles, never subject/relation prose, for lexical matching."""
    target = str(assertion.get("target_entity_name") or assertion.get("target") or "").strip()
    if target:
        return target
    if assertion.get("target_entity_id") or assertion.get("trait_name") in _TARGET_TRAITS:
        # Relation values (like/dislike/creator/...) do not identify the answer.
        return ""
    value = str(assertion.get("trait_value") or "").strip()
    if allow_trait_match and value:
        return f"{assertion.get('trait_name') or ''} | {value}"
    return value


async def rank_assertions(
    assertions: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    config: RetrievalConfig,
    trace: dict[str, Any],
    allow_trait_match: bool = False,
) -> list[dict[str, Any]]:
    """Score one governed page and abstain when no candidate is relevant."""
    trace["candidate_count"] = len(assertions)
    if not assertions or not query.strip():
        trace["ranking"] = "not_needed"
        return assertions[:limit]
    ranking_config = replace(
        config, reranker_top_k=len(assertions), reranker_layers=("assertion",),
    )
    lexical_candidates = [{
        "id": str(index), "content": _answer_text(item, allow_trait_match=allow_trait_match),
    } for index, item in enumerate(assertions)]
    if config.cross_encoder_enabled:
        semantic_candidates = [{
            "id": str(index),
            "content": " | ".join(dict.fromkeys(
                str(item.get(key) or "").strip() for key in (
                    "natural_summary", "trait_name", "trait_value", "entity_name", "target_entity_name", "target",
                ) if item.get(key)
            )),
        } for index, item in enumerate(assertions)]
        ranked = await build_retrieval_reranker(ranking_config).rerank(
            layer="assertion", results=semantic_candidates, query=query, fused_scores={},
        )
    else:
        ranked = []
    backend = str(ranked[0].get("reranker_backend") or "heuristic") if ranked else "heuristic"
    if backend != "cross_encoder":
        ranked = await build_retrieval_reranker(replace(
            ranking_config, cross_encoder_enabled=False,
        )).rerank(layer="assertion", results=lexical_candidates, query=query, fused_scores={})
    trace["ranking"] = "semantic_local" if backend == "cross_encoder" else "lexical"
    trace["relevance_gate"] = (
        "uncalibrated_local_score_floor" if backend == "cross_encoder"
        else "positive_answer_field_overlap"
    )
    if backend == "cross_encoder":
        trace["relevance_gate_floor"] = _SEMANTIC_RELEVANCE_FLOOR
        trace["relevance_gate_calibrated"] = False
    if backend != "cross_encoder":
        trace["fallback_reason"] = (
            "local_model_unavailable_or_failed" if config.cross_encoder_enabled else "local_model_disabled"
        )
    output: list[dict[str, Any]] = []
    for item in ranked:
        assertion = dict(assertions[int(item["id"])])
        score = max(0.0, float(item.get("reranker_score") or 0.0))
        if score <= 0.0 or (backend == "cross_encoder" and score < _SEMANTIC_RELEVANCE_FLOOR):
            continue
        assertion["_query_relevance_score"] = (
            min(1.0, score) if backend == "cross_encoder" else score / (1.0 + score)
        )
        output.append(assertion)
        if len(output) >= limit:
            break
    trace["abstained"] = not output
    trace["selected_count"] = len(output)
    return output
