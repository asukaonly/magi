"""Soft-edge recognition (RFC #65 P2)."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.soft_edges import (
    is_soft_edge,
)


@pytest.mark.parametrize(
    "marker_key,marker_value",
    [
        pytest.param("fact_kind", "semantic_edge", id="is_soft_edge_by_fact_kind"),
        pytest.param("predicate", "SEMANTIC_CONTEXT", id="is_soft_edge_by_predicate"),
    ],
)
def test_soft_edge_recognizes_supported_markers(marker_key, marker_value):
    assert is_soft_edge({marker_key: marker_value}) is True


def test_hard_edge_is_not_soft():
    assert is_soft_edge({"predicate": "LIKES", "fact_kind": "explicit_fact"}) is False
    assert is_soft_edge({}) is False
