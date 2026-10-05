"""Soft-edge recognition (RFC #65 P2)."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.soft_edges import (
    is_soft_edge,
)


@pytest.mark.parametrize(
    "edge,expected",
    [
        ({"fact_kind": "semantic_edge"}, True),
        ({"predicate": "SEMANTIC_CONTEXT"}, True),
        ({"predicate": "LIKES", "fact_kind": "explicit_fact"}, False),
        ({}, False),
    ],
)
def test_soft_edge_classification_requires_an_explicit_marker(edge, expected):
    assert is_soft_edge(edge) is expected
