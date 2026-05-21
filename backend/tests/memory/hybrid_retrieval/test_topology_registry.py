"""Phase 2B north star: TopologySpec + _execute_topology contract.

The registry-driven executor must:
1. Fetch primary edges via batch_get_relationships using spec.primary_predicates
   and spec.primary_object_types, forwarding evidence_classes from the plan.
2. When spec.bridge_predicate is set, issue a second batch_get_relationships
   call (omitting evidence_classes when spec.bridge_skip_evidence_filter is True).
3. Return tagged edges suitable for downstream channel merging.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    L2GroundingPlan,
)


def _make_plan(answer_kind: str, *, with_evidence_filter: bool = True) -> L2GroundingPlan:
    plan = L2GroundingPlan(answer_kind=answer_kind, subject_scope="self")
    plan.subject_candidates = [
        GroundedEntityCandidate(
            entity_id="user:u1",
            entity_type="person",
            surface="self",
            score=1.0,
            source="rule",
        )
    ]
    if with_evidence_filter:
        plan.allowed_evidence_classes = {EvidenceClass.USER_SELF_REPORT.label}
    return plan


@pytest.mark.asyncio
async def test_execute_topology_creator_runs_primary_and_bridge_calls():
    """The creator spec has a PRESENCE_OF bridge — executor must issue
    two batch_get_relationships calls: primary (with evidence_classes) and
    bridge (without — bridge_skip_evidence_filter=True)."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
        _execute_topology,
    )

    store = AsyncMock()
    # First call: primary edges
    store.batch_get_relationships = AsyncMock(
        side_effect=[
            {"user:u1": [
                {"triple_id": "p1", "subject_id": "user:u1",
                 "predicate": "FOLLOWS", "object_id": "presence:acct_a1",
                 "object_type": "presence"},
            ]},
            # Second call: bridge resolution
            {"presence:acct_a1": [
                {"triple_id": "b1", "subject_id": "presence:acct_a1",
                 "predicate": "PRESENCE_OF", "object_id": "person:nana",
                 "object_type": "person", "object": "nana"},
            ]},
        ]
    )

    plan = _make_plan("creator")
    spec = ANSWER_KIND_TOPOLOGIES["creator"]
    result = await _execute_topology(spec=spec, plan=plan, store=store, limit=20)

    # Two store calls — primary + bridge
    assert store.batch_get_relationships.await_count == 2
    primary_call, bridge_call = store.batch_get_relationships.await_args_list

    # Primary call forwards evidence_classes
    assert primary_call.kwargs["evidence_classes"] == [
        EvidenceClass.USER_SELF_REPORT.label
    ]
    assert set(primary_call.kwargs["predicates"]) == {
        "FOLLOWS", "LIKES", "INTERESTED_IN", "DISLIKES"
    }

    # Bridge call OMITS evidence_classes (bridge_skip_evidence_filter=True)
    assert bridge_call.kwargs["evidence_classes"] is None
    assert bridge_call.kwargs["predicates"] == ["PRESENCE_OF"]

    # Bridge resolution attaches _resolved_identity
    assert result[0].get("_resolved_identity") == {
        "object_id": "person:nana",
        "object_type": "person",
        "object": "nana",
    }


def test_registry_has_five_answer_kinds():
    """Phase 2B ships with 5 answer_kinds: creator, place, topic, software, person.
    Adding new answer_kinds in the future means adding a registry entry, NOT
    writing new dispatcher code."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
    )
    assert set(ANSWER_KIND_TOPOLOGIES.keys()) == {
        "creator", "place", "topic", "software", "person",
    }


def test_creator_spec_has_presence_bridge():
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
    )
    spec = ANSWER_KIND_TOPOLOGIES["creator"]
    assert spec.primary_predicates == (
        "FOLLOWS", "LIKES", "INTERESTED_IN", "DISLIKES",
    )
    assert spec.primary_object_types == ("presence", "person")
    assert spec.bridge_predicate == "PRESENCE_OF"
    assert spec.bridge_object_types == ("person",)
    assert spec.bridge_skip_evidence_filter is True


def test_place_spec_has_located_in_bridge():
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
    )
    spec = ANSWER_KIND_TOPOLOGIES["place"]
    assert spec.primary_predicates == ("VISITED", "LIKES", "DISLIKES")
    assert spec.bridge_predicate == "LOCATED_IN"
    assert spec.bridge_skip_evidence_filter is True


def test_topic_spec_has_no_bridge():
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
    )
    spec = ANSWER_KIND_TOPOLOGIES["topic"]
    assert spec.bridge_predicate is None
    assert spec.bridge_object_types == ()


@pytest.mark.asyncio
async def test_execute_topology_topic_has_no_bridge_call():
    """Topic spec has bridge_predicate=None — executor must issue only ONE
    batch_get_relationships call (primary), no bridge resolution."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
        _execute_topology,
    )

    store = AsyncMock()
    store.batch_get_relationships = AsyncMock(
        return_value={"user:u1": [
            {"triple_id": "t1", "subject_id": "user:u1",
             "predicate": "LIKES", "object_id": "topic:rust",
             "object_type": "topic"},
        ]}
    )

    plan = _make_plan("topic")
    spec = ANSWER_KIND_TOPOLOGIES["topic"]
    result = await _execute_topology(spec=spec, plan=plan, store=store, limit=20)

    assert store.batch_get_relationships.await_count == 1
    assert len(result) == 1
    assert result[0]["triple_id"] == "t1"


