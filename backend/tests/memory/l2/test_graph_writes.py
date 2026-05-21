"""Unit tests for L2 knowledge-graph write helpers (Phase 1 evidence-aware)."""

from __future__ import annotations

import time

import pytest

from magi.memory.evidence import EvidenceClass


@pytest.mark.asyncio
async def test_upsert_knowledge_edge_persists_evidence_class(l2_store_with_schema):
    """A freshly-inserted edge must round-trip its evidence_class label."""
    store = l2_store_with_schema
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:rust",
        object_type="topic",
        evidence_event_ids=["evt_1"],
        confidence=1.0,
        observed_at=time.time(),
        source_type="conversation",
        evidence_class=EvidenceClass.USER_SELF_REPORT.label,
    )
    edges = await store.batch_get_relationships(entity_ids=["user:u1"])
    rows = edges["user:u1"]
    assert len(rows) == 1
    assert rows[0]["evidence_class"] == EvidenceClass.USER_SELF_REPORT.label


@pytest.mark.asyncio
async def test_upsert_knowledge_edge_update_preserves_existing_class_when_new_is_none(
    l2_store_with_schema,
):
    """When an edge is re-observed without a new evidence_class, the existing
    value must not be overwritten with NULL."""
    store = l2_store_with_schema
    now = time.time()
    # First write: class set.
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:rust",
        object_type="topic",
        evidence_event_ids=["evt_1"],
        confidence=0.5,
        observed_at=now,
        source_type="conversation",
        evidence_class=EvidenceClass.USER_SELF_REPORT.label,
    )
    # Second write: no class supplied.
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:rust",
        object_type="topic",
        evidence_event_ids=["evt_2"],
        confidence=0.5,
        observed_at=now + 1.0,
        source_type="conversation",
        evidence_class=None,
    )
    edges = await store.batch_get_relationships(entity_ids=["user:u1"])
    rows = edges["user:u1"]
    assert len(rows) == 1
    assert rows[0]["evidence_class"] == EvidenceClass.USER_SELF_REPORT.label


@pytest.mark.asyncio
async def test_upsert_knowledge_edges_batch_persists_evidence_class(
    l2_store_with_schema,
):
    """The batch variant must also forward evidence_class from each candidate."""
    store = l2_store_with_schema
    now = time.time()
    await store.upsert_knowledge_edges(
        [
            dict(
                subject_id="user:u1",
                subject_type="person",
                predicate="LIKES",
                object_id="topic:rust",
                object_type="topic",
                evidence_event_ids=["evt_1"],
                confidence=1.0,
                observed_at=now,
                source_type="conversation",
                evidence_class=EvidenceClass.USER_SELF_REPORT.label,
            ),
            dict(
                subject_id="user:u1",
                subject_type="person",
                predicate="INTERESTED_IN",
                object_id="organization:acme",
                object_type="organization",
                evidence_event_ids=["evt_2"],
                confidence=0.9,
                observed_at=now,
                source_type="chrome_history",
                evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
            ),
        ]
    )
    edges = await store.batch_get_relationships(entity_ids=["user:u1"])
    rows = edges["user:u1"]
    by_predicate = {row["predicate"]: row for row in rows}
    assert by_predicate["LIKES"]["evidence_class"] == EvidenceClass.USER_SELF_REPORT.label
    assert (
        by_predicate["INTERESTED_IN"]["evidence_class"]
        == EvidenceClass.EXTERNAL_OBSERVATION.label
    )
