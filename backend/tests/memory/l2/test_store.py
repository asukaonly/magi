from __future__ import annotations

import time
import aiosqlite

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth, normalize_runtime_event


async def _build_user_message(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "content": text},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


async def _build_group_timeline_message(text: str, *, correlation_id: str, timestamp: float):
    return MemoryEvent(
        event_id=correlation_id,
        correlation_id=correlation_id,
        timestamp=timestamp,
        created_at=timestamp,
        event_type="SENSOR_EVENT",
        source="group_chat",
        source_item_id=f"group_chat:{correlation_id}",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id="u1",
        task_id=None,
        content=text,
        author_type="external",
        content_type="observation",
        importance_score=0.75,
        level=EventLevel.INFO.value,
        metadata_json={
            "timeline": {
                "event_id": correlation_id,
                "source_type": "group_chat",
                "source_item_id": f"group_chat:{correlation_id}",
                "occurred_at": timestamp,
                "captured_at": timestamp,
                "title": "Group chat",
                "summary": text,
                "retention_mode": "analyze_only",
                "content_blocks": [{"kind": "text", "value": text, "mime_type": None}],
                "entities": [],
                "tags": [],
                "privacy_labels": [],
                "processing_status": {"stored": True, "analyzed": False},
                "provenance": {},
            }
        },
    )


async def _build_contradiction(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "content": text},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


async def _apply_rule_candidates(store, event):  # type: ignore[no-untyped-def]
    await store.initialize()
    relation_count = 0
    assertion_count = 0
    for candidate in store.build_rule_graph_candidates(event):
        await store.upsert_knowledge_edge(**candidate.to_dict())
        relation_count += 1
    for candidate in store.build_rule_assertion_candidates(event):
        await store.upsert_assertion_candidate(candidate.to_dict())
        assertion_count += 1
    return {"relation_count": relation_count, "assertion_count": assertion_count}


@pytest.mark.asyncio
async def test_tom_assertion_starts_tentative_with_low_confidence(tmp_path):
    from magi.memory.l2.models import L2KnowledgeEdgeWrite, L2TomAssertionWrite
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    event = await _build_user_message(
        "I have been really stressed about work lately.",
        correlation_id="evt-1",
        timestamp=1710000000.0,
    )
    graph_candidates = store.build_rule_graph_candidates(event)
    assertion_candidates = store.build_rule_assertion_candidates(event)
    result = await _apply_rule_candidates(store, event)

    assertions = await store.list_tom_assertions(entity_id="user:u1")

    assert graph_candidates == []
    assert len(assertion_candidates) == 1
    assert isinstance(assertion_candidates[0], L2TomAssertionWrite)

    preference_event = await _build_user_message(
        "I like rainy days.",
        correlation_id="evt-like-1",
        timestamp=1710000100.0,
    )
    graph_candidates = store.build_rule_graph_candidates(preference_event)

    assert len(graph_candidates) == 1
    assert isinstance(graph_candidates[0], L2KnowledgeEdgeWrite)
    assert result["assertion_count"] == 1
    assert assertions[0]["trait_name"] == "stress_level"
    assert assertions[0]["validation_state"] == "tentative"
    assert assertions[0]["confidence_score"] <= 0.3


