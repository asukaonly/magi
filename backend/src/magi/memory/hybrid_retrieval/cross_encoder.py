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

from ...config.cross_encoder_registry import get_cross_encoder_registry
from ...utils.runtime import RuntimePaths
from ..onnx_variants import resolve_variant_path
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

_HEURISTIC_METADATA_KEYS = frozenset(
    {
        "role_bias",
        "fact_density",
        "eventness_score",
        "temporal_anchor_score",
    }
)
_HEURISTIC_PENALTY_KEYS = frozenset(
    {
        "verbosity_penalty",
        "generic_guidance_penalty",
        "generic_penalty",
    }
)

_scorer_cache: dict[tuple[str, str], CrossEncoderScorer] = {}
_scorer_lock = asyncio.Lock()


async def _get_or_create_scorer(
    model_dir: Path,
    *,
    model_file_path: Path,
) -> CrossEncoderScorer:
    """Return a cached scorer keyed by (model_dir, resolved variant file path).

    Switching variant produces a different ``model_file_path`` -> different
    cache key -> fresh scorer instance that loads the new file. Old scorers
    stay in the cache until the idle-unload loop kicks in (reranker models
    are small, so the memory cost is negligible).
    """
    key = (str(model_dir), str(model_file_path))
    async with _scorer_lock:
        if key not in _scorer_cache:
            _scorer_cache[key] = CrossEncoderScorer(
                model_dir,
                model_file_path=model_file_path,
            )
        return _scorer_cache[key]


def _resolve_cross_encoder_model_dir(config: RetrievalConfig) -> Optional[Path]:
    """Resolve the cross-encoder model directory from config."""
    model_id = (config.cross_encoder_model_id or "").strip()
    if not model_id:
        return None

    paths = RuntimePaths()
    model_dir = Path(paths.managed_reranker_model_dir(model_id))
    if model_dir.exists() and model_dir.is_dir():
        return model_dir
    return None


def _resolve_cross_encoder_paths(
    config: RetrievalConfig,
) -> Optional[tuple[Path, Path]]:
    """Resolve (model_dir, specific .onnx file) for the configured cross-encoder.

    Returns ``None`` if (a) no model is configured, (b) the model dir doesn't
    exist, or (c) the resolved variant's file isn't on disk. The variant
    override comes from ``config.cross_encoder_variant`` (``None`` means use
    the platform default from the registry).
    """
    model_dir = _resolve_cross_encoder_model_dir(config)
    if model_dir is None:
        return None

    model_id = (config.cross_encoder_model_id or "").strip()
    meta = get_cross_encoder_registry().get(model_id) if model_id else None

    variant_override = config.cross_encoder_variant
    model_file = resolve_variant_path(model_dir, meta, override=variant_override)
    if model_file is None:
        return None
    return model_dir, model_file


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

        paths = _resolve_cross_encoder_paths(self._config)
        if paths is None:
            logger.debug("Cross-encoder model not available, using heuristic only")
            return heuristic_results

        top_k = max(1, int(self._config.reranker_top_k))
        rerank_slice = list(heuristic_results[:top_k])
        remainder = list(heuristic_results[top_k:])

        try:
            scored = await self._score_cross_encoder_slice(
                layer=layer,
                query=query,
                rerank_slice=rerank_slice,
                paths=paths,
            )
        except Exception:
            logger.warning(
                "Cross-encoder scoring failed, falling back to heuristic",
                exc_info=True,
            )
            return heuristic_results

        reranked = self._sort_cross_encoder_scores(scored)
        remainder_annotated = await self._annotate_remainder(
            layer=layer,
            remainder=remainder,
            query=query,
            fused_scores=fused_scores,
        )
        return reranked + remainder_annotated

    async def _score_cross_encoder_slice(
        self,
        *,
        layer: str,
        query: str,
        rerank_slice: List[Dict[str, Any]],
        paths: tuple[Path, Path],
    ) -> list[tuple[float, Dict[str, Any]]]:
        model_dir, model_file = paths
        scorer = await _get_or_create_scorer(model_dir, model_file_path=model_file)
        ce_scores = await scorer.score_pairs(
            self._cross_encoder_pairs(
                layer=layer,
                query=query,
                rerank_slice=rerank_slice,
            )
        )
        return [
            self._score_cross_encoder_item(item, ce_score)
            for item, ce_score in zip(rerank_slice, ce_scores)
        ]

    def _cross_encoder_pairs(
        self,
        *,
        layer: str,
        query: str,
        rerank_slice: List[Dict[str, Any]],
    ) -> list[tuple[str, str]]:
        return [
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

    def _score_cross_encoder_item(
        self,
        item: Dict[str, Any],
        ce_score: float,
    ) -> tuple[float, Dict[str, Any]]:
        trace = dict(item.get("retrieval_trace") or {})
        metadata_bonus = sum(float(trace.get(key, 0.0) or 0.0) for key in _HEURISTIC_METADATA_KEYS)
        metadata_penalty = sum(float(trace.get(key, 0.0) or 0.0) for key in _HEURISTIC_PENALTY_KEYS)
        final_score = ce_score + metadata_bonus - metadata_penalty

        trace.update(
            {
                "backend": "cross_encoder",
                "base_backend": "heuristic",
                "ce_score": round(ce_score, 6),
                "metadata_bonus": round(metadata_bonus, 6),
                "metadata_penalty": round(metadata_penalty, 6),
            }
        )
        enriched = dict(item)
        enriched["retrieval_score"] = final_score
        enriched["retrieval_trace"] = trace
        enriched["reranker_backend"] = "cross_encoder"
        enriched["reranker_score"] = ce_score
        return final_score, enriched

    def _sort_cross_encoder_scores(
        self,
        scored: list[tuple[float, Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        scored.sort(
            key=lambda pair: (pair[0], _secondary_timestamp(pair[1])),
            reverse=True,
        )
        return [item for _, item in scored]

    async def _annotate_remainder(
        self,
        *,
        layer: str,
        remainder: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        return await NoopRetrievalReranker(self._config).rerank(
            layer=layer,
            results=remainder,
            query=query,
            fused_scores=fused_scores,
        )


__all__ = [
    "CrossEncoderReranker",
    "CrossEncoderScorer",
    "_find_onnx_model",
    "_get_or_create_scorer",
    "_resolve_cross_encoder_model_dir",
    "_resolve_cross_encoder_paths",
]
