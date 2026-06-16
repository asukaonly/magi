"""Tests for P4 user agency operations: reject, forget."""

from __future__ import annotations

import time
import pytest

from magi.memory.l2.store import L2CognitionStore


@pytest.fixture
async def store(tmp_path):
    s = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await s.initialize()
    return s


# ── reject_edge ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_edge_marks_user_rejected(store: L2CognitionStore):
    now = time.time()
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user",
        subject_type="user",
        predicate="LIKES",
        object_id="coffee",
        object_type="concept",
        evidence_event_ids=["e1"],
        confidence=0.8,
        observed_at=now,
        source_type="llm",
    )

    result = await store.reject_edge(triple_id=triple_id)
    assert result is not None
    assert result["status"] == "user_rejected"


@pytest.mark.asyncio
async def test_reject_edge_not_found(store: L2CognitionStore):
    result = await store.reject_edge(triple_id="nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_reject_edge_excluded_from_active_query(store: L2CognitionStore):
    now = time.time()
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user",
        subject_type="user",
        predicate="LIKES",
        object_id="tea",
        object_type="concept",
        evidence_event_ids=["e2"],
        confidence=0.8,
        observed_at=now,
        source_type="llm",
    )
    await store.reject_edge(triple_id=triple_id)

    active = await store.get_relationships(subject_id="user", status="active")
    assert all(r["triple_id"] != triple_id for r in active)


# ── forget_entity ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forget_entity_archives_kg_edges(store: L2CognitionStore):
    now = time.time()
    await store.upsert_knowledge_edge(
        subject_id="alice",
        subject_type="person",
        predicate="KNOWS",
        object_id="bob",
        object_type="person",
        evidence_event_ids=["e1"],
        confidence=0.8,
        observed_at=now,
        source_type="llm",
    )
    await store.upsert_knowledge_edge(
        subject_id="charlie",
        subject_type="person",
        predicate="KNOWS",
        object_id="alice",
        object_type="person",
        evidence_event_ids=["e2"],
        confidence=0.7,
        observed_at=now,
        source_type="llm",
    )

    counts = await store.forget_entity(entity_id="alice")
    assert counts["knowledge_graph"] == 2


