"""Tests for the generalized L2 graph traversal plan + executor (RFC #65 P0)."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.traversal import HopSpec, TraversalPlan


def test_hopspec_defaults_are_empty_and_hard():
    hop = HopSpec()
    assert hop.predicates == ()
    assert hop.object_types == ()
    assert hop.include_soft_edges is False


def test_traversalplan_defaults_single_hop_no_soft():
    tp = TraversalPlan(seed_entity_ids=["user:u1"])
    assert tp.seed_entity_ids == ["user:u1"]
    assert tp.subject_scope == "none"
    assert isinstance(tp.hop1, HopSpec)
    assert tp.hop2 is None
    assert tp.max_hops == 1
    assert tp.ranking_mode == "confidence"
    assert tp.limit == 20
    assert tp.resolution_source == {}


def test_traversalplan_carries_hop1_spec():
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(predicates=("LIKES", "FOLLOWS"), object_types=("media",)),
    )
    assert tp.hop1.predicates == ("LIKES", "FOLLOWS")
    assert tp.hop1.object_types == ("media",)
