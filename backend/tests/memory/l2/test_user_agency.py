"""Tests for P4 user agency operations: reject, forget."""

from __future__ import annotations

import json
import time
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.governance import forgetting as forgetting_module
from magi.memory.l2.graph.versions import append_knowledge_graph_version
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
    aid = await store.upsert_assertion_candidate(
        {
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
        }
    )

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
async def test_forget_entity_matches_episode_entity_ids_exactly(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(
        episode_id="ep-exact",
        time_start=now - 100,
        time_end=now,
        primary_entity_ids=["alice"],
    )
    await store.create_episode(
        episode_id="ep-substring",
        time_start=now - 100,
        time_end=now,
        primary_entity_ids=["malice"],
    )

    counts = await store.forget_entity(entity_id="alice")

    assert counts["episodes"] == 1
    assert (await store.get_episode(episode_id="ep-exact"))["status"] == "invalidated"
    assert (await store.get_episode(episode_id="ep-substring"))["status"] == "candidate"


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


@pytest.mark.asyncio
async def test_forget_entity_strengthens_an_earlier_time_range_forget(
    store: L2CognitionStore,
):
    observed_at = time.time() - 150
    triple_id = await store.upsert_knowledge_edge(
        subject_id="alice",
        subject_type="person",
        predicate="LIKES",
        object_id="coffee",
        object_type="concept",
        evidence_event_ids=["e-strengthen-edge"],
        confidence=0.8,
        observed_at=observed_at,
        source_type="llm",
    )
    assertion_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "alice",
            "entity_type": "person",
            "trait_family": "preference",
            "trait_name": "coffee",
            "trait_value": "likes coffee",
            "confidence_score": 0.8,
            "evidence_events": ["e-strengthen-assertion"],
            "volatility_index": 0.3,
            "source_domain": "chat",
            "inference_depth": "explicit",
            "validation_state": "active",
            "first_inferred_at": observed_at,
            "last_validated_at": observed_at,
        }
    )

    await store.forget_time_range(start=observed_at - 1, end=observed_at + 1)
    await store.forget_entity(entity_id="alice")

    edge = await store.get_relationship(triple_id=triple_id)
    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert edge is not None and edge["authority_ref"] == "forget:entity"
    assert assertion is not None and assertion["authority_ref"] == "forget:entity"


