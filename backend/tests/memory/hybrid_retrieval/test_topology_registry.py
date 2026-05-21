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