@pytest.mark.asyncio
async def test_forget_entity_archives_assertions(store: L2CognitionStore):
    now = time.time()
    aid = await store.upsert_assertion_candidate({
        "entity_id": "alice",
        "entity_type": "user",
        "trait_family": "preference",
        "trait_name": "coffee",
        "trait_value": "likes coffee",
        "confidence_score": 0.8,
        "evidence_events": ["e1"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    counts = await store.forget_entity(entity_id="alice")
    assert counts["tom_trait_assertions"] >= 1

    assertion = await store.get_tom_assertion(assertion_id=aid)
    assert assertion is not None
    assert assertion["status"] == "archived"


@pytest.mark.asyncio
async def test_forget_entity_invalidates_episodes(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-1",
        time_start=now - 100,
        time_end=now,
        primary_entity_ids=["alice", "bob"],
    )

    counts = await store.forget_entity(entity_id="alice")
    assert counts["episodes"] == 1

    ep = await store.get_episode(episode_id="ep-1")
    assert ep["status"] == "invalidated"


@pytest.mark.asyncio
async def test_forget_entity_skips_already_archived(store: L2CognitionStore):
    now = time.time()
    tid = await store.upsert_knowledge_edge(
        subject_id="alice",
        subject_type="person",
        predicate="LIKES",
        object_id="coffee",
        object_type="concept",
        evidence_event_ids=["e1"],
        confidence=0.8,
        observed_at=now,
        source_type="llm",
    )
    # Archive it manually first
    await store.reject_edge(triple_id=tid)

    counts = await store.forget_entity(entity_id="alice")
    # Already rejected — should not be counted again
    assert counts["knowledge_graph"] == 0


# ── forget_time_range ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forget_time_range_invalidates_overlapping_episodes(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-inside",
        time_start=now - 200,
        time_end=now - 100,
    )
    await store.create_episode(
        episode_id="ep-outside",
        time_start=now - 50,
        time_end=now,
    )

    counts = await store.forget_time_range(start=now - 250, end=now - 80)
    assert counts["episodes"] == 1

    ep_inside = await store.get_episode(episode_id="ep-inside")
    assert ep_inside["status"] == "invalidated"

    ep_outside = await store.get_episode(episode_id="ep-outside")
    assert ep_outside["status"] == "candidate"


@pytest.mark.asyncio
async def test_forget_time_range_archives_assertions_in_range(store: L2CognitionStore):
    now = time.time()
    aid = await store.upsert_assertion_candidate({
        "entity_id": "user",
        "entity_type": "user",
        "trait_family": "preference",
        "trait_name": "tea",
        "trait_value": "likes tea",
        "confidence_score": 0.8,
        "evidence_events": ["e1"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
        "first_inferred_at": now - 150,
        "last_validated_at": now - 150,
    })

    counts = await store.forget_time_range(start=now - 200, end=now - 100)
    assert counts["tom_trait_assertions"] >= 1

    assertion = await store.get_tom_assertion(assertion_id=aid)
    assert assertion["status"] == "archived"


@pytest.mark.asyncio
async def test_forget_time_range_archives_edges_in_range(store: L2CognitionStore):
    now = time.time()
    tid = await store.upsert_knowledge_edge(
        subject_id="user",
        subject_type="user",
        predicate="VISITED",
        object_id="park",
        object_type="place",
        evidence_event_ids=["e1"],
        confidence=0.8,
        observed_at=now - 150,
        source_type="llm",
    )

    counts = await store.forget_time_range(start=now - 200, end=now - 100)
    assert counts["knowledge_graph"] >= 1

    edge = await store.get_relationship(triple_id=tid)
    assert edge["status"] == "archived"


@pytest.mark.asyncio
async def test_forget_time_range_rejects_invalid_range(store: L2CognitionStore):
    with pytest.raises(ValueError, match="end must be greater"):
        await store.forget_time_range(start=100.0, end=50.0)


# ── forget_episode ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forget_episode_marks_invalidated(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-forget",
        time_start=now - 100,
        time_end=now,
    )

    result = await store.forget_episode(episode_id="ep-forget")
    assert result is not None
    assert result["episode_id"] == "ep-forget"
    assert result["event_ids"] == []

    ep = await store.get_episode(episode_id="ep-forget")
    assert ep["status"] == "invalidated"


@pytest.mark.asyncio
async def test_forget_episode_returns_event_ids_when_requested(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-with-events",
        time_start=now - 100,
        time_end=now,
    )
    await store.add_episode_events(episode_id="ep-with-events", event_ids=["ev1", "ev2", "ev3"])

    result = await store.forget_episode(episode_id="ep-with-events", delete_events=True)
    assert result is not None
    assert set(result["event_ids"]) == {"ev1", "ev2", "ev3"}


# ── forgotten records must not leak back into retrieval (#134) ────


async def _seed_assertion(store: L2CognitionStore, *, entity_id: str) -> str:
    now = time.time()
    return await store.upsert_assertion_candidate({
        "entity_id": entity_id,
        "entity_type": "user",
        "trait_family": "preference",
        "trait_name": "coffee",
        "trait_value": "likes coffee",
        "confidence_score": 0.8,
        "evidence_events": ["e1"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
        "first_inferred_at": now,
        "last_validated_at": now,
    })


_ACTIVE_STATES = ["tentative", "corroborated", "stable"]


@pytest.mark.asyncio
async def test_forgotten_assertion_excluded_from_list(store: L2CognitionStore):
    await _seed_assertion(store, entity_id="alice")

    before = await store.list_tom_assertions(
        entity_id="alice", validation_states=_ACTIVE_STATES
    )
    assert len(before) == 1

    await store.forget_entity(entity_id="alice")

    after = await store.list_tom_assertions(
        entity_id="alice", validation_states=_ACTIVE_STATES
    )
    assert after == []


@pytest.mark.asyncio
async def test_forgotten_assertion_excluded_from_batch_list(store: L2CognitionStore):
    await _seed_assertion(store, entity_id="alice")

    before = await store.batch_list_tom_assertions(
        entity_ids=["alice"], validation_states=_ACTIVE_STATES
    )
    assert len(before["alice"]) == 1

    await store.forget_entity(entity_id="alice")

    after = await store.batch_list_tom_assertions(
        entity_ids=["alice"], validation_states=_ACTIVE_STATES
    )
    assert after["alice"] == []


@pytest.mark.asyncio
async def test_forgotten_episode_excluded_from_fts(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-fts",
        time_start=now - 100,
        time_end=now,
        primary_entity_ids=["alice"],
    )
    await store.index_episode_fts(
        episode_id="ep-fts", summary="hiking trip", label="Hiking", user_label=""
    )

    before = await store.search_episodes_fts(query="hiking")
    assert len(before) == 1

    await store.forget_episode(episode_id="ep-fts")

    after = await store.search_episodes_fts(query="hiking")
    assert after == []


@pytest.mark.asyncio
async def test_forget_episode_not_found(store: L2CognitionStore):
    result = await store.forget_episode(episode_id="nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_forget_episode_without_delete_events_returns_empty(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-no-del",
        time_start=now - 100,
        time_end=now,
    )
    await store.add_episode_events(episode_id="ep-no-del", event_ids=["ev1"])

    result = await store.forget_episode(episode_id="ep-no-del", delete_events=False)
    assert result is not None
    assert result["event_ids"] == []
