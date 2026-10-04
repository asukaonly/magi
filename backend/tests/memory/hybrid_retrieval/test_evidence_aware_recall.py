"""Regression test for evidence-aware L2 retrieval (Phase 1).

Reproduces the production bug where a `predicate_family=preference` query
flood-returned Chrome-history INTERESTED_IN edges instead of the user's
declared name preference. After Phase 1, INTERESTED_IN edges must be
filtered out when the question is a self-preference query.
"""

from __future__ import annotations

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.models import L2Conditions


@pytest.mark.asyncio
@pytest.mark.parametrize("restricted", [False, True])
async def test_grounded_preference_query_applies_evidence_restrictions_to_real_rows(
    seeded_l2_store, restricted
):
    from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
    from magi.memory.hybrid_retrieval.l2_knowledge_retriever import retrieve_knowledge

    conditions = L2Conditions(
        content_query="用户名字偏好",
        subject_hint="self",
        predicate_family="preference",
        allow_soft_edges=False,
        allowed_evidence_classes={EvidenceClass.USER_SELF_REPORT.label} if restricted else None,
    )
    plan = build_grounding_plan(conditions, resolved_entities=[], user_id="local_user")
    edges = await retrieve_knowledge(plan, seeded_l2_store)
    expected = {"preference:address_form:子涵"}
    if not restricted:
        expected |= {
            "organization:74f953b57f75",
            "organization:cbff460f1cac",
            "organization:abc123def456",
        }
    assert len(edges) == len(expected)
    assert {edge["object_id"] for edge in edges} == expected
    assert {edge["evidence_class"] for edge in edges} == (
        {EvidenceClass.USER_SELF_REPORT.label}
        if restricted
        else {EvidenceClass.USER_SELF_REPORT.label, EvidenceClass.EXTERNAL_OBSERVATION.label}
    )
