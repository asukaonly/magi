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


@pytest.mark.parametrize(
    "case_positive_predicate,case_answer_kind",
    [
        pytest.param(
            "USES", "software", id="software_spec_includes_dislikes_for_negative_polarity_parity"
        ),
        pytest.param(
            "INTERESTED_IN", "topic", id="topic_spec_includes_dislikes_for_negative_polarity_parity"
        ),
    ],
)
def test_affinity_topology_preserves_positive_and_negative_polarity(
    case_positive_predicate, case_answer_kind
):
    software_predicates = set(ANSWER_KIND_TOPOLOGIES[case_answer_kind].primary_predicates)
    assert "DISLIKES" in software_predicates
    assert "LIKES" in software_predicates
    assert case_positive_predicate in software_predicates


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
        return_value={
            "user:u1": [
                {
                    "triple_id": "p1",
                    "subject_id": "user:u1",
                    "predicate": "FOLLOWS",
                    "object_id": "presence:a1",
                    "object_type": "presence",
                }
            ]
        }
    )
    result = await execute_graph_traversal(
        _creator_traversal(),
        store,
        relation_direction="outgoing",
        evidence_classes=["user_self_report"],
    )
    assert store.batch_get_relationships.await_count == 1
    call = store.batch_get_relationships.await_args_list[0]
    assert set(call.kwargs["predicates"]) == {"FOLLOWS", "LIKES", "INTERESTED_IN", "DISLIKES"}
    assert call.kwargs["evidence_classes"] == ["user_self_report"]
    assert call.kwargs["object_types"] == ["presence", "person"]
    assert [
        (edge["triple_id"], edge["subject_id"], edge["predicate"], edge["object_id"])
        for edge in result
    ] == [("p1", "user:u1", "FOLLOWS", "presence:a1")]
    assert "_resolved_identity" not in result[0]