@pytest.mark.asyncio
async def test_forget_entity_blocks_passive_assertion_replay(
    store: L2CognitionStore,
):
    first_observed_at = time.time() - 10
    candidate = {
        "entity_id": "alice",
        "entity_type": "person",
        "trait_family": "preference",
        "trait_name": "coffee",
        "trait_value": "likes coffee",
        "confidence_score": 0.8,
        "evidence_events": ["evt-assertion-before-forget"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
        "first_inferred_at": first_observed_at,
        "last_validated_at": first_observed_at,
    }
    await store.upsert_assertion_candidate(candidate)
    await store.forget_entity(entity_id="alice")

    replayed = dict(candidate)
    replayed["evidence_events"] = ["evt-assertion-replayed-after-forget"]
    replayed["last_validated_at"] = time.time()
    replayed["scope"] = {
        "all_of": [
            {
                "dimension": "project",
                "context_id": f"ctx_project_{'a' * 64}",
            }
        ]
    }
    result_id = await store.upsert_assertion_candidate(replayed)

    assert result_id.startswith("blocked:")
    assert await store.list_current_assertions(entity_id="alice") == []
    assert await store.active_correction_evidence_event_ids(
        ["evt-assertion-replayed-after-forget"]
    ) == {"evt-assertion-replayed-after-forget"}


@pytest.mark.asyncio
async def test_forget_entity_blocks_relationship_replay_after_row_cleanup(
    store: L2CognitionStore,
):
    observed_at = time.time() - 10
    triple_id = await store.upsert_knowledge_edge(
        subject_id="alice",
        subject_type="person",
        predicate="LIKES",
        object_id="coffee",
        object_type="concept",
        evidence_event_ids=["evt-edge-before-forget"],
        confidence=0.8,
        observed_at=observed_at,
        source_type="llm",
    )
    await store.forget_entity(entity_id="alice")
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("DELETE FROM knowledge_graph WHERE triple_id = ?", (triple_id,))
        await db.commit()

    replayed_id = await store.upsert_knowledge_edge(
        subject_id="alice",
        subject_type="person",
        predicate="LIKES",
        object_id="coffee",
        object_type="concept",
        evidence_event_ids=["evt-edge-replayed-after-forget"],
        confidence=0.8,
        observed_at=time.time(),
        source_type="llm",
    )

    assert replayed_id == triple_id
    assert await store.get_relationship(triple_id=triple_id) is None
    assert await store.active_correction_evidence_event_ids(["evt-edge-replayed-after-forget"]) == {
        "evt-edge-replayed-after-forget"
    }


@pytest.mark.asyncio
async def test_forget_entity_rebuilds_an_orphaned_entity_snapshot(store: L2CognitionStore):
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:orphan",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-orphan-snapshot"],
        confidence=0.8,
        observed_at=time.time(),
        source_type="llm",
    )
    snapshot = await store.refresh_entity_snapshot(
        entity_id="user:orphan",
        entity_type="user",
    )
    assert snapshot is not None
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("DELETE FROM knowledge_graph WHERE triple_id = ?", (triple_id,))
        await db.execute("DELETE FROM knowledge_graph_versions WHERE triple_id = ?", (triple_id,))
        await db.execute(
            "DELETE FROM memory_claim_evidence_events WHERE event_id = ?",
            ("evt-orphan-snapshot",),
        )
        await db.commit()

    await store.forget_entity(entity_id="user:orphan")

    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM tom_snapshots WHERE entity_id = ?",
            ("user:orphan",),
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0


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
    aid = await store.upsert_assertion_candidate(
        {
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
        }
    )

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
@pytest.mark.parametrize("forget_older", [True, False])
async def test_forget_time_range_removes_only_matching_assertion_evidence(
    store: L2CognitionStore,
    forget_older: bool,
):
    now = time.time()
    older_at = now - 200
    newer_at = now - 50
    candidate = {
        "entity_id": "user",
        "entity_type": "user",
        "trait_family": "preference",
        "trait_name": "tea",
        "trait_value": "likes tea",
        "confidence_score": 0.8,
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
    }
    assertion_id = await store.upsert_assertion_candidate(
        {
            **candidate,
            "evidence_events": ["evt-older"],
            "first_inferred_at": older_at,
            "last_validated_at": older_at,
        }
    )
    await store.upsert_assertion_candidate(
        {
            **candidate,
            "evidence_events": ["evt-newer"],
            "first_inferred_at": newer_at,
            "last_validated_at": newer_at,
        }
    )
    forgotten_at = older_at if forget_older else newer_at

    await store.forget_time_range(start=forgotten_at - 1, end=forgotten_at + 1)

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None and assertion["status"] != "archived"
    assert assertion["evidence_events"] == ["evt-newer" if forget_older else "evt-older"]


@pytest.mark.asyncio
@pytest.mark.parametrize("forget_older", [True, False])
async def test_forget_time_range_removes_only_matching_relationship_evidence(
    store: L2CognitionStore,
    forget_older: bool,
):
    now = time.time()
    older_at = now - 200
    newer_at = now - 50
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user",
        subject_type="user",
        predicate="LIKES",
        object_id="tea",
        object_type="concept",
        evidence_event_ids=["evt-edge-older"],
        confidence=0.8,
        observed_at=older_at,
        source_type="llm",
    )
    await store.upsert_knowledge_edge(
        subject_id="user",
        subject_type="user",
        predicate="LIKES",
        object_id="tea",
        object_type="concept",
        evidence_event_ids=["evt-edge-newer"],
        confidence=0.8,
        observed_at=newer_at,
        source_type="llm",
    )
    forgotten_at = older_at if forget_older else newer_at

    await store.forget_time_range(start=forgotten_at - 1, end=forgotten_at + 1)

    relationship = await store.get_relationship(triple_id=triple_id)
    assert relationship is not None and relationship["status"] == "active"
    assert relationship["evidence_event_ids"] == [
        "evt-edge-newer" if forget_older else "evt-edge-older"
    ]
    assert relationship["observation_count"] == 1


