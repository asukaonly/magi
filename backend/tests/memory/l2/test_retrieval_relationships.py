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
@pytest.mark.parametrize("query_kind", ["single", "batch"])
async def test_relationship_evidence_filter_selects_only_explicit_matches(tmp_path, query_kind):
    store = await _make_store(tmp_path)
    for object_id, evidence_class in [
        ("topic:external", EvidenceClass.EXTERNAL_OBSERVATION.label),
        ("topic:self", EvidenceClass.USER_SELF_REPORT.label),
        ("topic:unknown", None),
    ]:
        await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="person",
            predicate="LIKES",
            object_id=object_id,
            object_type="topic",
            evidence_event_ids=[object_id],
            confidence=0.9,
            observed_at=time.time(),
            source_type="conversation",
            evidence_class=evidence_class,
        )

    async def read(**filters):
        if query_kind == "single":
            return await store.get_relationships(subject_id="user:u1", **filters)
        return (await store.batch_get_relationships(entity_ids=["user:u1"], **filters))["user:u1"]

    assert {row["object_id"] for row in await read()} == {
        "topic:external",
        "topic:self",
        "topic:unknown",
    }
    assert [
        row["object_id"]
        for row in await read(
            evidence_classes=[EvidenceClass.USER_SELF_REPORT.label],
        )
    ] == ["topic:self"]
