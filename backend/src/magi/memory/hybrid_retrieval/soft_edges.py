"""Shared constants + recognition for L2 SEMANTIC_CONTEXT soft edges (RFC #65 P2).

These co-occurrence edges are written by ``EntityScopedSemanticBuilder`` (which
holds the canonical write-side copies of these constants). This module is the
retrieval-side source of truth for recognizing them in the traversal engine,
edge_vector channel, and fusion.
"""

from __future__ import annotations

from typing import Any

SEMANTIC_EDGE_PREDICATE = "SEMANTIC_CONTEXT"
SEMANTIC_EDGE_FACT_KIND = "semantic_edge"


def is_soft_edge(edge: dict[str, Any]) -> bool:
    """True for SEMANTIC_CONTEXT co-occurrence soft edges."""
    return (
        edge.get("fact_kind") == SEMANTIC_EDGE_FACT_KIND
        or edge.get("predicate") == SEMANTIC_EDGE_PREDICATE
    )


__all__ = ["SEMANTIC_EDGE_PREDICATE", "SEMANTIC_EDGE_FACT_KIND", "is_soft_edge"]
