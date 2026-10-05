"""Tests for the generalized L2 graph traversal plan + executor (RFC #65 P0)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.traversal import HopSpec, TraversalPlan, execute_graph_traversal


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
@pytest.mark.parametrize("seeds", [[], ["user:u1"]])
async def test_abstain_when_no_predicate_and_no_object_type(seeds):
    store = _store()
    tp = TraversalPlan(seed_entity_ids=seeds, hop1=HopSpec())
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
async def test_candidate_object_queries_preserve_each_object_filter_and_result():
    from unittest.mock import call
    from magi.memory.hybrid_retrieval.topology_registry import ANSWER_KIND_TOPOLOGIES

    store = _store()
    rows = [
        {
            "triple_id": f"p{i}",
            "subject_id": "user:u1",
            "predicate": "VISITED",
            "object_id": f"place:cafe{i}",
            "object_type": "place",
        }
        for i in (1, 2)
    ]
    store.get_relationships.side_effect = [[row] for row in rows]
    spec = ANSWER_KIND_TOPOLOGIES["place"]
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"], hop1=HopSpec(predicates=spec.primary_predicates), limit=20
    )
    result = await execute_graph_traversal(
        tp,
        store,
        candidate_object_ids=["place:cafe1", "place:cafe2"],
        evidence_classes=["user_self_report"],
        per_candidate_limit=5,
    )
    assert store.get_relationships.await_args_list == [
        call(
            subject_id="user:u1",
            object_id=f"place:cafe{i}",
            predicates=["VISITED", "LIKES", "DISLIKES"],
            status_filters=["active"],
            limit=5,
            evidence_classes=["user_self_report"],
        )
        for i in (1, 2)
    ]
    assert result == rows
    store.batch_get_relationships.assert_not_awaited()


# ---------------------------------------------------------------------------
# Soft-edge sparse fallback tests (RFC #65 P2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soft_fallback_fires_when_hard_sparse_and_allowed():
    store = _store()
    store.batch_get_relationships = AsyncMock(side_effect=[
        {"user:u1": []},  # hard fetch: empty (sparse)
        {"user:u1": [{"triple_id": "s1", "subject_id": "user:u1",
                      "predicate": "SEMANTIC_CONTEXT", "object_id": "media:song1",
                      "fact_kind": "semantic_edge", "confidence": 0.82}]},  # soft fetch
    ])
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(predicates=("LISTENED",), object_types=(), include_soft_edges=True),
    )
    edges = await execute_graph_traversal(tp, store)
    assert any(e["predicate"] == "SEMANTIC_CONTEXT" for e in edges)
    soft_call = store.batch_get_relationships.await_args_list[1]
    assert soft_call.kwargs["predicates"] == ["SEMANTIC_CONTEXT"]
    assert soft_call.kwargs["evidence_classes"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_soft,hard_count", [(True, 5), (False, 0), (False, 1)])
async def test_soft_fallback_is_not_queried_without_permission_or_with_enough_hard_facts(
    allow_soft, hard_count
):
    store = _store()
    hard = [
        {
            "triple_id": f"h{i}",
            "subject_id": "user:u1",
            "predicate": "LISTENED",
            "object_id": f"media:{i}",
            "object_type": "media",
        }
        for i in range(hard_count)
    ]
    store.batch_get_relationships.return_value = {"user:u1": hard}
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(predicates=("LISTENED",), include_soft_edges=allow_soft),
    )
    assert await execute_graph_traversal(tp, store) == hard
    store.batch_get_relationships.assert_awaited_once_with(
        entity_ids=["user:u1"],
        direction="outgoing",
        status_filters=["active"],
        predicates=["LISTENED"],
        object_types=None,
        limit_per_entity=20,
        evidence_classes=None,
        temporal_clause=None,
    )
    store.get_relationships.assert_not_awaited()


@pytest.mark.asyncio
async def test_soft_fallback_fires_on_abstain_when_allowed():
    """Abstain (no predicate, no object_type) → hard=[] is sparse → soft fires if allowed."""
    store = _store()
    store.batch_get_relationships = AsyncMock(return_value={"user:u1": [
        {"triple_id": "s1", "subject_id": "user:u1", "predicate": "SEMANTIC_CONTEXT",
         "object_id": "x", "fact_kind": "semantic_edge", "confidence": 0.8}]})
    tp = TraversalPlan(seed_entity_ids=["user:u1"], hop1=HopSpec(include_soft_edges=True))
    edges = await execute_graph_traversal(tp, store)
    assert any(e["predicate"] == "SEMANTIC_CONTEXT" for e in edges)
    assert store.batch_get_relationships.await_count == 1
    assert store.batch_get_relationships.await_args_list[0].kwargs["predicates"] == ["SEMANTIC_CONTEXT"]


# ---------------------------------------------------------------------------
# Second-hop expansion tests (RFC #65 P3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("expand", [False, True])
async def test_two_hop_expands_from_bridge_nodes(expand):
    store = _store()
    store.batch_get_relationships = AsyncMock(
        side_effect=[
            {
                "user:u1": [
                    {
                        "triple_id": "h1",
                        "subject_id": "user:u1",
                        "predicate": "LIKES",
                        "object_id": "person:artist",
                        "object_type": "person",
                    }
                ]
            },  # hop1
            {
                "person:artist": [
                    {
                        "triple_id": "h2",
                        "subject_id": "person:artist",
                        "predicate": "CREATES",
                        "object_id": "media:album",
                        "object_type": "media",
                    }
                ]
            },  # hop2 hard
            {
                "person:artist": [
                    {
                        "triple_id": "s2",
                        "subject_id": "person:artist",
                        "predicate": "SEMANTIC_CONTEXT",
                        "object_id": "media:album2",
                        "object_type": "media",
                        "fact_kind": "semantic_edge",
                    }
                ]
            },  # hop2 soft
        ]
    )
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(
            predicates=("LIKES",), object_types=("person",)
        ),  # no hop1 soft (default False)
        hop2=HopSpec(object_types=("media",), include_soft_edges=True) if expand else None,
        max_hops=2,
    )
    edges = await execute_graph_traversal(tp, store)
    assert [(edge["triple_id"], edge["object_id"], edge.get("_hop", 1)) for edge in edges] == (
        [("h1", "person:artist", 1), ("h2", "media:album", 2), ("s2", "media:album2", 2)]
        if expand
        else [("h1", "person:artist", 1)]
    )
    assert store.batch_get_relationships.await_count == (3 if expand else 1)
    if expand:
        second, soft = store.batch_get_relationships.await_args_list[1:]
        assert second.kwargs["entity_ids"] == soft.kwargs["entity_ids"] == ["person:artist"]
        assert second.kwargs["object_types"] == soft.kwargs["object_types"] == ["media"]
        assert second.kwargs["predicates"] is None
        assert soft.kwargs["predicates"] == ["SEMANTIC_CONTEXT"]


@pytest.mark.asyncio
async def test_no_second_hop_when_hop1_empty():
    store = _store()
    store.batch_get_relationships = AsyncMock(return_value={"user:u1": []})
    tp = TraversalPlan(seed_entity_ids=["user:u1"],
                       hop1=HopSpec(predicates=("LIKES",), object_types=("person",)),
                       hop2=HopSpec(object_types=("media",), include_soft_edges=True), max_hops=2)
    await execute_graph_traversal(tp, store)
    assert store.batch_get_relationships.await_count == 1  # hop1 empty → no bridges → no hop2