@pytest.mark.asyncio
async def test_forget_time_range_uses_each_l1_evidence_timestamp(
    store: L2CognitionStore,
):
    now = time.time()
    older_at = now - 200
    newer_at = now - 50

    async def resolve_timestamps(event_ids: list[str]) -> dict[str, float]:
        timestamps = {
            "evt-batch-older": older_at,
            "evt-batch-newer": newer_at,
        }
        return {event_id: timestamps[event_id] for event_id in event_ids}

    precise_store = L2CognitionStore(
        db_path=store.db_path,
        evidence_timestamp_resolver=resolve_timestamps,
    )
    await precise_store.initialize()
    triple_id = await precise_store.upsert_knowledge_edge(
        subject_id="user",
        subject_type="user",
        predicate="LIKES",
        object_id="coffee",
        object_type="concept",
        evidence_event_ids=["evt-batch-older", "evt-batch-newer"],
        confidence=0.8,
        observed_at=newer_at,
        source_type="llm",
    )

    await precise_store.forget_time_range(start=older_at - 1, end=older_at + 1)

    relationship = await precise_store.get_relationship(triple_id=triple_id)
    assert relationship is not None and relationship["status"] == "active"
    assert relationship["evidence_event_ids"] == ["evt-batch-newer"]


@pytest.mark.asyncio
async def test_time_forget_filters_assertion_evidence_across_scopes(
    store: L2CognitionStore,
):
    older_at = time.time() - 200
    newer_at = time.time() - 20

    async def resolve_timestamps(event_ids: list[str]) -> dict[str, float]:
        return {event_id: older_at for event_id in event_ids if event_id == "evt-scope-old"}

    precise_store = L2CognitionStore(
        db_path=store.db_path,
        evidence_timestamp_resolver=resolve_timestamps,
    )
    await precise_store.initialize()
    base = {
        "entity_id": "user:scope",
        "entity_type": "user",
        "trait_family": "preference",
        "trait_name": "tea",
        "trait_value": "likes tea",
        "confidence_score": 0.8,
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
        "first_inferred_at": older_at,
        "last_validated_at": older_at,
    }
    await precise_store.upsert_assertion_candidate({**base, "evidence_events": ["evt-scope-old"]})
    await precise_store.forget_time_range(start=older_at - 1, end=older_at + 1)

    replayed_id = await precise_store.upsert_assertion_candidate(
        {
            **base,
            "evidence_events": ["evt-scope-old", "evt-scope-new"],
            "first_inferred_at": newer_at,
            "last_validated_at": newer_at,
            "scope": {
                "all_of": [{"dimension": "project", "context_id": f"ctx_project_{'a' * 64}"}]
            },
        }
    )

    replayed = await precise_store.get_tom_assertion(assertion_id=replayed_id)
    assert replayed is not None
    assert replayed["evidence_events"] == ["evt-scope-new"]
    assert replayed["first_inferred_at"] > older_at + 1
    assert replayed["last_validated_at"] > older_at + 1

    blocked_id = await precise_store.upsert_assertion_candidate(
        {
            **base,
            "evidence_events": ["evt-scope-old"],
            "first_inferred_at": newer_at,
            "last_validated_at": newer_at,
            "scope": {
                "all_of": [{"dimension": "project", "context_id": f"ctx_project_{'b' * 64}"}]
            },
        }
    )
    assert blocked_id.startswith("blocked:")


