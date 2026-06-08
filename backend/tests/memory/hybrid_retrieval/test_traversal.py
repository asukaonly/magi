"""Tests for the generalized L2 graph traversal plan + executor (RFC #65 P0)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.traversal import HopSpec, TraversalPlan, execute_graph_traversal


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


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------

def _store() -> AsyncMock:
    s = AsyncMock()
    s.batch_get_relationships = AsyncMock(return_value={})
    s.get_relationships = AsyncMock(return_value=[])
    return s


@pytest.mark.asyncio
async def test_batch_mode_forwards_typed_filters_and_evidence():
    store = _store()
    store.batch_get_relationships = AsyncMock(
        return_value={"user:u1": [{"triple_id": "t1", "subject_id": "user:u1",
                                    "predicate": "LIKES", "object_id": "topic:rust",
                                    "object_type": "topic"}]}
    )
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(predicates=("LIKES", "DISLIKES"), object_types=("topic",)),
        limit=20,
    )
    edges = await execute_graph_traversal(
        tp, store, relation_direction="outgoing",
        evidence_classes=["user_self_report"],
    )
    assert [e["triple_id"] for e in edges] == ["t1"]
    call = store.batch_get_relationships.await_args_list[0]
    assert call.kwargs["entity_ids"] == ["user:u1"]
    assert call.kwargs["direction"] == "outgoing"
    assert call.kwargs["status_filters"] == ["active"]
    assert call.kwargs["predicates"] == ["LIKES", "DISLIKES"]
    assert call.kwargs["object_types"] == ["topic"]
    assert call.kwargs["limit_per_entity"] == 20
    assert call.kwargs["evidence_classes"] == ["user_self_report"]


@pytest.mark.asyncio
async def test_get_fallback_when_no_subject_forwards_evidence():
    store = _store()
    tp = TraversalPlan(
        seed_entity_ids=[],
        hop1=HopSpec(predicates=("LIKES",), object_types=()),
        limit=20,
    )
    await execute_graph_traversal(
        tp, store, temporal_clause=None, evidence_classes=["user_self_report"],
    )
    assert store.batch_get_relationships.await_count == 0
    call = store.get_relationships.await_args_list[0]
    assert call.kwargs["predicates"] == ["LIKES"]
    assert call.kwargs["status_filters"] == ["active"]
    assert call.kwargs["limit"] == 20
    assert call.kwargs["evidence_classes"] == ["user_self_report"]


@pytest.mark.asyncio
async def test_abstain_when_no_predicate_and_no_object_type():
    store = _store()
    tp = TraversalPlan(seed_entity_ids=["user:u1"], hop1=HopSpec())
    edges = await execute_graph_traversal(tp, store)
    assert edges == []
    assert store.batch_get_relationships.await_count == 0
    assert store.get_relationships.await_count == 0


@pytest.mark.asyncio
async def test_does_not_abstain_when_object_type_present():
    store = _store()
    store.batch_get_relationships = AsyncMock(return_value={"user:u1": []})
    tp = TraversalPlan(seed_entity_ids=["user:u1"], hop1=HopSpec(object_types=("media",)))
    await execute_graph_traversal(tp, store)
    assert store.batch_get_relationships.await_count == 1
    assert store.batch_get_relationships.await_args_list[0].kwargs["predicates"] is None
    assert store.batch_get_relationships.await_args_list[0].kwargs["object_types"] == ["media"]


@pytest.mark.asyncio
async def test_candidate_object_mode_per_object_get_relationships():
    store = _store()
    store.get_relationships = AsyncMock(
        return_value=[{"triple_id": "p1", "subject_id": "user:u1",
                       "predicate": "VISITED", "object_id": "place:cafe1",
                       "object_type": "place"}]
    )
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(predicates=("VISITED", "LIKES", "DISLIKES")),
        limit=20,
    )
    await execute_graph_traversal(
        tp, store, candidate_object_ids=["place:cafe1", "place:cafe2"],
        evidence_classes=["user_self_report"], per_candidate_limit=5,
    )
    assert store.get_relationships.await_count == 2
    first = store.get_relationships.await_args_list[0]
    assert first.kwargs["subject_id"] == "user:u1"
    assert first.kwargs["object_id"] == "place:cafe1"
    assert first.kwargs["predicates"] == ["VISITED", "LIKES", "DISLIKES"]
    assert first.kwargs["limit"] == 5
    assert first.kwargs["evidence_classes"] == ["user_self_report"]
