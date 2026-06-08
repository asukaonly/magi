"""TopologySpec data-registry tests + migrated executor contract tests (RFC #65).

Pure-data tests: verify ANSWER_KIND_TOPOLOGIES shape, predicate lists, bridge
fields — these are regression guards for the declarative registry.

Executor tests: equivalent to the removed _execute_topology unit tests, now
exercising ``execute_graph_traversal`` directly with TopologySpec-derived plans.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.traversal import (
    HopSpec,
    TraversalPlan,
    execute_graph_traversal,
)
from magi.memory.hybrid_retrieval.topology_registry import ANSWER_KIND_TOPOLOGIES


# ---------------------------------------------------------------------------
# Pure-data tests (registry shape)
# ---------------------------------------------------------------------------


def test_registry_has_five_answer_kinds():
    """Phase 2B ships with 5 answer_kinds: creator, place, topic, software, person.
    Adding new answer_kinds in the future means adding a registry entry, NOT
    writing new dispatcher code."""
    assert set(ANSWER_KIND_TOPOLOGIES.keys()) == {
        "creator", "place", "topic", "software", "person",
    }


def test_creator_spec_has_presence_bridge():
    spec = ANSWER_KIND_TOPOLOGIES["creator"]
    assert spec.primary_predicates == (
        "FOLLOWS", "LIKES", "INTERESTED_IN", "DISLIKES",
    )
    assert spec.primary_object_types == ("presence", "person")
    assert spec.bridge_predicate == "PRESENCE_OF"
    assert spec.bridge_object_types == ("person",)
    assert spec.bridge_skip_evidence_filter is True


def test_place_spec_has_located_in_bridge():
    spec = ANSWER_KIND_TOPOLOGIES["place"]
    assert spec.primary_predicates == ("VISITED", "LIKES", "DISLIKES")
    assert spec.bridge_predicate == "LOCATED_IN"
    assert spec.bridge_skip_evidence_filter is True


def test_topic_spec_has_no_bridge():
    spec = ANSWER_KIND_TOPOLOGIES["topic"]
    assert spec.bridge_predicate is None
    assert spec.bridge_object_types == ()


def test_place_spec_includes_likes_dislikes_for_affinity_parity():
    """Regression guard: place primary_predicates must include LIKES and DISLIKES
    to preserve parity with the affinity-side scorer (retrieval_projection_findings
    weights LIKES at 0.20 for place — higher than VISITED at 0.15) and the
    semantic-frame predicates_for_semantic_frame('place') path.

    Without this, "what restaurants do I LIKE in Tokyo" queries with no VISITED
    edges silently return empty results."""
    place_predicates = set(ANSWER_KIND_TOPOLOGIES["place"].primary_predicates)
    assert "LIKES" in place_predicates
    assert "DISLIKES" in place_predicates
    assert "VISITED" in place_predicates


def test_software_spec_includes_dislikes_for_negative_polarity_parity():
    """Regression guard: software primary_predicates must include DISLIKES.
    retrieval_projection_findings._default weights DISLIKES at 0.25 for
    negative-polarity queries ("what software do I dislike?"). Without DISLIKES
    in the fetch, those queries silently return empty.

    Same bug pattern as commit 42fe1029 fixed for 'place'."""
    software_predicates = set(ANSWER_KIND_TOPOLOGIES["software"].primary_predicates)
    assert "DISLIKES" in software_predicates
    assert "LIKES" in software_predicates
    assert "USES" in software_predicates


def test_topic_spec_includes_dislikes_for_negative_polarity_parity():
    """Regression guard: topic primary_predicates must include DISLIKES.
    Same rationale as software_spec_includes_dislikes."""
    topic_predicates = set(ANSWER_KIND_TOPOLOGIES["topic"].primary_predicates)
    assert "DISLIKES" in topic_predicates
    assert "LIKES" in topic_predicates
    assert "INTERESTED_IN" in topic_predicates


# ---------------------------------------------------------------------------
# Migrated executor tests (execute_graph_traversal replacing _execute_topology)
# ---------------------------------------------------------------------------


def _creator_traversal() -> TraversalPlan:
    spec = ANSWER_KIND_TOPOLOGIES["creator"]
    return TraversalPlan(
        seed_entity_ids=["user:u1"],
        subject_scope="self",
        hop1=HopSpec(predicates=spec.primary_predicates,
                     object_types=spec.primary_object_types),
        limit=20,
    )


@pytest.mark.asyncio
async def test_executor_creator_primary_only_forwards_evidence():
    store = AsyncMock()
    store.batch_get_relationships = AsyncMock(
        return_value={"user:u1": [{"triple_id": "p1", "subject_id": "user:u1",
                                   "predicate": "FOLLOWS", "object_id": "presence:a1",
                                   "object_type": "presence"}]}
    )
    result = await execute_graph_traversal(
        _creator_traversal(), store, relation_direction="outgoing",
        evidence_classes=["user_self_report"],
    )
    assert store.batch_get_relationships.await_count == 1
    call = store.batch_get_relationships.await_args_list[0]
    assert set(call.kwargs["predicates"]) == {"FOLLOWS", "LIKES", "INTERESTED_IN", "DISLIKES"}
    assert call.kwargs["evidence_classes"] == ["user_self_report"]
    assert "_resolved_identity" not in result[0]


@pytest.mark.asyncio
async def test_executor_returns_empty_when_no_subject():
    """No subject IDs and no predicates/types → abstain path → empty result,
    no store calls issued."""
    store = AsyncMock()
    store.batch_get_relationships = AsyncMock()
    # Empty HopSpec (no predicates, no object_types) triggers the abstain path
    # regardless of seed_entity_ids — no subject + no constraints = junk dump guard.
    tp = TraversalPlan(seed_entity_ids=[], hop1=HopSpec(), limit=20)
    result = await execute_graph_traversal(tp, store)
    assert result == []
    assert store.batch_get_relationships.await_count == 0


@pytest.mark.asyncio
async def test_executor_candidate_mode_per_object_get_relationships():
    store = AsyncMock()
    store.get_relationships = AsyncMock(
        return_value=[{"triple_id": "p1", "subject_id": "user:u1",
                       "predicate": "VISITED", "object_id": "place:cafe1",
                       "object_type": "place"}]
    )
    spec = ANSWER_KIND_TOPOLOGIES["place"]
    tp = TraversalPlan(
        seed_entity_ids=["user:u1"],
        hop1=HopSpec(predicates=spec.primary_predicates),
        limit=20,
    )
    await execute_graph_traversal(
        tp, store, candidate_object_ids=["place:cafe1", "place:cafe2"],
        evidence_classes=["user_self_report"],
    )
    assert store.get_relationships.await_count == 2
    first = store.get_relationships.await_args_list[0]
    assert first.kwargs["object_id"] == "place:cafe1"
    assert first.kwargs["predicates"] == ["VISITED", "LIKES", "DISLIKES"]
    assert first.kwargs["limit"] == 5