@pytest.mark.asyncio
async def test_execute_topology_respects_evidence_filter_on_primary_when_no_skip():
    """Topic has bridge_skip_evidence_filter=False (no bridge anyway) — primary
    call still receives the plan's evidence_classes filter."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
        _execute_topology,
    )

    store = AsyncMock()
    store.batch_get_relationships = AsyncMock(return_value={"user:u1": []})

    plan = _make_plan("topic")
    spec = ANSWER_KIND_TOPOLOGIES["topic"]
    await _execute_topology(spec=spec, plan=plan, store=store, limit=20)

    call = store.batch_get_relationships.await_args_list[0]
    assert call.kwargs["evidence_classes"] == [
        EvidenceClass.USER_SELF_REPORT.label
    ]


@pytest.mark.asyncio
async def test_execute_topology_returns_empty_when_no_subject_candidates():
    """No subject candidates → no edges to fetch → return empty list."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
        _execute_topology,
    )

    store = AsyncMock()
    store.batch_get_relationships = AsyncMock()

    plan = L2GroundingPlan(answer_kind="creator", subject_scope="self")
    # plan.subject_candidates left empty
    spec = ANSWER_KIND_TOPOLOGIES["creator"]
    result = await _execute_topology(spec=spec, plan=plan, store=store, limit=20)

    assert result == []
    assert store.batch_get_relationships.await_count == 0


@pytest.mark.asyncio
async def test_execute_topology_with_candidate_object_ids_uses_get_relationships():
    """When constraint preprocessing provides candidate_object_ids (e.g. place
    LOCATED_IN→cafes), executor fetches user→{each candidate} via per-object
    get_relationships instead of batch_get_relationships."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
        _execute_topology,
    )

    store = AsyncMock()
    store.get_relationships = AsyncMock(
        return_value=[
            {"triple_id": "p1", "subject_id": "user:u1",
             "predicate": "VISITED", "object_id": "place:cafe1",
             "object_type": "place"},
        ]
    )
    # Bridge call (LOCATED_IN) — empty for this test
    store.batch_get_relationships = AsyncMock(return_value={})

    plan = _make_plan("place")
    spec = ANSWER_KIND_TOPOLOGIES["place"]
    result = await _execute_topology(
        spec=spec, plan=plan, store=store, limit=20,
        candidate_object_ids=["place:cafe1", "place:cafe2"],
    )

    assert store.get_relationships.await_count == 2  # one per candidate
    first_call = store.get_relationships.await_args_list[0]
    assert first_call.kwargs["subject_id"] == "user:u1"
    assert first_call.kwargs["object_id"] == "place:cafe1"
    assert first_call.kwargs["predicates"] == ["VISITED", "LIKES", "DISLIKES"]
    assert first_call.kwargs["evidence_classes"] == [
        EvidenceClass.USER_SELF_REPORT.label
    ]


def test_place_spec_includes_likes_dislikes_for_affinity_parity():
    """Regression guard: place primary_predicates must include LIKES and DISLIKES
    to preserve parity with the affinity-side scorer (retrieval_projection_findings
    weights LIKES at 0.20 for place — higher than VISITED at 0.15) and the
    semantic-frame predicates_for_semantic_frame('place') path.

    Without this, "what restaurants do I LIKE in Tokyo" queries with no VISITED
    edges silently return empty results."""
    from magi.memory.hybrid_retrieval.topology_registry import (
        ANSWER_KIND_TOPOLOGIES,
    )
    place_predicates = set(ANSWER_KIND_TOPOLOGIES["place"].primary_predicates)
    assert "LIKES" in place_predicates
    assert "DISLIKES" in place_predicates
    assert "VISITED" in place_predicates