@pytest.mark.asyncio
async def test_time_forget_filters_relationship_evidence_across_scopes(
    store: L2CognitionStore,
):
    older_at = time.time() - 200
    newer_at = time.time() - 20

    async def resolve_timestamps(event_ids: list[str]) -> dict[str, float]:
        timestamps = {
            "evt-edge-scope-old": older_at,
            "evt-edge-scope-new": newer_at,
        }
        return {event_id: timestamps[event_id] for event_id in event_ids}

    precise_store = L2CognitionStore(
        db_path=store.db_path,
        evidence_timestamp_resolver=resolve_timestamps,
    )
    await precise_store.initialize()
    await precise_store.upsert_knowledge_edge(
        subject_id="user:scope",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:coffee",
        object_type="concept",
        evidence_event_ids=["evt-edge-scope-old"],
        confidence=0.8,
        observed_at=older_at,
        source_type="llm",
        evidence_text="old private detail",
    )
    await precise_store.forget_time_range(start=older_at - 1, end=older_at + 1)
    project_scope = {"all_of": [{"dimension": "project", "context_id": f"ctx_project_{'c' * 64}"}]}

    replayed_id = await precise_store.upsert_knowledge_edge(
        subject_id="user:scope",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:coffee",
        object_type="concept",
        evidence_event_ids=["evt-edge-scope-old", "evt-edge-scope-new"],
        confidence=0.8,
        observed_at=newer_at,
        source_type="llm",
        evidence_text="mixed private detail",
        scope=project_scope,
    )

    replayed = await precise_store.get_relationship(triple_id=replayed_id)
    assert replayed is not None
    assert replayed["evidence_event_ids"] == ["evt-edge-scope-new"]
    assert replayed["evidence_text"] == ""
    assert replayed["natural_summary"] == ""
    assert replayed["first_observed_at"] == newer_at
    assert replayed["last_observed_at"] == newer_at
    assert replayed["valid_from"] == newer_at


@pytest.mark.asyncio
async def test_time_forget_uses_approximate_evidence_interval_when_l1_is_missing(
    store: L2CognitionStore,
):
    interval_start = time.time() - 300
    interval_end = interval_start + 100

    async def resolve_nothing(_event_ids: list[str]) -> dict[str, float]:
        return {}

    approximate_store = L2CognitionStore(
        db_path=store.db_path,
        evidence_timestamp_resolver=resolve_nothing,
    )
    await approximate_store.initialize()
    assertion_id = await approximate_store.upsert_assertion_candidate(
        {
            "entity_id": "user:approximate-evidence",
            "entity_type": "user",
            "trait_family": "preference",
            "trait_name": "tea",
            "trait_value": "likes tea",
            "confidence_score": 0.8,
            "evidence_events": ["evt-approximate-interval"],
            "volatility_index": 0.3,
            "source_domain": "chat",
            "inference_depth": "explicit",
            "validation_state": "active",
            "first_inferred_at": interval_start,
            "last_validated_at": interval_end,
        }
    )

    counts = await approximate_store.forget_time_range(
        start=interval_start + 40,
        end=interval_start + 60,
    )

    assertion = await approximate_store.get_tom_assertion(assertion_id=assertion_id)
    assert counts["tom_trait_assertions"] == 1
    assert assertion is not None and assertion["status"] == "archived"
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute("""
            SELECT observed_from, observed_to, observed_at_is_approximate
            FROM memory_claim_evidence_events
            WHERE event_id = 'evt-approximate-interval'
            """) as cursor:
            ledger_row = await cursor.fetchone()
    assert tuple(ledger_row) == (interval_start, interval_end, 1)


