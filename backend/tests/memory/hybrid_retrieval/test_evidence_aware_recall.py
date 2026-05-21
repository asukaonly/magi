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
async def test_self_preference_query_excludes_external_observation_edges(
    seeded_l2_store,
):
    """When a user asks about their own declared preference, INTERESTED_IN
    edges sourced from Chrome history (EXTERNAL_OBSERVATION) must not appear
    in the candidate set."""
    store = seeded_l2_store

    conditions = L2Conditions(
        content_query="用户名字偏好",
        subject_hint="self",
        predicate_family="preference",
    )
    conditions.allowed_evidence_classes = {EvidenceClass.USER_SELF_REPORT.label}

    edges = await store.batch_get_relationships(
        entity_ids=["user:local_user"],
        evidence_classes=list(conditions.allowed_evidence_classes),
    )

    flat = [edge for batch in edges.values() for edge in batch]
    predicates = {edge["predicate"] for edge in flat}
    evidence_classes = {edge.get("evidence_class") for edge in flat}

    assert "INTERESTED_IN" not in predicates, (
        f"INTERESTED_IN leaked into self-preference query; got {predicates}"
    )
    assert evidence_classes <= {EvidenceClass.USER_SELF_REPORT.label}, (
        f"Non-self-report evidence leaked; got {evidence_classes}"
    )
    assert flat, "expected at least one USER_SELF_REPORT edge"