@pytest.mark.asyncio
async def test_repeated_evidence_promotes_snapshot_to_stable(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    events = [
        await _build_user_message(
            "I feel stressed about work.",
            correlation_id="evt-1",
            timestamp=1710000000.0,
        ),
        await _build_user_message(
            "Work pressure is making me anxious again.",
            correlation_id="evt-2",
            timestamp=1710090000.0,
        ),
        await _build_user_message(
            "The job competition still feels stressful.",
            correlation_id="evt-3",
            timestamp=1710185000.0,
        ),
    ]

    for event in events:
        await _apply_rule_candidates(store, event)

    assertions = await store.list_tom_assertions(entity_id="user:u1")
    snapshot = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")

    assert assertions[0]["validation_state"] == "stable"
    assert assertions[0]["confidence_score"] >= 0.8
    assert snapshot is not None
    assert snapshot["core_traits"]["stress_level"] == "high"


@pytest.mark.asyncio
async def test_reconcile_entity_returns_typed_outcomes(tmp_path):
    from magi.memory.l2.models import ReconciledTraitOutcome
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    event = await _build_user_message(
        "I feel stressed about work.",
        correlation_id="evt-1",
        timestamp=1710000000.0,
    )
    await _apply_rule_candidates(store, event)

    outcomes = await store.reconcile_entity(
        entity_id="user:u1",
        entity_type="user",
        evidence_timestamps={"evt-1": 1710000000.0},
    )

    assert len(outcomes) == 1
    assert isinstance(outcomes[0], ReconciledTraitOutcome)
    assert outcomes[0].trait_name == "stress_level"


@pytest.mark.asyncio
async def test_contradiction_downgrades_existing_assertion(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for correlation_id, timestamp, text in (
        ("evt-1", 1710000000.0, "I feel stressed about work."),
        ("evt-2", 1710090000.0, "The workload still makes me anxious."),
        ("evt-3", 1710185000.0, "Work pressure is stressing me out."),
    ):
        await _apply_rule_candidates(
            store,
            await _build_user_message(text, correlation_id=correlation_id, timestamp=timestamp)
        )

    await _apply_rule_candidates(
        store,
        await _build_contradiction(
            "I actually feel calm and relaxed about work now.",
            correlation_id="evt-4",
            timestamp=1710275000.0,
        )
    )

    assertions = await store.list_tom_assertions(entity_id="user:u1")

    assert assertions[0]["validation_state"] == "contradicted"
    assert assertions[0]["confidence_score"] < 0.8


@pytest.mark.asyncio
async def test_group_content_avoids_deep_psychology(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await _apply_rule_candidates(
        store,
        await _build_group_timeline_message(
            "The group felt tense and Alice openly praised Bob.",
            correlation_id="evt-1",
            timestamp=1710000000.0,
        )
    )

    assertions = await store.list_tom_assertions(entity_id="user:u1")

    assert assertions == []


@pytest.mark.asyncio
async def test_upsert_knowledge_edge_accumulates_confidence_on_repeat(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.3,
        observed_at=1710000000.0,
        source_type="chat",
    )
    edges = await store.get_relationships(subject_id="user:u1", limit=10)
    assert abs(edges[0]["confidence"] - 0.3) < 1e-6

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-2"],
        confidence=0.3,
        observed_at=1710010000.0,
        source_type="chat",
    )
    edges = await store.get_relationships(subject_id="user:u1", limit=10)
    # noisy-OR: 1 - (1-0.3)*(1-0.3) = 0.51
    assert edges[0]["confidence"] > 0.3
    assert abs(edges[0]["confidence"] - 0.51) < 1e-6

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-3"],
        confidence=0.3,
        observed_at=1710020000.0,
        source_type="chat",
    )
    edges = await store.get_relationships(subject_id="user:u1", limit=10)
    # noisy-OR: 1 - (1-0.51)*(1-0.3) = 0.657
    assert edges[0]["confidence"] > 0.51
    assert edges[0]["confidence"] <= 0.99


@pytest.mark.asyncio
async def test_preference_reversal_deprecates_opposite_graph_edge(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-like-1"],
        confidence=0.82,
        observed_at=1710000000.0,
        source_type="chat",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-dislike-1"],
        confidence=0.86,
        observed_at=1710090000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:u1", limit=10)

    assert len(active_edges) == 1
    assert active_edges[0]["predicate"] == "DISLIKES"

    deprecated_like_edges = await store.get_relationships(subject_id="user:u1", limit=10, status="deprecated")
    assert len(deprecated_like_edges) == 1
    assert deprecated_like_edges[0]["predicate"] == "LIKES"
    assert deprecated_like_edges[0]["deprecated_by"] == active_edges[0]["triple_id"]


@pytest.mark.asyncio
async def test_upsert_knowledge_edge_normalizes_alias_object_type(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="dish:west-lake-vinegar-fish",
        object_type="dish",
        evidence_event_ids=["evt-food-1"],
        confidence=0.85,
        observed_at=1710000000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:u1", limit=10)

    assert active_edges[0]["object_type"] == "food"
    assert active_edges[0]["object_id"] == "food:west-lake-vinegar-fish"


@pytest.mark.asyncio
async def test_upsert_assertion_normalizes_unknown_entity_type_to_other(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_assertion_candidate(
        {
            "entity_id": "mystery:thing",
            "entity_type": "unknown_type",
            "trait_name": "mood",
            "trait_value": "curious",
            "confidence_score": 0.2,
            "evidence_events": ["evt-assert-1"],
            "volatility_index": 0.5,
            "source_domain": "user_authored",
            "inference_depth": "defensive_psychology",
            "validation_state": "tentative",
            "first_inferred_at": 1710000000.0,
            "last_validated_at": 1710000000.0,
        }
    )

    assertions = await store.list_tom_assertions(entity_id="mystery:thing", limit=10)

    assert assertions[0]["entity_type"] == "other"


@pytest.mark.asyncio
async def test_refresh_snapshot_ignores_expired_temporary_assertions(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "mood",
            "trait_name": "annoyance",
            "trait_value": "high",
            "confidence_score": 0.3,
            "evidence_events": ["evt-expired-1"],
            "volatility_index": 0.9,
            "source_domain": "user_authored",
            "inference_depth": "defensive_psychology",
            "validation_state": "corroborated",
            "first_inferred_at": now - 7200,
            "last_validated_at": now - 3600,
            "target_entity_id": "weather_state:hangzhou-rainy-11c",
            "target_entity_type": "weather_state",
            "target_scope": "entity_bound",
            "temporal_scope": "momentary",
            "decay_policy": "fast_decay",
            "decay_anchor_at": now - 7200,
            "context_ref_id": "weather_state:hangzhou-rainy-11c",
            "expires_at": now - 60,
        }
    )
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "stress",
            "trait_name": "stress_level",
            "trait_value": "high",
            "confidence_score": 0.82,
            "evidence_events": ["evt-stress-1", "evt-stress-2", "evt-stress-3"],
            "volatility_index": 0.6,
            "source_domain": "user_authored",
            "inference_depth": "defensive_psychology",
            "validation_state": "stable",
            "first_inferred_at": now - 172800,
            "last_validated_at": now,
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "daily",
            "decay_policy": "time_window",
            "decay_anchor_at": now,
            "context_ref_id": "",
            "expires_at": now + 86400,
        }
    )

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assertions = await store.list_tom_assertions(entity_id="user:u1", entity_type="user")

    assert snapshot is not None
    assert snapshot["current_mood"] is None
    assert snapshot["core_traits"]["stress_level"] == "high"
    assert snapshot["current_context"]["active_assertion_count"] == 1
    assert snapshot["current_context"]["expired_assertion_count"] == 1
    assert any(item["trait_name"] == "annoyance" and item["expires_at"] is not None for item in assertions)


@pytest.mark.asyncio
async def test_refresh_entity_snapshot_excludes_deprecated_preference_and_keeps_history(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-like-1"],
        confidence=0.82,
        observed_at=1710000000.0,
        source_type="chat",
    )
    first_snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-dislike-1"],
        confidence=0.9,
        observed_at=1710090000.0,
        source_type="chat",
    )
    second_snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")

    assert first_snapshot is not None
    assert first_snapshot["preferences"]["food:sushi"] == "like"
    assert second_snapshot is not None
    assert second_snapshot["preferences"]["food:sushi"] == "dislike"
    assert second_snapshot["preferences_history"][0]["field"] == "food:sushi"
    assert second_snapshot["preferences_history"][0]["from"] == "like"
    assert second_snapshot["preferences_history"][0]["to"] == "dislike"


