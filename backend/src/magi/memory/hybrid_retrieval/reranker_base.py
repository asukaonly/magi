"""Base and pass-through reranker contracts."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import RetrievalConfig
from .reranker_utils import _identifier_key_for_layer


class BaseRetrievalReranker:
    """Base reranker contract."""

    def __init__(self, config: RetrievalConfig) -> None:
        self._config = config

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _enabled_for_layer(self, layer: str) -> bool:
        return layer in set(self._config.reranker_layers)


class NoopRetrievalReranker(BaseRetrievalReranker):
    """Pass-through reranker that only annotates base retrieval metadata."""

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        _ = query
        identifier_key = _identifier_key_for_layer(layer)
        annotated: List[Dict[str, Any]] = []
        for result in results:
            item_id = str(result.get(identifier_key) or "")
            base_score = float(fused_scores.get(item_id, result.get("retrieval_score", 0.0) or 0.0))
            enriched = dict(result)
            enriched["retrieval_score"] = base_score
            enriched["retrieval_trace"] = {
                "backend": "noop",
                "base_rrf_score": round(base_score, 6),
            }
            enriched["reranker_backend"] = "noop"
            enriched["reranker_score"] = base_score
            annotated.append(enriched)
        return annotated


__all__ = ["BaseRetrievalReranker", "NoopRetrievalReranker"]