@pytest.mark.asyncio
async def test_time_forget_refreshes_only_approximate_evidence_in_batches(
    store: L2CognitionStore,
    monkeypatch: pytest.MonkeyPatch,
):
    approximate_event_ids = [f"evt-approximate-{index}" for index in range(5)]
    unresolved_event_id = "evt-approximate-missing"
    exact_event_id = "evt-exact"
    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            """
            INSERT INTO memory_claim_evidence_events(
                target_kind, claim_fingerprint, event_id, observed_at,
                observed_from, observed_to, observed_at_is_approximate, created_at
            ) VALUES ('assertion', 'claim-refresh', ?, 10, 5, 15, 1, 1)
            """,
            [(event_id,) for event_id in (*approximate_event_ids, unresolved_event_id)],
        )
        await db.execute(
            """
            INSERT INTO memory_claim_evidence_events(
                target_kind, claim_fingerprint, event_id, observed_at,
                observed_from, observed_to, observed_at_is_approximate, created_at
            ) VALUES ('assertion', 'claim-refresh', ?, 99, 99, 99, 0, 1)
            """,
            (exact_event_id,),
        )
        await db.commit()

    resolver_calls: list[list[str]] = []
    canonical_times = {
        event_id: 100.0 + index for index, event_id in enumerate(approximate_event_ids)
    }

    async def resolve_timestamps(event_ids: list[str]) -> dict[str, float]:
        resolver_calls.append(list(event_ids))
        return {
            event_id: canonical_times[event_id]
            for event_id in event_ids
            if event_id in canonical_times
        }

    monkeypatch.setattr(forgetting_module, "_EVIDENCE_TIMESTAMP_REFRESH_BATCH_SIZE", 2)
    precise_store = L2CognitionStore(
        db_path=store.db_path,
        evidence_timestamp_resolver=resolve_timestamps,
    )
    await precise_store.initialize()
    await precise_store.forget_time_range(start=1_000, end=1_001)

    assert resolver_calls == [
        ["evt-approximate-0", "evt-approximate-1"],
        ["evt-approximate-2", "evt-approximate-3"],
        ["evt-approximate-4", unresolved_event_id],
    ]
    assert exact_event_id not in {event_id for batch in resolver_calls for event_id in batch}
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute("""
            SELECT event_id, observed_at, observed_from, observed_to,
                   observed_at_is_approximate
            FROM memory_claim_evidence_events
            WHERE claim_fingerprint = 'claim-refresh'
            ORDER BY event_id
            """) as cursor:
            rows = await cursor.fetchall()
    normalized = {str(row[0]): tuple(row[1:]) for row in rows}
    for event_id, canonical_time in canonical_times.items():
        assert normalized[event_id] == (canonical_time, canonical_time, canonical_time, 0)
    assert normalized[unresolved_event_id] == (10.0, 5.0, 15.0, 1)
    assert normalized[exact_event_id] == (99.0, 99.0, 99.0, 0)


@pytest.mark.asyncio
async def test_repeating_same_time_forget_does_not_mutate_clean_relationship(
    store: L2CognitionStore,
):
    older_at = time.time() - 200
    newer_at = time.time() - 20

    async def resolve_timestamps(event_ids: list[str]) -> dict[str, float]:
        timestamps = {
            "evt-idempotent-old": older_at,
            "evt-idempotent-new": newer_at,
        }
        return {event_id: timestamps[event_id] for event_id in event_ids}

    precise_store = L2CognitionStore(
        db_path=store.db_path,
        evidence_timestamp_resolver=resolve_timestamps,
    )
    await precise_store.initialize()
    triple_id = await precise_store.upsert_knowledge_edge(
        subject_id="user:idempotent-forget",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:tea",
        object_type="concept",
        evidence_event_ids=["evt-idempotent-old", "evt-idempotent-new"],
        confidence=0.8,
        observed_at=newer_at,
        source_type="llm",
        evidence_text="mixed private detail",
    )

    first_counts = await precise_store.forget_time_range(
        start=older_at - 1,
        end=older_at + 1,
    )
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            """
            SELECT updated_at, evidence_event_ids, evidence_text, natural_summary
            FROM knowledge_graph WHERE triple_id = ?
            """,
            (triple_id,),
        ) as cursor:
            after_first = tuple(await cursor.fetchone())
        async with db.execute("""
            SELECT revision FROM memory_subject_revisions
            WHERE subject_key = 'user:idempotent-forget'
            """) as cursor:
            revision_after_first = tuple(await cursor.fetchone())
        async with db.execute("""
            SELECT COUNT(*) FROM memory_forget_claim_rules
            WHERE target_kind = 'edge' AND forget_kind = 'time_range'
            """) as cursor:
            rule_count_after_first = int((await cursor.fetchone())[0])

    second_counts = await precise_store.forget_time_range(
        start=older_at - 1,
        end=older_at + 1,
    )
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            """
            SELECT updated_at, evidence_event_ids, evidence_text, natural_summary
            FROM knowledge_graph WHERE triple_id = ?
            """,
            (triple_id,),
        ) as cursor:
            after_second = tuple(await cursor.fetchone())
        async with db.execute("""
            SELECT revision FROM memory_subject_revisions
            WHERE subject_key = 'user:idempotent-forget'
            """) as cursor:
            revision_after_second = tuple(await cursor.fetchone())
        async with db.execute("""
            SELECT COUNT(*) FROM memory_forget_claim_rules
            WHERE target_kind = 'edge' AND forget_kind = 'time_range'
            """) as cursor:
            rule_count_after_second = int((await cursor.fetchone())[0])

    assert first_counts["knowledge_graph"] == 1
    assert json.loads(str(after_first[1])) == ["evt-idempotent-new"]
    assert after_first[2:] == ("", "")
    assert second_counts["knowledge_graph"] == 0
    assert after_second == after_first
    assert revision_after_second == revision_after_first
    assert rule_count_after_first == rule_count_after_second == 1


