"""Soft-edge recognition (RFC #65 P2)."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.soft_edges import (
    SEMANTIC_EDGE_FACT_KIND,
    SEMANTIC_EDGE_PREDICATE,
    is_soft_edge,
)


def test_constants():
    assert SEMANTIC_EDGE_PREDICATE == "SEMANTIC_CONTEXT"
    assert SEMANTIC_EDGE_FACT_KIND == "semantic_edge"


def test_is_soft_edge_by_fact_kind():
    assert is_soft_edge({"fact_kind": "semantic_edge"}) is True


def test_is_soft_edge_by_predicate():
    assert is_soft_edge({"predicate": "SEMANTIC_CONTEXT"}) is True


def test_hard_edge_is_not_soft():
    assert is_soft_edge({"predicate": "LIKES", "fact_kind": "explicit_fact"}) is False
    assert is_soft_edge({}) is False
