"""Reranking facade for hybrid memory retrieval."""

from __future__ import annotations

from .heuristic_reranker import HeuristicRetrievalReranker
from .models import RetrievalConfig
from .reranker_base import BaseRetrievalReranker, NoopRetrievalReranker
from .reranker_utils import (
    _best_distance,
    _candidate_text_for_item,
    _identifier_key_for_layer,
    _recency_bonus,
    _secondary_timestamp,
)


def build_retrieval_reranker(config: RetrievalConfig) -> BaseRetrievalReranker:
    """Create the configured reranker.

    Heuristic reranking is always active. When ``cross_encoder_enabled``
    is set, a :class:`CrossEncoderReranker` wraps the heuristic stage
    (imported lazily to keep startup lightweight).
    """
    if config.cross_encoder_enabled:
        from .cross_encoder import CrossEncoderReranker

        return CrossEncoderReranker(config)
    return HeuristicRetrievalReranker(config)


__all__ = [
    "BaseRetrievalReranker",
    "HeuristicRetrievalReranker",
    "NoopRetrievalReranker",
    "build_retrieval_reranker",
    "_best_distance",
    "_candidate_text_for_item",
    "_identifier_key_for_layer",
    "_recency_bonus",
    "_secondary_timestamp",
]