@pytest.mark.asyncio
async def test_time_forget_uses_ledger_evidence_missing_from_live_row(
    store: L2CognitionStore,
):
    older_at = time.time() - 200
    newer_at = time.time() - 20
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:ledger",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:tea",
        object_type="concept",
        evidence_event_ids=["evt-ledger-current"],
        confidence=0.8,
        observed_at=newer_at,
        source_type="llm",
        evidence_text="possibly derived from any supporting event",
    )
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            "SELECT claim_fingerprint FROM knowledge_graph WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            claim_fingerprint = str((await cursor.fetchone())[0])
        await db.execute(
            """
            INSERT INTO memory_claim_evidence_events(
                target_kind, claim_fingerprint, event_id, observed_at,
                observed_from, observed_to, observed_at_is_approximate, created_at
            ) VALUES ('edge', ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                claim_fingerprint,
                "evt-ledger-outside-row",
                older_at,
                older_at,
                older_at,
                older_at,
            ),
        )
        await db.execute(
            """
            UPDATE knowledge_graph
            SET valid_from = ?, first_observed_at = ?
            WHERE triple_id = ?
            """,
            (older_at - 100, older_at - 100, triple_id),
        )
        await db.commit()

    await store.forget_time_range(start=older_at - 1, end=older_at + 1)
    await store.upsert_knowledge_edge(
        subject_id="user:ledger",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:tea",
        object_type="concept",
        evidence_event_ids=["evt-ledger-outside-row"],
        confidence=0.8,
        observed_at=older_at,
        source_type="llm",
    )

    relationship = await store.get_relationship(triple_id=triple_id)
    assert relationship is not None and relationship["status"] == "active"
    assert relationship["evidence_event_ids"] == ["evt-ledger-current"]
    assert relationship["evidence_text"] == ""
    assert relationship["natural_summary"] == ""


@pytest.mark.asyncio
async def test_time_forget_uses_assertion_ledger_evidence_missing_from_live_row(
    store: L2CognitionStore,
):
    older_at = time.time() - 200
    newer_at = time.time() - 20
    candidate = {
        "entity_id": "user:ledger-assertion",
        "entity_type": "user",
        "trait_family": "preference",
        "trait_name": "tea",
        "trait_value": "likes tea",
        "confidence_score": 0.8,
        "evidence_events": ["evt-assertion-ledger-current"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "explicit",
        "validation_state": "active",
        "first_inferred_at": newer_at,
        "last_validated_at": newer_at,
    }
    assertion_id = await store.upsert_assertion_candidate(candidate)
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            "SELECT claim_fingerprint FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cursor:
            claim_fingerprint = str((await cursor.fetchone())[0])
        await db.execute(
            """
            INSERT INTO memory_claim_evidence_events(
                target_kind, claim_fingerprint, event_id, observed_at,
                observed_from, observed_to, observed_at_is_approximate, created_at
            ) VALUES ('assertion', ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                claim_fingerprint,
                "evt-assertion-ledger-outside-row",
                older_at,
                older_at,
                older_at,
                older_at,
            ),
        )
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET valid_from = ?, first_inferred_at = ?
            WHERE assertion_id = ?
            """,
            (older_at - 100, older_at - 100, assertion_id),
        )
        await db.commit()

    await store.forget_time_range(start=older_at - 1, end=older_at + 1)
    replayed = dict(candidate)
    replayed["evidence_events"] = ["evt-assertion-ledger-outside-row"]
    replayed["first_inferred_at"] = older_at
    replayed["last_validated_at"] = older_at
    result_id = await store.upsert_assertion_candidate(replayed)

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None and assertion["status"] != "archived"
    assert assertion["evidence_events"] == ["evt-assertion-ledger-current"]
    assert result_id.startswith("blocked:")


@pytest.mark.asyncio
async def test_time_forget_clears_unattributed_relationship_text_from_history(
    store: L2CognitionStore,
):
    older_at = time.time() - 200
    newer_at = time.time() - 20
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:history-redaction",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:tea",
        object_type="concept",
        evidence_event_ids=["evt-history-old"],
        confidence=0.8,
        observed_at=older_at,
        source_type="llm",
        evidence_text="old private detail",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:history-redaction",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:tea",
        object_type="concept",
        evidence_event_ids=["evt-history-new"],
        confidence=0.8,
        observed_at=newer_at,
        source_type="llm",
        evidence_text="old private detail plus current support",
    )
    async with sqlite_connection_async(store.db_path) as db:
        await append_knowledge_graph_version(
            db,
            triple_id=triple_id,
            created_at=newer_at + 1,
        )
        await db.commit()

    await store.forget_time_range(start=older_at - 1, end=older_at + 1)

    history = await store.list_current_relationships(
        subject_id="user:history-redaction",
        include_history=True,
        effective_range=(older_at - 1, newer_at + 10),
        limit=20,
    )
    retained_rows = [row for row in history if "evt-history-new" in row["evidence_event_ids"]]
    assert retained_rows
    assert all(row["evidence_text"] == "" for row in retained_rows)
    assert all(row["natural_summary"] == "" for row in retained_rows)


@pytest.mark.asyncio
async def test_forget_time_range_rejects_invalid_range(store: L2CognitionStore):
    with pytest.raises(ValueError, match="end must be greater"):
        await store.forget_time_range(start=100.0, end=50.0)
    with pytest.raises(ValueError, match="end must be greater"):
        await store.forget_time_range(start=float("nan"), end=100.0)
    with pytest.raises(ValueError, match="end must be greater"):
        await store.forget_time_range(start=100.0, end=float("inf"))


@pytest.mark.asyncio
async def test_forget_time_range_rebuilds_snapshot_from_remaining_memory(
    store: L2CognitionStore,
):
    forgotten_at = time.time() - 100
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-snapshot-forgotten"],
        confidence=0.8,
        observed_at=forgotten_at,
        source_type="llm",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:coffee",
        object_type="concept",
        evidence_event_ids=["evt-snapshot-retained"],
        confidence=0.8,
        observed_at=time.time(),
        source_type="llm",
    )
    before = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert before is not None

    await store.forget_time_range(start=forgotten_at - 1, end=forgotten_at + 1)

    after = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
    assert after is not None
    serialized = json.dumps(after, ensure_ascii=False)
    assert "place:hangzhou" not in serialized
    assert "concept:coffee" in serialized
    assert int(after["source_revision"]) > int(before["source_revision"])


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


@pytest.mark.asyncio
async def test_forget_episode_invalidates_all_dependent_memory(store: L2CognitionStore):
    from magi.memory.l3.models import L3Candidate
    from magi.memory.l3.summary_store import L3SummaryStore

    now = time.time()
    await store.create_episode(
        episode_id="ep-private",
        status="active",
        time_start=now - 100,
        time_end=now,
    )
    await store.add_episode_events(episode_id="ep-private", event_ids=["evt-private"])
    seed_id = await store.create_experience_seed(
        seed_id="seed-private",
        seed_type="manual",
        status="accepted",
        title="Private seed",
        created_by="user",
        source_ref_type="episode",
        source_ref_id="ep-private",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[{"ref_type": "episode", "ref_id": "ep-private", "role": "trigger"}],
    )
    await store.create_experience(
        experience_id="exp-private",
        status="active",
        title="Private experience",
        time_start=now - 100,
        time_end=now,
        source_seed_id=seed_id,
    )
    await store.add_experience_members(
        experience_id="exp-private",
        members=[{"member_type": "episode", "member_id": "ep-private"}],
    )
    await store.create_experience_draft(
        draft_id="draft-private",
        query_text="Private trip",
        title="Private trip",
        one_sentence_review="Private review",
        time_start=now - 100,
        time_end=now,
        chapters=[{"episode_ids": ["ep-private"], "event_ids": []}],
        possible_evidence=[],
    )
    l3 = L3SummaryStore(db_path=store.db_path, vector_enabled=False)
    await l3.initialize()
    summary = await l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="episodic",
            content="Private generated summary",
            source_event_ids=["evt-private"],
            insight_key="episode:ep-private:review",
            insight_metadata={"source_episode_id": "ep-private"},
        )
    )

    result = await store.forget_episode(episode_id="ep-private")

    assert result is not None
    assert result["experiences"] == 1
    assert result["experience_seeds"] == 1
    assert result["experience_drafts"] == 1
    assert result["summaries"] == 1
    experience = await store.get_experience(experience_id="exp-private")
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert experience is not None and experience["status"] == "invalidated"
    assert seed is not None and seed["status"] == "stale"
    assert seed["promoted_experience_id"] is None
    assert await store.get_experience_draft(draft_id="draft-private") is None
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            "SELECT derivation_state FROM summaries WHERE summary_id = ?",
            (summary["summary_id"],),
        ) as cursor:
            assert tuple(await cursor.fetchone()) == ("retired",)


# ── forgotten records must not leak back into retrieval (#134) ────


async def _seed_assertion(store: L2CognitionStore, *, entity_id: str) -> str:
    now = time.time()
    return await store.upsert_assertion_candidate(
        {
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
        }
    )


_ACTIVE_STATES = ["tentative", "corroborated", "stable"]


@pytest.mark.asyncio
async def test_forgotten_assertion_excluded_from_list(store: L2CognitionStore):
    await _seed_assertion(store, entity_id="alice")

    before = await store.list_tom_assertions(entity_id="alice", validation_states=_ACTIVE_STATES)
    assert len(before) == 1

    await store.forget_entity(entity_id="alice")

    after = await store.list_tom_assertions(entity_id="alice", validation_states=_ACTIVE_STATES)
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
async def test_list_assertions_for_episode_intersects_evidence(store: L2CognitionStore):
    now = time.time()
    await store.create_episode(episode_id="ep", time_start=now - 10, time_end=now)
    await store.add_episode_events(episode_id="ep", event_ids=["e1", "e2"])
    assertion_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "user",
            "entity_type": "user",
            "trait_family": "preference",
            "trait_name": "balance",
            "trait_value": "values work-life balance",
            "confidence_score": 0.7,
            "evidence_events": ["e2"],
            "volatility_index": 0.3,
            "source_domain": "chat",
            "inference_depth": "explicit",
            "validation_state": "tentative",
            "first_inferred_at": now,
            "last_validated_at": now,
            "natural_summary": "User values balance.",
        }
    )

    rows = await store.list_assertions_for_episode(episode_id="ep")

    assert any(row["assertion_id"] == assertion_id for row in rows)
    assert rows[0]["natural_summary"] == "User values balance."

    await store.apply_user_feedback(assertion_id=assertion_id, feedback="rejected")
    rows_after_reject = await store.list_assertions_for_episode(episode_id="ep")
    assert rows_after_reject == []


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
