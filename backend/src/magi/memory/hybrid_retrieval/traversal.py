"""Generalized L2 graph traversal: plan contract + typed executor (RFC #65).

P0 scope: a single-hop, typed (predicate/object_type) edge fetch that subsumes
the structured-graph and topology channels' fetch logic. Soft edges, hop2, decay
and ranking_mode are carried on the plan but unused until later phases. This
module is intentionally free of any ``L2GroundingPlan`` dependency — callers map
their grounded plan into a ``TraversalPlan`` and pass execution context as kwargs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class HopSpec:
    """One hop's edge selector: which predicates/types define this hop's answer."""

    predicates: tuple[str, ...] = ()
    object_types: tuple[str, ...] = ()
    include_soft_edges: bool = False


@dataclass
class TraversalPlan:
    """Per-query, derived plan for graph traversal (replaces answer_kind→frozen spec)."""

    seed_entity_ids: list[str] = field(default_factory=list)
    subject_scope: str = "none"
    hop1: HopSpec = field(default_factory=HopSpec)
    hop2: Optional[HopSpec] = None
    max_hops: int = 1
    ranking_mode: str = "confidence"
    decay: float = 0.5
    limit: int = 20
    # provenance: which resolver layer filled each field ("llm"|"embedding"|"keyword_fallback")
    resolution_source: dict[str, str] = field(default_factory=dict)


__all__ = ["HopSpec", "TraversalPlan"]
