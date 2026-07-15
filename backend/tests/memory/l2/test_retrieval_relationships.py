"""Tests for L2 knowledge-graph relationship retrieval filters."""

from __future__ import annotations

import time

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.evidence import EvidenceClass
from magi.memory.l2.store import L2CognitionStore


async def _make_store(tmp_path) -> L2CognitionStore:
    db_path = str(tmp_path / "l2.sqlite")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_batch_get_relationships_filters_by_evidence_class(tmp_path):
    store = await _make_store(tmp_path)
    now = time.time()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="INTERESTED_IN",
        object_id="org:x",
        object_type="organization",
        evidence_event_ids=["e1"],
        confidence=0.9,
        observed_at=now,
        source_type="chrome_history",
        evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:rust",
        object_type="topic",
        evidence_event_ids=["e2"],
        confidence=1.0,
        observed_at=now,
        source_type="conversation",
        evidence_class=EvidenceClass.USER_SELF_REPORT.label,
    )

    filtered = await store.batch_get_relationships(
        entity_ids=["user:u1"],
        evidence_classes=[EvidenceClass.USER_SELF_REPORT.label],
    )
    rows = filtered["user:u1"]
    assert len(rows) == 1
    assert rows[0]["predicate"] == "LIKES"

    # No filter -> both returned
    unfiltered = await store.batch_get_relationships(entity_ids=["user:u1"])
    assert len(unfiltered["user:u1"]) == 2


@pytest.mark.asyncio
async def test_get_relationships_filters_by_evidence_class(tmp_path):
    """Single-entity retrieval returns only explicitly matching evidence."""
    store = await _make_store(tmp_path)
    now = time.time()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="INTERESTED_IN",
        object_id="org:x",
        object_type="organization",
        evidence_event_ids=["e1"],
        confidence=0.9,
        observed_at=now,
        source_type="chrome_history",
        evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:rust",
        object_type="topic",
        evidence_event_ids=["e2"],
        confidence=1.0,
        observed_at=now,
        source_type="conversation",
        evidence_class=EvidenceClass.USER_SELF_REPORT.label,
    )

    filtered = await store.get_relationships(
        subject_id="user:u1",
        evidence_classes=[EvidenceClass.USER_SELF_REPORT.label],
    )
    assert len(filtered) == 1
    assert filtered[0]["predicate"] == "LIKES"

    unfiltered = await store.get_relationships(subject_id="user:u1")
    assert len(unfiltered) == 2


@pytest.mark.asyncio
async def test_get_relationships_excludes_unknown_evidence_class(tmp_path):
    """Unknown evidence must not satisfy an explicit evidence-class filter."""
    store = await _make_store(tmp_path)
    now = time.time()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:old",
        object_type="topic",
        evidence_event_ids=["e_legacy"],
        confidence=0.5,
        observed_at=now,
        source_type="legacy",
        # evidence_class deliberately omitted
    )

    filtered = await store.get_relationships(
        subject_id="user:u1",
        evidence_classes=[EvidenceClass.USER_SELF_REPORT.label],
    )
    assert filtered == []


@pytest.mark.asyncio
async def test_batch_get_relationships_excludes_unknown_evidence_class(tmp_path):
    """Batch retrieval applies the same exact evidence-class contract."""
    store = await _make_store(tmp_path)
    now = time.time()

    # Insert a row with NULL evidence_class (simulate pre-backfill state)
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="person",
        predicate="LIKES",
        object_id="topic:old",
        object_type="topic",
        evidence_event_ids=["e_legacy"],
        confidence=0.5,
        observed_at=now,
        source_type="legacy",
        # evidence_class deliberately omitted
    )
    filtered = await store.batch_get_relationships(
        entity_ids=["user:u1"],
        evidence_classes=[EvidenceClass.USER_SELF_REPORT.label],
    )
    assert filtered["user:u1"] == []
