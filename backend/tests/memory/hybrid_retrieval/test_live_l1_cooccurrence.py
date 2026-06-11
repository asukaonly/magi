"""Live L1 co-occurrence fallback adapter (RFC #65 P4)."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.live_l1_cooccurrence import live_l1_cooccurrence_edges


class _FakeL1:
    def __init__(self, entity_events=None, event_entities=None, raises=False):
        self._ee = entity_events or {}
        self._ev = event_entities or {}
        self._raises = raises

    async def get_entity_event_ids(self, seed_ids, **kwargs):
        if self._raises:
            raise RuntimeError("boom")
        return {s: self._ee.get(s, []) for s in seed_ids}

    async def get_event_entity_ids(self, event_ids):
        return {e: self._ev.get(e, []) for e in event_ids}


@pytest.mark.asyncio
async def test_synthesizes_low_conf_soft_edges_ranked_by_frequency():
    l1 = _FakeL1(
        entity_events={"user:u1": ["e1", "e2"]},
        event_entities={"e1": ["user:u1", "topic:rust"],
                        "e2": ["user:u1", "topic:go"]},
    )
    edges = await live_l1_cooccurrence_edges(["user:u1"], l1, limit=10)
    objs = [e["object_id"] for e in edges]
    assert "topic:rust" in objs and "topic:go" in objs
    assert "user:u1" not in objs  # seed excluded
    for e in edges:
        assert e["fact_kind"] == "semantic_edge"
        assert e["predicate"] == "SEMANTIC_CONTEXT"
        assert e["confidence"] == 0.3
        assert e["subject_id"] == "user:u1"
        assert e["_channel"] == "live_l1"
        assert e["triple_id"].startswith("livel1:user:u1:")


@pytest.mark.asyncio
async def test_caps_at_max_live_l1():
    from magi.memory.hybrid_retrieval.live_l1_cooccurrence import MAX_LIVE_L1
    ents = [f"topic:{i}" for i in range(MAX_LIVE_L1 + 5)]
    l1 = _FakeL1(entity_events={"user:u1": ["e1"]},
                 event_entities={"e1": ["user:u1"] + ents})
    edges = await live_l1_cooccurrence_edges(["user:u1"], l1, limit=MAX_LIVE_L1)
    assert len(edges) == MAX_LIVE_L1


@pytest.mark.asyncio
async def test_empty_and_failure_return_empty():
    assert await live_l1_cooccurrence_edges([], _FakeL1()) == []
    assert await live_l1_cooccurrence_edges(["user:u1"], None) == []
    assert await live_l1_cooccurrence_edges(["user:u1"], _FakeL1(raises=True)) == []
    assert await live_l1_cooccurrence_edges(["user:u1"], _FakeL1(entity_events={"user:u1": []})) == []