@pytest.mark.asyncio
async def test_refresh_entity_snapshot_tracks_core_trait_evolution_history(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "stress",
            "trait_name": "stress_level",
            "trait_value": "high",
            "confidence_score": 0.84,
            "evidence_events": ["evt-stress-high-1", "evt-stress-high-2", "evt-stress-high-3"],
            "volatility_index": 0.5,
            "source_domain": "user_authored",
            "inference_depth": "defensive_psychology",
            "validation_state": "stable",
            "first_inferred_at": now - 172800,
            "last_validated_at": now - 7200,
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "daily",
            "decay_policy": "time_window",
            "decay_anchor_at": now - 7200,
            "context_ref_id": "",
            "expires_at": now + 86400,
        }
    )
    first_snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET trait_value = ?, confidence_score = ?, validation_state = ?, last_validated_at = ?, updated_at = ?
            WHERE entity_id = ? AND entity_type = ? AND trait_name = ?
            """,
            (
                "low",
                0.86,
                "stable",
                now,
                now,
                "user:u1",
                "user",
                "stress_level",
            ),
        )
        await db.commit()
    second_snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")

    assert first_snapshot is not None
    assert first_snapshot["core_traits"]["stress_level"] == "high"
    assert second_snapshot is not None
    assert second_snapshot["core_traits"]["stress_level"] == "low"
    assert second_snapshot["core_traits_history"][0]["field"] == "stress_level"
    assert second_snapshot["core_traits_history"][0]["from"] == "high"
    assert second_snapshot["core_traits_history"][0]["to"] == "low"


@pytest.mark.asyncio
async def test_custom_opposite_rule_can_mark_existing_edge_conflicted(tmp_path):
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.graph_conflicts import GraphConflictRule

    store = L2CognitionStore(
        db_path=str(tmp_path / "l2.db"),
        graph_conflict_rules={
            "ENDORSES": GraphConflictRule(
                predicate="ENDORSES",
                opposite_predicates=("REJECTS",),
                opposite_resolution="mark_conflicted",
            ),
            "REJECTS": GraphConflictRule(
                predicate="REJECTS",
                opposite_predicates=("ENDORSES",),
                opposite_resolution="mark_conflicted",
            ),
        },
    )
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="ENDORSES",
        object_id="topic:remote-work",
        object_type="topic",
        evidence_event_ids=["evt-endorse-1"],
        confidence=0.74,
        observed_at=1710000000.0,
        source_type="chat",
    )
    reject_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="REJECTS",
        object_id="topic:remote-work",
        object_type="topic",
        evidence_event_ids=["evt-reject-1"],
        confidence=0.78,
        observed_at=1710090000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:u1", limit=10)
    conflicted_edges = await store.get_relationships(subject_id="user:u1", limit=10, status="conflicted")

    assert len(active_edges) == 1
    assert active_edges[0]["triple_id"] == reject_id
    assert len(conflicted_edges) == 1
    assert conflicted_edges[0]["predicate"] == "ENDORSES"
    assert conflicted_edges[0]["deprecated_by"] == reject_id


@pytest.mark.asyncio
async def test_exclusive_group_rule_deprecates_cross_predicate_edges(tmp_path):
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.graph_conflicts import GraphConflictRule

    store = L2CognitionStore(
        db_path=str(tmp_path / "l2.db"),
        graph_conflict_rules={
            "PRIMARY_BASED_IN": GraphConflictRule(
                predicate="PRIMARY_BASED_IN",
                exclusive_group="current_residence",
            ),
            "CURRENT_LIVES_IN": GraphConflictRule(
                predicate="CURRENT_LIVES_IN",
                exclusive_group="current_residence",
            ),
        },
    )
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="PRIMARY_BASED_IN",
        object_id="place:shanghai",
        object_type="place",
        evidence_event_ids=["evt-home-1"],
        confidence=0.72,
        observed_at=1710000000.0,
        source_type="timeline",
    )
    live_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:tokyo",
        object_type="place",
        evidence_event_ids=["evt-home-2"],
        confidence=0.91,
        observed_at=1710090000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:u1", limit=10)
    deprecated_edges = await store.get_relationships(subject_id="user:u1", limit=10, status="deprecated")

    assert len(active_edges) == 1
    assert active_edges[0]["triple_id"] == live_id
    assert len(deprecated_edges) == 1
    assert deprecated_edges[0]["predicate"] == "PRIMARY_BASED_IN"
    assert deprecated_edges[0]["deprecated_by"] == live_id


@pytest.mark.asyncio
async def test_default_graph_conflict_rules_are_seeded_and_listed(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    rules = await store.list_graph_conflict_rules()

    likes_rule = next(rule for rule in rules if rule["predicate"] == "LIKES")
    residence_rule = next(rule for rule in rules if rule["predicate"] == "CURRENT_LIVES_IN")

    assert "DISLIKES" in likes_rule["opposite_predicates"]
    assert likes_rule["opposite_resolution"] == "mark_deprecated"
    assert residence_rule["exclusive_group"] == "current_residence"


@pytest.mark.asyncio
async def test_upserted_graph_conflict_rule_persists_across_store_instances(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    await store.upsert_graph_conflict_rule(
        {
            "predicate": "ALLY_OF",
            "opposite_predicates": ["OPPOSES"],
            "opposite_resolution": "mark_conflicted",
            "exclusive_group": "active_alignment",
            "exclusive_resolution": "mark_conflicted",
        }
    )

    reloaded_store = L2CognitionStore(db_path=db_path)
    await reloaded_store.initialize()
    rules = await reloaded_store.list_graph_conflict_rules()
    ally_rule = next(rule for rule in rules if rule["predicate"] == "ALLY_OF")

    assert ally_rule["opposite_predicates"] == ["OPPOSES"]
    assert ally_rule["opposite_resolution"] == "mark_conflicted"
    assert ally_rule["exclusive_group"] == "active_alignment"


@pytest.mark.asyncio
async def test_upserted_graph_conflict_rule_changes_runtime_conflict_behavior(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await store.upsert_graph_conflict_rule(
        {
            "predicate": "ENDORSES",
            "opposite_predicates": ["REJECTS"],
            "opposite_resolution": "mark_conflicted",
        }
    )
    await store.upsert_graph_conflict_rule(
        {
            "predicate": "REJECTS",
            "opposite_predicates": ["ENDORSES"],
            "opposite_resolution": "mark_conflicted",
        }
    )

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="ENDORSES",
        object_id="topic:hybrid-work",
        object_type="topic",
        evidence_event_ids=["evt-1"],
        confidence=0.7,
        observed_at=1710000000.0,
        source_type="chat",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="REJECTS",
        object_id="topic:hybrid-work",
        object_type="topic",
        evidence_event_ids=["evt-2"],
        confidence=0.72,
        observed_at=1710090000.0,
        source_type="chat",
    )

    conflicted_edges = await store.get_relationships(subject_id="user:u1", limit=10, status="conflicted")

    assert len(conflicted_edges) == 1
    assert conflicted_edges[0]["predicate"] == "ENDORSES"


@pytest.mark.asyncio
async def test_upsert_graph_conflict_rule_normalizes_predicates_and_deduplicates_opposites(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    rule = await store.upsert_graph_conflict_rule(
        {
            "predicate": " endorses ",
            "opposite_predicates": ["rejects", " REJECTS ", "avoids"],
            "opposite_resolution": "mark_conflicted",
        }
    )

    assert rule["predicate"] == "ENDORSES"
    assert rule["opposite_predicates"] == ["REJECTS", "AVOIDS"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "predicate": "ENDORSES",
                "opposite_predicates": ["ENDORSES"],
                "opposite_resolution": "mark_conflicted",
            },
            "cannot reference itself",
        ),
        (
            {
                "predicate": "STANCE",
            },
            "must define at least one conflict mechanism",
        ),
        (
            {
                "predicate": "STANCE",
                "exclusive_resolution": "mark_conflicted",
            },
            "exclusive_group",
        ),
    ],
)
async def test_upsert_graph_conflict_rule_rejects_invalid_combinations(tmp_path, payload, message):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    with pytest.raises(ValueError, match=message):
        await store.upsert_graph_conflict_rule(payload)


@pytest.mark.asyncio
async def test_apply_user_feedback_confirmed_promotes_confidence(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    event = await _build_user_message("I have been really stressed.", correlation_id="evt-fb-1", timestamp=1710000000.0)
    await _apply_rule_candidates(store, event)
    assertions = await store.list_tom_assertions(entity_id="user:u1")
    assert len(assertions) == 1
    assert assertions[0]["validation_state"] == "tentative"
    original_confidence = assertions[0]["confidence_score"]

    result = await store.apply_user_feedback(assertion_id=assertions[0]["assertion_id"], feedback="confirmed")

    assert result is not None
    assert result["user_feedback"] == "confirmed"
    assert result["user_feedback_at"] is not None
    assert result["validation_state"] == "stable"
    assert result["confidence_score"] >= original_confidence + 0.20 - 0.01


@pytest.mark.asyncio
async def test_apply_user_feedback_rejected_drops_confidence(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    event = await _build_user_message("I have been really stressed.", correlation_id="evt-fb-2", timestamp=1710000000.0)
    await _apply_rule_candidates(store, event)
    assertions = await store.list_tom_assertions(entity_id="user:u1")

    result = await store.apply_user_feedback(assertion_id=assertions[0]["assertion_id"], feedback="rejected")

    assert result is not None
    assert result["user_feedback"] == "rejected"
    assert result["validation_state"] == "user_rejected"
    assert result["confidence_score"] == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_apply_user_feedback_not_found_returns_none(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    result = await store.apply_user_feedback(assertion_id="nonexistent", feedback="confirmed")
    assert result is None


@pytest.mark.asyncio
async def test_apply_user_feedback_invalid_value_raises(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    with pytest.raises(ValueError, match="Invalid feedback"):
        await store.apply_user_feedback(assertion_id="any", feedback="maybe")


@pytest.mark.asyncio
async def test_reconcile_respects_user_confirmed_feedback(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    event = await _build_user_message("I have been really stressed.", correlation_id="evt-rc-1", timestamp=1710000000.0)
    await _apply_rule_candidates(store, event)
    assertions = await store.list_tom_assertions(entity_id="user:u1")

    await store.apply_user_feedback(assertion_id=assertions[0]["assertion_id"], feedback="confirmed")

    outcomes = await store.reconcile_entity(entity_id="user:u1")
    assert len(outcomes) == 1
    assert outcomes[0].status == "stable"
    assert outcomes[0].confidence >= 0.85


@pytest.mark.asyncio
async def test_reconcile_respects_user_rejected_feedback(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    event = await _build_user_message("I have been really stressed.", correlation_id="evt-rc-2", timestamp=1710000000.0)
    await _apply_rule_candidates(store, event)
    assertions = await store.list_tom_assertions(entity_id="user:u1")

    await store.apply_user_feedback(assertion_id=assertions[0]["assertion_id"], feedback="rejected")

    outcomes = await store.reconcile_entity(entity_id="user:u1")
    assert len(outcomes) == 1
    assert outcomes[0].status == "user_rejected"
    assert outcomes[0].confidence == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_snapshot_excludes_user_rejected_assertions(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    now = time.time()
    # Create two assertions — one will be rejected
    for i, text in enumerate(["I have been really stressed.", "I have been really stressed."], start=1):
        event = await _build_user_message(text, correlation_id=f"evt-snap-{i}", timestamp=now + i * 100)
        await _apply_rule_candidates(store, event)

    assertions = await store.list_tom_assertions(entity_id="user:u1")
    assert len(assertions) >= 1

    # Reject the assertion
    await store.apply_user_feedback(assertion_id=assertions[0]["assertion_id"], feedback="rejected")

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1")
    # The rejected assertion should not appear in the active snapshot traits
    if snapshot and snapshot.get("core_traits"):
        assert "stress_level" not in snapshot["core_traits"]
