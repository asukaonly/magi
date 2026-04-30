"""Cross-encoder reranker backed by ONNX Runtime.

Pipeline: Heuristic (always) -> Cross-encoder top-K re-scoring (optional).
The cross-encoder evaluates (query, document) semantic relevance while
heuristic metadata adjustments are preserved and added on top.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cross_encoder_scorer import CrossEncoderScorer, _find_onnx_model
from .models import RetrievalConfig
from .reranker import (
    BaseRetrievalReranker,
    HeuristicRetrievalReranker,
    NoopRetrievalReranker,
    _candidate_text_for_item,
    _secondary_timestamp,
)

logger = logging.getLogger(__name__)

_HEURISTIC_METADATA_KEYS = frozenset({
    "role_bias",
    "fact_density",
    "eventness_score",
    "temporal_anchor_score",
})
_HEURISTIC_PENALTY_KEYS = frozenset({
    "verbosity_penalty",
    "generic_guidance_penalty",
    "generic_penalty",
})

_scorer_cache: dict[str, CrossEncoderScorer] = {}
_scorer_lock = asyncio.Lock()


async def _get_or_create_scorer(model_dir: Path) -> CrossEncoderScorer:
    """Return a cached scorer for the given model directory."""
    key = str(model_dir)
    async with _scorer_lock:
        if key not in _scorer_cache:
            _scorer_cache[key] = CrossEncoderScorer(model_dir)
        return _scorer_cache[key]


def _resolve_cross_encoder_model_dir(config: RetrievalConfig) -> Optional[Path]:
    """Resolve the cross-encoder model directory from config."""
    model_id = (config.cross_encoder_model_id or "").strip()
    if not model_id:
        return None

    from ...utils.runtime import RuntimePaths

    paths = RuntimePaths()
    model_dir = Path(paths.managed_reranker_model_dir(model_id))
    if model_dir.exists() and model_dir.is_dir():
        return model_dir
    return None


class CrossEncoderReranker(BaseRetrievalReranker):
    """Two-stage reranker: heuristic metadata plus cross-encoder semantic scoring."""

    def __init__(self, config: RetrievalConfig) -> None:
        super().__init__(config)
        self._heuristic = HeuristicRetrievalReranker(config)

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        heuristic_results = await self._heuristic.rerank(
            layer=layer,
            results=results,
            query=query,
            fused_scores=fused_scores,
        )
        if not heuristic_results or not self._enabled_for_layer(layer):
            return heuristic_results

        model_dir = _resolve_cross_encoder_model_dir(self._config)
        if model_dir is None:
            logger.debug("Cross-encoder model not available, using heuristic only")
            return heuristic_results

        top_k = max(1, int(self._config.reranker_top_k))
        rerank_slice = list(heuristic_results[:top_k])
        remainder = list(heuristic_results[top_k:])

        try:
            scorer = await _get_or_create_scorer(model_dir)
            pairs = [
                (
                    query,
                    _candidate_text_for_item(
                        layer=layer,
                        item=item,
                        max_chars=self._config.reranker_candidate_max_chars,
                    ),
                )
                for item in rerank_slice
            ]
            ce_scores = await scorer.score_pairs(pairs)
        except Exception:
            logger.warning(
                "Cross-encoder scoring failed, falling back to heuristic",
                exc_info=True,
            )
            return heuristic_results

        scored: list[tuple[float, Dict[str, Any]]] = []
        for item, ce_score in zip(rerank_slice, ce_scores):
            trace = dict(item.get("retrieval_trace") or {})
            metadata_bonus = sum(
                float(trace.get(key, 0.0) or 0.0) for key in _HEURISTIC_METADATA_KEYS
            )
            metadata_penalty = sum(
                float(trace.get(key, 0.0) or 0.0) for key in _HEURISTIC_PENALTY_KEYS
            )
            final_score = ce_score + metadata_bonus - metadata_penalty

            trace.update({
                "backend": "cross_encoder",
                "base_backend": "heuristic",
                "ce_score": round(ce_score, 6),
                "metadata_bonus": round(metadata_bonus, 6),
                "metadata_penalty": round(metadata_penalty, 6),
            })
            enriched = dict(item)
            enriched["retrieval_score"] = final_score
            enriched["retrieval_trace"] = trace
            enriched["reranker_backend"] = "cross_encoder"
            enriched["reranker_score"] = ce_score
            scored.append((final_score, enriched))

        scored.sort(
            key=lambda pair: (pair[0], _secondary_timestamp(pair[1])),
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


__all__ = [
    "CrossEncoderReranker",
    "CrossEncoderScorer",
    "_find_onnx_model",
    "_get_or_create_scorer",
    "_resolve_cross_encoder_model_dir",
]
