"""Heuristic reranking backend for hybrid memory retrieval."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .answerability import (
    extract_query_phrases,
    extract_query_tokens,
    extract_quoted_spans,
)
from .reranker_base import BaseRetrievalReranker, NoopRetrievalReranker
from .reranker_utils import (
    _best_distance,
    _identifier_key_for_layer,
    _recency_bonus,
    _secondary_timestamp,
)


class HeuristicRetrievalReranker(BaseRetrievalReranker):
    """Rule-based reranker shared across memory layers."""

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        if not results:
            return []
        if not self._enabled_for_layer(layer):
            return await NoopRetrievalReranker(self._config).rerank(
                layer=layer,
                results=results,
                query=query,
                fused_scores=fused_scores,
            )

        self._rerank_now = time.time()
        top_k = max(1, int(self._config.reranker_top_k))
        rerank_slice = list(results[:top_k])
        remainder = list(results[top_k:])
        scored = [
            self._score_item(layer=layer, item=item, query=query, fused_scores=fused_scores)
            for item in rerank_slice
        ]
        scored.sort(
            key=lambda pair: (
                pair[0],
                _secondary_timestamp(pair[1]),
            ),
            reverse=True,
        )
        reranked = [item for _, item in scored]
        remainder_annotated = await NoopRetrievalReranker(self._config).rerank(
            layer=layer,
            results=remainder,
            query=query,
            fused_scores=fused_scores,
        )
        return reranked + remainder_annotated

    def _score_item(
        self,
        *,
        layer: str,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        if layer == "L1":
            return self._score_l1_item(item=item, query=query, fused_scores=fused_scores)
        if layer == "L3":
            return self._score_l3_item(item=item, query=query, fused_scores=fused_scores)
        if layer == "L4":
            return self._score_l4_item(item=item, query=query, fused_scores=fused_scores)
        return self._score_generic_item(layer=layer, item=item, query=query, fused_scores=fused_scores)

    def _score_l1_item(
        self,
        *,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        query_tokens = extract_query_tokens(query)
        query_phrases = extract_query_phrases(query_tokens)
        quoted_phrases = extract_quoted_spans(query)
        content = str(item.get("content") or "")
        lowered = content.lower()
        content_tokens = set(extract_query_tokens(content))
        matched_tokens = [token for token in query_tokens if token in content_tokens]
        phrase_hits = [phrase for phrase in query_phrases if phrase and phrase in lowered]
        quoted_phrase_hits = [phrase for phrase in quoted_phrases if phrase and phrase in lowered]

        item_id = str(item.get("event_id") or "")
        base_rrf_score = float(fused_scores.get(item_id, 0.0))
        author_type = str(item.get("author_type") or "").strip().lower()
        role_bias = 0.35 if author_type == "user" else (-0.1 if author_type == "assistant" else 0.0)
        token_overlap = (len(matched_tokens) / len(query_tokens)) if query_tokens else 0.0
        phrase_score = min(len(phrase_hits), 3) * 0.25
        quoted_phrase_weight = 0.45 if author_type == "user" else 0.15
        quoted_phrase_score = min(len(quoted_phrase_hits), 2) * quoted_phrase_weight

        verbosity_penalty = 0.0
        if author_type == "assistant" and len(content) > 240:
            verbosity_penalty = min((len(content) - 240) / 600.0, 0.25)
        recency_bonus = _recency_bonus(item.get("timestamp"), now=getattr(self, "_rerank_now", None))

        final_score = (
            base_rrf_score
            + role_bias
            + token_overlap
            + phrase_score
            + quoted_phrase_score
            + recency_bonus
            - verbosity_penalty
        )
        trace = {
            "backend": "heuristic",
            "base_rrf_score": round(base_rrf_score, 6),
            "role_bias": role_bias,
            "token_overlap": round(token_overlap, 6),
            "phrase_hits": phrase_hits,
            "quoted_phrase_hits": quoted_phrase_hits,
            "recency_bonus": round(recency_bonus, 6),
            "verbosity_penalty": round(verbosity_penalty, 6),
            "matched_tokens": matched_tokens,
        }
        enriched = dict(item)
        enriched["retrieval_score"] = final_score
        enriched["retrieval_trace"] = trace
        enriched["reranker_backend"] = "heuristic"
        enriched["reranker_score"] = final_score
        return final_score, enriched

    def _score_l3_item(
        self,
        *,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        text = "\n".join(
            part
            for part in [
                str(item.get("summary_type") or "").strip(),
                str(item.get("summary_category") or "").strip(),
                str(item.get("content") or "").strip(),
            ]
            if part
        )
        return self._score_generic_text_item(
            layer="L3",
            item=item,
            item_id=str(item.get("summary_id") or ""),
            text=text,
            query=query,
            fused_scores=fused_scores,
        )

    def _score_l4_item(
        self,
        *,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        text = "\n".join(
            part
            for part in [
                str(item.get("skill_name") or "").strip(),
                str(item.get("skill_category") or "").strip(),
                str(item.get("optimized_prompt") or "").strip(),
            ]
            if part
        )
        return self._score_generic_text_item(
            layer="L4",
            item=item,
            item_id=str(item.get("skill_id") or ""),
            text=text,
            query=query,
            fused_scores=fused_scores,
        )

    def _score_generic_item(
        self,
        *,
        layer: str,
        item: Dict[str, Any],
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        item_id = str(item.get(_identifier_key_for_layer(layer)) or "")
        text = str(item.get("content") or "")
        return self._score_generic_text_item(
            layer=layer,
            item=item,
            item_id=item_id,
            text=text,
            query=query,
            fused_scores=fused_scores,
        )

    def _score_generic_text_item(
        self,
        *,
        layer: str,
        item: Dict[str, Any],
        item_id: str,
        text: str,
        query: str,
        fused_scores: Dict[str, float],
    ) -> tuple[float, Dict[str, Any]]:
        query_tokens = extract_query_tokens(query)
        query_phrases = extract_query_phrases(query_tokens)
        lowered = text.lower()
        content_tokens = set(extract_query_tokens(text))
        matched_tokens = [token for token in query_tokens if token in content_tokens]
        phrase_hits = [phrase for phrase in query_phrases if phrase and phrase in lowered]
        matched_chunks = item.get("matched_chunks") if isinstance(item.get("matched_chunks"), list) else []
        best_distance = _best_distance(item, matched_chunks)
        token_overlap = (len(matched_tokens) / len(query_tokens)) if query_tokens else 0.0
        phrase_score = min(len(phrase_hits), 3) * 0.22
        chunk_bonus = min(len(matched_chunks), 3) * 0.08
        distance_bonus = max(0.0, 0.3 - best_distance) if best_distance is not None else 0.0
        generic_penalty = 0.0
        if "general" in lowered or "broad advice" in lowered:
            generic_penalty += 0.12

        ts_value = _secondary_timestamp(item)
        recency_bonus = _recency_bonus(ts_value if ts_value > 0 else None, now=getattr(self, "_rerank_now", None))

        base_rrf_score = float(fused_scores.get(item_id, 0.0))
        final_score = (
            base_rrf_score
            + token_overlap
            + phrase_score
            + chunk_bonus
            + distance_bonus
            + recency_bonus
            - generic_penalty
        )
        trace = {
            "backend": "heuristic",
            "layer": layer,
            "base_rrf_score": round(base_rrf_score, 6),
            "token_overlap": round(token_overlap, 6),
            "phrase_hits": phrase_hits,
            "matched_tokens": matched_tokens,
            "chunk_bonus": round(chunk_bonus, 6),
            "best_distance": best_distance,
            "distance_bonus": round(distance_bonus, 6),
            "recency_bonus": round(recency_bonus, 6),
            "generic_penalty": round(generic_penalty, 6),
        }
        enriched = dict(item)
        enriched["retrieval_score"] = final_score
        enriched["retrieval_trace"] = trace
        enriched["reranker_backend"] = "heuristic"
        enriched["reranker_score"] = final_score
        return final_score, enriched


__all__ = ["HeuristicRetrievalReranker"]
