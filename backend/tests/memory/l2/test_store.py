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
async def test_upsert_knowledge_edge_keeps_first_and_last_observed_bounds_for_out_of_order_events(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="VISITED",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-late"],
        confidence=0.4,
        observed_at=1710010000.0,
        source_type="photo_library",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="VISITED",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-early"],
        confidence=0.4,
        observed_at=1710000000.0,
        source_type="photo_library",
    )

    edge = (await store.get_relationships(subject_id="user:u1", limit=10))[0]
    assert edge["first_observed_at"] == 1710000000.0
    assert edge["last_observed_at"] == 1710010000.0


@pytest.mark.asyncio
async def test_initialize_adds_fact_kind_column_for_existing_db(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = tmp_path / "l2.db"
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE knowledge_graph (
                triple_id TEXT PRIMARY KEY,
                subject_id TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_id TEXT NOT NULL,
                object_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                evidence_event_ids TEXT NOT NULL,
                observation_count INTEGER NOT NULL DEFAULT 1,
                first_observed_at REAL NOT NULL,
                last_observed_at REAL NOT NULL,
                last_confirmed_at REAL,
                source_type TEXT,
                extraction_method TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                deprecated_by TEXT,
                deprecated_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(subject_id, predicate, object_id)
            );
            """
        )
        await db.commit()

    store = L2CognitionStore(db_path=str(db_path))
    await store.initialize()

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("PRAGMA table_info(knowledge_graph)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}

    assert "fact_kind" in columns


@pytest.mark.asyncio
async def test_upsert_knowledge_edge_persists_fact_kind(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="USES",
        object_id="software:github",
        object_type="software",
        evidence_event_ids=["evt-1"],
        confidence=0.7,
        observed_at=1710000000.0,
        source_type="sensor",
        fact_kind="interaction_evidence",
    )
    edge = await store.get_relationship(triple_id=triple_id)

    assert edge is not None
    assert edge["fact_kind"] == "interaction_evidence"

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="USES",
        object_id="software:github",
        object_type="software",
        evidence_event_ids=["evt-2"],
        confidence=0.4,
        observed_at=1710010000.0,
        source_type="sensor",
    )
    edge = await store.get_relationship(triple_id=triple_id)

    assert edge is not None
    assert edge["fact_kind"] == "interaction_evidence"


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
async def test_upsert_entity_facet_persists_and_filters_by_value(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_entity_facet(
        entity_id="place:manner-xihu",
        entity_type="place",
        facet_name="category",
        facet_value="coffee_shop",
        evidence_event_ids=["evt-1"],
        confidence=0.93,
        observed_at=1710000000.0,
        source_type="chrome_history",
        extraction_method="structured_hint",
    )
    await store.upsert_entity_facet(
        entity_id="place:grandma-home",
        entity_type="place",
        facet_name="category",
        facet_value="restaurant",
        evidence_event_ids=["evt-2"],
        confidence=0.9,
        observed_at=1710000001.0,
        source_type="chrome_history",
        extraction_method="structured_hint",
    )

    facets = await store.list_entity_facets(entity_id="place:manner-xihu", facet_name="category")
    matches = await store.filter_entity_ids_by_facet(
        entity_ids=["place:manner-xihu", "place:grandma-home"],
        facet_name="category",
        facet_values=["coffee_shop"],
    )

    assert facets == [
        {
            "entity_id": "place:manner-xihu",
            "entity_type": "place",
            "facet_name": "category",
            "facet_value": "coffee_shop",
            "confidence": 0.93,
            "evidence_event_ids": ["evt-1"],
            "source_type": "chrome_history",
            "extraction_method": "structured_hint",
        }
    ]
    assert matches == ["place:manner-xihu"]


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
    assert first_snapshot["preferences"]["food:sushi"]["value"] == "like"
    assert first_snapshot["preferences"]["food:sushi"]["affinity"] > 0
    assert second_snapshot is not None
    assert second_snapshot["preferences"]["food:sushi"]["value"] == "dislike"
    assert second_snapshot["preferences"]["food:sushi"]["affinity"] < 0
    assert second_snapshot["preferences_history"][0]["field"] == "food:sushi"
    assert second_snapshot["preferences_history"][0]["from"]["value"] == "like"
    assert second_snapshot["preferences_history"][0]["to"]["value"] == "dislike"


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


@pytest.mark.asyncio
async def test_l2_projection_jobs_support_enqueue_claim_complete_and_stats(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    inserted = await store.enqueue_projection_job(
        event_id="evt-proj-1",
        source="chrome_history",
        event_type="SENSOR_EVENT",
        batch_owner="owner:chrome_history:default",
    )
    duplicate = await store.enqueue_projection_job(
        event_id="evt-proj-1",
        source="chrome_history",
        event_type="SENSOR_EVENT",
        batch_owner="owner:chrome_history:default",
    )

    assert inserted is True
    assert duplicate is False

    claimed = await store.claim_projection_jobs(
        consumer_name="runtime_worker",
        limit=8,
    )

    assert len(claimed) == 1
    assert claimed[0]["event_id"] == "evt-proj-1"
    assert claimed[0]["status"] == "queued"
    assert claimed[0]["batch_owner"] == "owner:chrome_history:default"

    running_count = await store.mark_projection_jobs_running(
        ["evt-proj-1"],
        consumer_name="runtime_worker",
    )
    stats = await store.get_projection_backlog_stats()

    assert running_count == 1
    assert stats["pending"] == 0
    assert stats["queued"] == 0
    assert stats["running"] == 1
    assert stats["claimed"] == 1

    await store.complete_projection_jobs(["evt-proj-1"])
    stats = await store.get_projection_backlog_stats()

    assert stats["pending"] == 0
    assert stats["queued"] == 0
    assert stats["running"] == 0
    assert stats["claimed"] == 0
    assert stats["completed"] == 1
    assert stats["failed"] == 0


@pytest.mark.asyncio
async def test_mark_projection_jobs_running_only_transitions_queued(tmp_path):
    """mark_projection_jobs_running must not overwrite completed/failed rows."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.enqueue_projection_job(
        event_id="evt-already-done",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(consumer_name="w1", limit=1)
    assert len(claimed) == 1

    await store.mark_projection_jobs_running(["evt-already-done"], consumer_name="w1")
    await store.complete_projection_jobs(["evt-already-done"])

    stats = await store.get_projection_backlog_stats()
    assert stats["completed"] == 1
    assert stats["running"] == 0

    # A stale duplicate batch tries to mark the same event running again.
    affected = await store.mark_projection_jobs_running(
        ["evt-already-done"], consumer_name="w2",
    )
    assert affected == 0

    stats = await store.get_projection_backlog_stats()
    assert stats["completed"] == 1
    assert stats["running"] == 0


@pytest.mark.asyncio
async def test_l2_projection_jobs_support_fail_and_stale_requeue(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.enqueue_projection_job(
        event_id="evt-proj-fail",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(
        consumer_name="runtime_worker",
        limit=1,
    )
    assert [item["event_id"] for item in claimed] == ["evt-proj-fail"]
    assert claimed[0]["status"] == "queued"

    await store.fail_projection_jobs(["evt-proj-fail"], error_text="phase1 timeout", requeue=False)
    stats = await store.get_projection_backlog_stats()
    assert stats["failed"] == 1

    await store.enqueue_projection_job(
        event_id="evt-proj-stale",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(
        consumer_name="runtime_worker",
        limit=1,
    )
    assert [item["event_id"] for item in claimed] == ["evt-proj-stale"]
    assert claimed[0]["status"] == "queued"

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET status = ?, claimed_at = ?, started_at = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (
                "running",
                time.time() - 7200,
                time.time() - 7200,
                time.time() - 7200,
                "evt-proj-stale",
            ),
        )
        await db.commit()

    reset_count = await store.requeue_stale_projection_jobs(
        queued_timeout_seconds=1800,
        running_timeout_seconds=300,
    )
    assert reset_count == 1

    reclaimed = await store.claim_projection_jobs(
        consumer_name="runtime_worker_2",
        limit=1,
    )
    assert [item["event_id"] for item in reclaimed] == ["evt-proj-stale"]
    assert reclaimed[0]["attempt_count"] == 1
    assert reclaimed[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_l2_projection_jobs_do_not_requeue_queued_jobs_with_running_timeout(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.enqueue_projection_job(
        event_id="evt-proj-queued",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(
        consumer_name="runtime_worker",
        limit=1,
    )
    assert [item["event_id"] for item in claimed] == ["evt-proj-queued"]
    assert claimed[0]["status"] == "queued"

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET claimed_at = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (time.time() - 7200, time.time() - 7200, "evt-proj-queued"),
        )
        await db.commit()

    reset_count = await store.requeue_stale_projection_jobs(
        queued_timeout_seconds=1800,
        running_timeout_seconds=300,
    )
    stats = await store.get_projection_backlog_stats()

    assert reset_count == 1
    assert stats["pending"] == 1
    assert stats["queued"] == 0
    assert stats["running"] == 0
    assert stats["claimed"] == 0


@pytest.mark.asyncio
async def test_l2_projection_jobs_keep_queued_jobs_when_only_running_timeout_expires(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.enqueue_projection_job(
        event_id="evt-proj-queued-only",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(
        consumer_name="runtime_worker",
        limit=1,
    )
    assert [item["event_id"] for item in claimed] == ["evt-proj-queued-only"]
    assert claimed[0]["status"] == "queued"

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET claimed_at = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (time.time() - 600, time.time() - 600, "evt-proj-queued-only"),
        )
        await db.commit()

    reset_count = await store.requeue_stale_projection_jobs(
        queued_timeout_seconds=1800,
        running_timeout_seconds=300,
    )
    stats = await store.get_projection_backlog_stats()

    assert reset_count == 0
    assert stats["pending"] == 0
    assert stats["queued"] == 1
    assert stats["running"] == 0
    assert stats["claimed"] == 1


@pytest.mark.asyncio
async def test_claim_ready_projection_jobs_waits_for_owner_to_fill_batch(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for suffix in ("1", "2"):
        await store.enqueue_projection_job(
            event_id=f"evt-owner-wait-{suffix}",
            source="chrome_history",
            event_type="SENSOR_EVENT",
            batch_owner="chrome_history:Default:github.com",
            max_events=3,
            max_wait_seconds=180,
        )

    claimed = await store.claim_ready_projection_jobs(
        consumer_name="runtime_worker",
        limit=10,
    )
    stats = await store.get_projection_backlog_stats()

    assert claimed == []
    assert stats["pending"] == 2
    assert stats["claimed"] == 0


@pytest.mark.asyncio
async def test_claim_ready_projection_jobs_claims_full_chunks_and_leaves_remainder_pending(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for index in range(5):
        await store.enqueue_projection_job(
            event_id=f"evt-owner-chunk-{index}",
            source="chrome_history",
            event_type="SENSOR_EVENT",
            batch_owner="chrome_history:Default:x.com",
            max_events=2,
            max_wait_seconds=180,
        )

    claimed = await store.claim_ready_projection_jobs(
        consumer_name="runtime_worker",
        limit=10,
    )
    stats = await store.get_projection_backlog_stats()

    assert [item["event_id"] for item in claimed] == [
        "evt-owner-chunk-0",
        "evt-owner-chunk-1",
        "evt-owner-chunk-2",
        "evt-owner-chunk-3",
    ]
    assert stats["claimed"] == 4
    assert stats["pending"] == 1


@pytest.mark.asyncio
async def test_claim_ready_projection_jobs_claims_underfilled_owner_after_wait_threshold(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.enqueue_projection_job(
        event_id="evt-owner-aged-1",
        source="chrome_history",
        event_type="SENSOR_EVENT",
        batch_owner="chrome_history:Default:mail.google.com",
        max_events=20,
        max_wait_seconds=60,
    )
    await store.enqueue_projection_job(
        event_id="evt-owner-aged-2",
        source="chrome_history",
        event_type="SENSOR_EVENT",
        batch_owner="chrome_history:Default:mail.google.com",
        max_events=20,
        max_wait_seconds=60,
    )

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET created_at = ?, updated_at = ?
            WHERE batch_owner = ?
            """,
            (
                time.time() - 120,
                time.time() - 120,
                "chrome_history:Default:mail.google.com",
            ),
        )
        await db.commit()

    claimed = await store.claim_ready_projection_jobs(
        consumer_name="runtime_worker",
        limit=10,
    )
    stats = await store.get_projection_backlog_stats()

    assert [item["event_id"] for item in claimed] == ["evt-owner-aged-1", "evt-owner-aged-2"]
    assert stats["claimed"] == 2
    assert stats["pending"] == 0


@pytest.mark.asyncio
async def test_claim_ready_projection_jobs_uses_min_ready_events_in_steady_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l2.store import L2CognitionStore

    monkeypatch.setattr("magi.memory.l2.projection_queue.DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD", 9999)

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for index in range(8):
        await store.enqueue_projection_job(
            event_id=f"evt-owner-steady-{index}",
            source="chrome_history",
            event_type="SENSOR_EVENT",
            batch_owner="chrome_history:Default:github.com",
            catch_up_owner="chrome_history:Default:catchup:0",
            max_events=20,
            min_ready_events=8,
            max_wait_seconds=180,
        )

    claimed = await store.claim_ready_projection_jobs(
        consumer_name="runtime_worker",
        limit=20,
    )

    assert [item["event_id"] for item in claimed] == [f"evt-owner-steady-{index}" for index in range(8)]
    assert all(item["effective_batch_owner"] == "chrome_history:Default:github.com" for item in claimed)


@pytest.mark.asyncio
async def test_claim_ready_projection_jobs_merges_low_frequency_owners_in_catch_up_mode(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l2.store import L2CognitionStore

    monkeypatch.setattr("magi.memory.l2.projection_queue.DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD", 10)

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for index in range(10):
        await store.enqueue_projection_job(
            event_id=f"evt-owner-catch-a-{index}",
            source="chrome_history",
            event_type="SENSOR_EVENT",
            batch_owner="chrome_history:Default:github.com",
            catch_up_owner="chrome_history:Default:catchup:2",
            max_events=20,
            min_ready_events=8,
            max_wait_seconds=180,
        )
    for index in range(10):
        await store.enqueue_projection_job(
            event_id=f"evt-owner-catch-b-{index}",
            source="chrome_history",
            event_type="SENSOR_EVENT",
            batch_owner="chrome_history:Default:news.ycombinator.com",
            catch_up_owner="chrome_history:Default:catchup:2",
            max_events=20,
            min_ready_events=8,
            max_wait_seconds=180,
        )

    claimed = await store.claim_ready_projection_jobs(
        consumer_name="runtime_worker",
        limit=40,
    )

    assert len(claimed) == 20
    expected_event_ids = {f"evt-owner-catch-a-{index}" for index in range(10)} | {
        f"evt-owner-catch-b-{index}" for index in range(10)
    }
    assert {item["event_id"] for item in claimed} == expected_event_ids
    assert all(item["effective_batch_owner"] == "chrome_history:Default:catchup:2" for item in claimed)


# ── T1: Same (S,O) write interception ──


@pytest.mark.asyncio
async def test_same_pair_synonymous_predicate_merges_to_existing(tmp_path):
    """When LIKES already exists for (user, food:ramen), a new INTERESTED_IN
    for the same pair should reuse the LIKES edge instead of creating a new one."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    # First write: LIKES
    tid1 = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.7,
        observed_at=1710000000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    # Second write: INTERESTED_IN (synonymous with LIKES in the affinity group)
    tid2 = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="INTERESTED_IN",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-2"],
        confidence=0.6,
        observed_at=1710001000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    # Should be merged into same edge
    assert tid1 == tid2

    edges = await store.get_relationships(subject_id="user:u1", status="active")
    assert len(edges) == 1
    assert edges[0]["predicate"] == "LIKES"
    assert edges[0]["observation_count"] == 2


@pytest.mark.asyncio
async def test_same_pair_different_group_predicates_coexist(tmp_path):
    """USES and LIKES for the same (S,O) pair should NOT merge because they
    belong to different synonym groups."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid1 = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="USES",
        object_id="software:vscode",
        object_type="software",
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=1710000000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    tid2 = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="software:vscode",
        object_type="software",
        evidence_event_ids=["evt-2"],
        confidence=0.7,
        observed_at=1710001000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    assert tid1 != tid2

    edges = await store.get_relationships(subject_id="user:u1", status="active")
    assert len(edges) == 2


@pytest.mark.asyncio
async def test_same_pair_opposite_predicates_do_not_merge(tmp_path):
    """LIKES and DISLIKES for the same (S,O) pair should NOT merge because
    they have an antonym relationship, not a synonym one."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid1 = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:cilantro",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.7,
        observed_at=1710000000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    tid2 = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="food:cilantro",
        object_type="food",
        evidence_event_ids=["evt-2"],
        confidence=0.8,
        observed_at=1710001000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    # Different groups → different edges (conflict resolution handles deprecation separately)
    assert tid1 != tid2


# ── T2: corroborate_edge ──


@pytest.mark.asyncio
async def test_corroborate_edge_accumulates_confidence(tmp_path):
    """corroborate_edge should increase observation_count and confidence."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.6,
        observed_at=1710000000.0,
        source_type="chat",
        extraction_method="llm_phase2_integration",
    )

    result = await store.corroborate_edge(
        triple_id=tid,
        evidence_event_ids=["evt-2"],
        new_confidence=0.5,
        observed_at=1710001000.0,
    )

    assert result is True

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["observation_count"] == 2
    assert edge["confidence"] > 0.6  # Noisy-OR accumulation
    assert "evt-2" in edge["evidence_event_ids"]


@pytest.mark.asyncio
async def test_corroborate_edge_preserves_observed_time_bounds_for_older_evidence(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="VISITED",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-late"],
        confidence=0.6,
        observed_at=1710010000.0,
        source_type="photo_library",
    )

    await store.corroborate_edge(
        triple_id=tid,
        evidence_event_ids=["evt-early"],
        new_confidence=0.5,
        observed_at=1710000000.0,
    )

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["first_observed_at"] == 1710000000.0
    assert edge["last_observed_at"] == 1710010000.0


@pytest.mark.asyncio
async def test_corroborate_edge_missing_triple_returns_false(tmp_path):
    """corroborate_edge on a non-existent triple should return False."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    result = await store.corroborate_edge(
        triple_id="triple_nonexistent",
        evidence_event_ids=["evt-1"],
        new_confidence=0.5,
        observed_at=1710000000.0,
    )

    assert result is False


# ---------------------------------------------------------------------------
# T4: evidence_text + natural_summary + embedding_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_edge_stores_evidence_text_and_natural_summary(tmp_path):
    """New edges should persist evidence_text, natural_summary, and embedding_status='pending'."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=1710000000.0,
        source_type="chat",
        evidence_text="I really love ramen",
    )

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["evidence_text"] == "I really love ramen"
    assert edge["natural_summary"] == "I really love ramen"
    assert edge["embedding_status"] == "pending"


@pytest.mark.asyncio
async def test_upsert_edge_generates_natural_summary_when_evidence_text_empty(tmp_path):
    """When evidence_text is empty, natural_summary should be auto-generated from S/P/O."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=1710000000.0,
        source_type="chat",
    )

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["evidence_text"] == ""
    assert "LIKES" in edge["natural_summary"]
    assert "user:u1" in edge["natural_summary"]


@pytest.mark.asyncio
async def test_corroborate_keeps_longer_evidence_text(tmp_path):
    """corroborate_edge should keep the longer evidence_text."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-1"],
        confidence=0.6,
        observed_at=1710000000.0,
        source_type="chat",
        evidence_text="short",
    )

    await store.corroborate_edge(
        triple_id=tid,
        evidence_event_ids=["evt-2"],
        new_confidence=0.5,
        observed_at=1710001000.0,
        evidence_text="this is a much longer evidence text describing the relationship",
    )

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["evidence_text"] == "this is a much longer evidence text describing the relationship"


# ---------------------------------------------------------------------------
# T6: future_intent TTL expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_future_intent_auto_sets_expires_at(tmp_path):
    """Edges with fact_kind='future_intent' should auto-populate expires_at."""
    from magi.memory.l2.store import L2CognitionStore, DEFAULT_FUTURE_INTENT_TTL_SECONDS

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    observed = 1710000000.0
    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="PLANS_TO",
        object_id="activity:travel-japan",
        object_type="activity",
        fact_kind="future_intent",
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=observed,
        source_type="chat",
    )

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["expires_at"] is not None
    assert abs(edge["expires_at"] - (observed + DEFAULT_FUTURE_INTENT_TTL_SECONDS)) < 1.0


@pytest.mark.asyncio
async def test_non_future_intent_does_not_set_expires_at(tmp_path):
    """Edges with other fact_kinds should not auto-populate expires_at."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    tid = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        fact_kind="explicit_fact",
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=1710000000.0,
        source_type="chat",
    )

    edge = await store.get_relationship(triple_id=tid)
    assert edge is not None
    assert edge["expires_at"] is None


@pytest.mark.asyncio
async def test_initialize_creates_query_indexes(tmp_path):
    """Verify secondary indexes exist on knowledge_graph and tom_trait_assertions."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'knowledge_graph'"
        ) as cursor:
            kg_indexes = {row[0] for row in await cursor.fetchall()}

        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tom_trait_assertions'"
        ) as cursor:
            ta_indexes = {row[0] for row in await cursor.fetchall()}

    assert "idx_knowledge_graph_status_subject" in kg_indexes
    assert "idx_knowledge_graph_status_object" in kg_indexes
    assert "idx_knowledge_graph_status_predicate" in kg_indexes
    assert "idx_tom_assertions_entity_updated" in ta_indexes


@pytest.mark.asyncio
async def test_find_edges_by_event_id_uses_sqlite_like(tmp_path):
    """find_edges_by_event_id should use SQL LIKE instead of loading all rows."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:ramen",
        object_type="food",
        evidence_event_ids=["evt-find-1", "evt-find-2"],
        confidence=0.5,
        observed_at=1710000000.0,
        source_type="chat",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-find-3"],
        confidence=0.5,
        observed_at=1710000000.0,
        source_type="chat",
    )

    results = await store.find_edges_by_event_id("evt-find-1")
    assert len(results) == 1
    assert results[0]["object_id"] == "food:ramen"

    results = await store.find_edges_by_event_id("evt-find-2")
    assert len(results) == 1
    assert results[0]["object_id"] == "food:ramen"

    results = await store.find_edges_by_event_id("evt-find-3")
    assert len(results) == 1
    assert results[0]["object_id"] == "food:sushi"

    results = await store.find_edges_by_event_id("evt-find-999")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_batch_get_relationships_returns_grouped_by_entity(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="LIKES", object_id="food:ramen", object_type="food",
        evidence_event_ids=["e1"], confidence=0.5, observed_at=1710000000.0, source_type="chat",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="DISLIKES", object_id="food:sushi", object_type="food",
        evidence_event_ids=["e2"], confidence=0.4, observed_at=1710001000.0, source_type="chat",
    )
    await store.upsert_knowledge_edge(
        subject_id="person:alice", subject_type="person",
        predicate="LIKES", object_id="food:pasta", object_type="food",
        evidence_event_ids=["e3"], confidence=0.6, observed_at=1710002000.0, source_type="chat",
    )

    result = await store.batch_get_relationships(
        entity_ids=["user:u1", "person:alice"],
        direction="outgoing",
    )
    assert "user:u1" in result
    assert "person:alice" in result
    assert len(result["user:u1"]) == 2
    assert len(result["person:alice"]) == 1
    assert result["person:alice"][0]["object_id"] == "food:pasta"


@pytest.mark.asyncio
async def test_batch_get_relationships_incoming_direction(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="FOLLOWS", object_id="person:alice", object_type="person",
        evidence_event_ids=["e1"], confidence=0.5, observed_at=1710000000.0, source_type="chat",
    )

    result = await store.batch_get_relationships(
        entity_ids=["person:alice"],
        direction="incoming",
    )
    assert len(result["person:alice"]) == 1
    assert result["person:alice"][0]["subject_id"] == "user:u1"


@pytest.mark.asyncio
async def test_batch_get_relationships_both_direction_deduplicates(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="person:alice", subject_type="person",
        predicate="KNOWS", object_id="person:bob", object_type="person",
        evidence_event_ids=["e1"], confidence=0.5, observed_at=1710000000.0, source_type="chat",
    )

    result = await store.batch_get_relationships(
        entity_ids=["person:alice"],
        direction="both",
    )
    assert len(result["person:alice"]) == 1


@pytest.mark.asyncio
async def test_batch_get_relationships_target_object_id_filter(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="LIKES", object_id="food:ramen", object_type="food",
        evidence_event_ids=["e1"], confidence=0.5, observed_at=1710000000.0, source_type="chat",
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="LIKES", object_id="food:sushi", object_type="food",
        evidence_event_ids=["e2"], confidence=0.5, observed_at=1710001000.0, source_type="chat",
    )

    result = await store.batch_get_relationships(
        entity_ids=["user:u1"],
        direction="outgoing",
        target_object_id="food:ramen",
    )
    assert len(result["user:u1"]) == 1
    assert result["user:u1"][0]["object_id"] == "food:ramen"


@pytest.mark.asyncio
async def test_batch_get_relationships_empty_ids_returns_empty(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    result = await store.batch_get_relationships(entity_ids=[])
    assert result == {}


@pytest.mark.asyncio
async def test_batch_list_tom_assertions_returns_grouped(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_assertion_candidate({
        "entity_id": "user:u1", "entity_type": "user",
        "trait_family": "preference", "trait_name": "food_taste",
        "trait_value": "spicy", "confidence_score": 0.5,
        "evidence_events": ["e1"], "volatility_index": 0.3,
        "source_domain": "user_authored", "inference_depth": "direct",
        "validation_state": "tentative",
        "first_inferred_at": 1710000000.0, "last_validated_at": 1710000000.0,
    })
    await store.upsert_assertion_candidate({
        "entity_id": "person:alice", "entity_type": "person",
        "trait_family": "personality", "trait_name": "mood",
        "trait_value": "cheerful", "confidence_score": 0.6,
        "evidence_events": ["e2"], "volatility_index": 0.2,
        "source_domain": "user_authored", "inference_depth": "direct",
        "validation_state": "tentative",
        "first_inferred_at": 1710000000.0, "last_validated_at": 1710000000.0,
    })

    result = await store.batch_list_tom_assertions(
        entity_ids=["user:u1", "person:alice"],
    )
    assert "user:u1" in result
    assert "person:alice" in result
    assert len(result["user:u1"]) == 1
    assert result["user:u1"][0]["trait_name"] == "food_taste"
    assert len(result["person:alice"]) == 1
    assert result["person:alice"][0]["trait_name"] == "mood"


@pytest.mark.asyncio
async def test_batch_list_tom_assertions_filters_trait_families(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    for family in ("preference", "personality"):
        await store.upsert_assertion_candidate({
            "entity_id": "user:u1", "entity_type": "user",
            "trait_family": family, "trait_name": f"test_{family}",
            "trait_value": "val", "confidence_score": 0.5,
            "evidence_events": ["e1"], "volatility_index": 0.3,
            "source_domain": "user_authored", "inference_depth": "direct",
            "validation_state": "tentative",
            "first_inferred_at": 1710000000.0, "last_validated_at": 1710000000.0,
        })

    result = await store.batch_list_tom_assertions(
        entity_ids=["user:u1"],
        trait_families=["preference"],
    )
    assert len(result["user:u1"]) == 1
    assert result["user:u1"][0]["trait_family"] == "preference"


@pytest.mark.asyncio
async def test_batch_list_tom_assertions_empty_ids_returns_empty(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    result = await store.batch_list_tom_assertions(entity_ids=[])
    assert result == {}


@pytest.mark.asyncio
async def test_batch_get_tom_snapshots_returns_multiple(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    # Create assertions and refresh snapshots to populate tom_snapshots table
    for eid, etype in [("user:u1", "user"), ("person:alice", "person")]:
        await store.upsert_assertion_candidate({
            "entity_id": eid, "entity_type": etype,
            "trait_family": "personality", "trait_name": "mood",
            "trait_value": "happy", "confidence_score": 0.5,
            "evidence_events": ["e1"], "volatility_index": 0.3,
            "source_domain": "user_authored", "inference_depth": "direct",
            "validation_state": "corroborated",
            "first_inferred_at": 1710000000.0, "last_validated_at": 1710000000.0,
        })
        await store.refresh_entity_snapshot(entity_id=eid, entity_type=etype)

    result = await store.batch_get_tom_snapshots(entities=[
        {"entity_id": "user:u1", "entity_type": "user"},
        {"entity_id": "person:alice", "entity_type": "person"},
    ])
    assert len(result) == 2
    entity_ids = {r["entity_id"] for r in result}
    assert "user:u1" in entity_ids
    assert "person:alice" in entity_ids


@pytest.mark.asyncio
async def test_batch_get_tom_snapshots_empty_input_returns_empty(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    result = await store.batch_get_tom_snapshots(entities=[])
    assert result == []


@pytest.mark.asyncio
async def test_search_edges_by_embedding_returns_filtered_edges(tmp_path):
    """search_edges_by_embedding queries vector index and returns matching edges."""
    from dataclasses import dataclass
    from unittest.mock import AsyncMock

    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    # Insert two edges
    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="LIKES", object_id="food:sushi", object_type="food",
        evidence_event_ids=["e1"], confidence=0.8, source_type="llm",
        extraction_method="phase2", evidence_text="User loves sushi",
        observed_at=1000.0,
    )
    await store.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user",
        predicate="DISLIKES", object_id="food:natto", object_type="food",
        evidence_event_ids=["e2"], confidence=0.7, source_type="llm",
        extraction_method="phase2", evidence_text="User hates natto",
        observed_at=1000.0,
    )

    # Manually deprecate the natto edge and get triple IDs
    async with aiosqlite.connect(str(tmp_path / "l2.db")) as conn:
        conn.row_factory = aiosqlite.Row
        rows = [dict(r) async for r in await conn.execute(
            "SELECT triple_id, predicate FROM knowledge_graph ORDER BY predicate"
        )]
        assert len(rows) == 2
        natto_row = next(r for r in rows if r["predicate"] == "DISLIKES")
        sushi_row = next(r for r in rows if r["predicate"] == "LIKES")
        await conn.execute(
            "UPDATE knowledge_graph SET status = 'deprecated' WHERE triple_id = ?",
            (natto_row["triple_id"],),
        )
        await conn.commit()

    sushi_triple = sushi_row["triple_id"]
    natto_triple = natto_row["triple_id"]

    @dataclass
    class FakeHit:
        entity_id: str
        distance: float

    @dataclass
    class FakeEmbedding:
        model_name: str = "test"
        dimension: int = 8
        vector: list = None

    # Return both triple IDs from vector search
    mock_index = AsyncMock()
    mock_index.search.return_value = [
        FakeHit(entity_id=sushi_triple, distance=0.1),
        FakeHit(entity_id=natto_triple, distance=0.3),
    ]

    # Only active edges should return
    results = await store.search_edges_by_embedding(
        vector_index=mock_index,
        embedding=FakeEmbedding(),
        limit=10,
        status_filters=["active"],
    )
    assert len(results) == 1
    assert results[0]["triple_id"] == sushi_triple
    assert results[0]["evidence_text"] == "User loves sushi"
    assert results[0]["vector_distance"] == 0.1


@pytest.mark.asyncio
async def test_search_edges_by_embedding_returns_empty_without_index(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    results = await store.search_edges_by_embedding(
        vector_index=None,
        embedding=None,
        limit=10,
    )
    assert results == []


# -----------------------------------------------------------------------
# A1: Temporary-state traits get corroborated with single evidence
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temporary_trait_corroborated_with_single_evidence(tmp_path):
    """Stress/mood/engagement should reach 'corroborated' with just 1 evidence."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    event = await _build_user_message(
        "I feel really stressed about the deadline.",
        correlation_id="evt-temp-1",
        timestamp=1710000000.0,
    )
    await _apply_rule_candidates(store, event)

    # Reconciliation promotes temporary traits with single evidence
    await store.reconcile_entity(entity_id="user:u1", entity_type="user")

    assertions = await store.list_tom_assertions(entity_id="user:u1")
    assert len(assertions) == 1
    assert assertions[0]["trait_name"] == "stress_level"
    # With A1 change, single evidence should promote to corroborated
    assert assertions[0]["validation_state"] == "corroborated"
    assert assertions[0]["confidence_score"] >= 0.50


@pytest.mark.asyncio
async def test_temporary_trait_corroborated_appears_in_snapshot(tmp_path):
    """A corroborated temporary trait should appear in the entity snapshot."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    event = await _build_user_message(
        "I have been stressed about work.",
        correlation_id="evt-snap-temp-1",
        timestamp=1710000000.0,
    )
    await _apply_rule_candidates(store, event)

    # Reconcile to promote temporary trait
    await store.reconcile_entity(entity_id="user:u1", entity_type="user")

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None
    # Corroborated stress_level should now appear in snapshot
    stress = snapshot.get("current_stress_level")
    if stress is None:
        stress = (snapshot.get("core_traits") or {}).get("stress_level")
    assert stress is not None


@pytest.mark.asyncio
async def test_non_temporary_trait_still_requires_multiple_evidence(tmp_path):
    """Non-temporary traits (e.g. preference_profile) still need >=2 evidence."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    # Directly insert a non-temporary assertion with 1 evidence
    now = time.time()
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.coffee",
        "trait_value": "likes_dark_roast",
        "confidence_score": 0.25,
        "validation_state": "tentative",
        "temporal_scope": "stable",
        "decay_policy": "evidence_only",
        "evidence_events": ["evt-pref-1"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "defensive_psychology",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    outcomes = await store.reconcile_entity(
        entity_id="user:u1",
        entity_type="user",
        evidence_timestamps={"evt-pref-1": 1710000000.0},
    )
    assert len(outcomes) == 1
    # Single evidence for a non-temporary trait stays tentative
    assert outcomes[0].status == "tentative"


# -----------------------------------------------------------------------
# B2: expire_session_decay_assertions
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expire_session_decay_assertions_expires_tentative(tmp_path):
    """Session-end should expire tentative session_decay assertions."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "happy",
        "confidence_score": 0.25,
        "validation_state": "tentative",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-mood-1"],
        "volatility_index": 0.5,
        "source_domain": "chat",
        "inference_depth": "defensive_psychology",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    expired_count = await store.expire_session_decay_assertions(entity_ids=["user:u1"])
    assert expired_count == 1

    assertions = await store.list_tom_assertions(entity_id="user:u1")
    assert assertions[0]["validation_state"] == "expired"


@pytest.mark.asyncio
async def test_expire_session_decay_does_not_touch_corroborated(tmp_path):
    """Corroborated session_decay assertions should survive session end."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "happy",
        "confidence_score": 0.60,
        "validation_state": "corroborated",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-mood-1", "evt-mood-2"],
        "volatility_index": 0.5,
        "source_domain": "chat",
        "inference_depth": "defensive_psychology",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    expired_count = await store.expire_session_decay_assertions(entity_ids=["user:u1"])
    assert expired_count == 0

    assertions = await store.list_tom_assertions(entity_id="user:u1")
    assert assertions[0]["validation_state"] == "corroborated"


# -----------------------------------------------------------------------
# C1: Emerging signals in snapshot
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_includes_emerging_signals(tmp_path):
    """Tentative assertions should appear in snapshot.emerging_signals."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()

    # Insert a tentative assertion (single evidence, won't promote without reconcile)
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.coffee",
        "trait_value": "likes_strong_coffee",
        "confidence_score": 0.25,
        "validation_state": "tentative",
        "temporal_scope": "persistent",
        "decay_policy": "",
        "evidence_events": ["evt-1"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    # Also insert a corroborated assertion so snapshot isn't empty
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "happy",
        "confidence_score": 0.60,
        "validation_state": "corroborated",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-2", "evt-3"],
        "volatility_index": 0.5,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    # Tentative assertion should appear in emerging_signals
    emerging = snapshot.get("emerging_signals", [])
    assert len(emerging) == 1
    assert emerging[0]["trait_name"] == "preference.coffee"
    assert emerging[0]["trait_value"] == "likes_strong_coffee"
    assert emerging[0]["confidence"] == pytest.approx(0.25, abs=0.01)
    assert emerging[0]["evidence_count"] == 1

    # Corroborated assertion should NOT appear in emerging_signals
    assert all(s["trait_name"] != "mood" for s in emerging)

    # But mood should appear in the active snapshot data
    assert snapshot["current_mood"] == "happy"


@pytest.mark.asyncio
async def test_snapshot_emerging_signals_empty_when_no_tentative(tmp_path):
    """Snapshot should have empty emerging_signals when all assertions are confirmed."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()

    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "focused",
        "confidence_score": 0.60,
        "validation_state": "corroborated",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-1", "evt-2"],
        "volatility_index": 0.5,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None
    assert snapshot.get("emerging_signals", []) == []


@pytest.mark.asyncio
async def test_snapshot_mood_trajectory_tracks_temporal_assertions(tmp_path):
    """Mood trajectory should collect mood/stress/engagement assertions sorted by time."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()

    # Insert assertions from different temporal families at different times.
    # Note: upsert deduplicates by (entity_id, trait_name, target_entity_id),
    # so each entry must have a distinct trait_name.
    for i, (family, name, value, offset) in enumerate([
        ("mood", "mood", "calm", -1800),                    # 30min ago
        ("stress", "stress_level", "high", -3600),           # 1h ago
        ("engagement", "engagement", "focused", -600),       # 10min ago
    ]):
        await store.upsert_assertion_candidate({
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": family,
            "trait_name": name,
            "trait_value": value,
            "confidence_score": 0.60,
            "validation_state": "corroborated",
            "temporal_scope": "session",
            "decay_policy": "session_decay",
            "evidence_events": [f"evt-{i}"],
            "volatility_index": 0.5,
            "source_domain": "chat",
            "inference_depth": "direct",
            "first_inferred_at": now + offset,
            "last_validated_at": now + offset,
        })

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    trajectory = snapshot.get("mood_trajectory", [])
    assert len(trajectory) == 3

    # Should be sorted by time ascending (oldest first)
    assert trajectory[0]["family"] == "stress"
    assert trajectory[0]["value"] == "high"
    assert trajectory[1]["family"] == "mood"
    assert trajectory[1]["value"] == "calm"
    assert trajectory[2]["family"] == "engagement"
    assert trajectory[2]["value"] == "focused"

    # All should have confidence and timestamp
    for entry in trajectory:
        assert "confidence" in entry
        assert "at" in entry
        assert entry["confidence"] == pytest.approx(0.60, abs=0.01)


@pytest.mark.asyncio
async def test_snapshot_mood_trajectory_includes_expired_assertions(tmp_path):
    """Mood trajectory should accumulate entries across snapshot refreshes, preserving history."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()

    # First: insert a mood=sad assertion and snapshot
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "sad",
        "confidence_score": 0.70,
        "validation_state": "corroborated",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-1"],
        "volatility_index": 0.5,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now - 3600,
        "last_validated_at": now - 3600,
    })
    snap1 = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snap1 is not None
    assert len(snap1.get("mood_trajectory", [])) == 1
    assert snap1["mood_trajectory"][0]["value"] == "sad"

    # Second: update the same assertion to mood=happy and snapshot again
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "happy",
        "confidence_score": 0.80,
        "validation_state": "corroborated",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-2"],
        "volatility_index": 0.3,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now,
        "last_validated_at": now,
    })
    snap2 = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snap2 is not None

    trajectory = snap2.get("mood_trajectory", [])
    # Should have accumulated both mood states across the two refreshes
    assert len(trajectory) == 2
    assert trajectory[0]["value"] == "sad"
    assert trajectory[1]["value"] == "happy"


@pytest.mark.asyncio
async def test_snapshot_mood_trajectory_excludes_non_temporal_families(tmp_path):
    """Non-temporal families like preference_profile should not appear in mood_trajectory."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()

    # Insert a preference assertion (not a temporal family)
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.coffee",
        "trait_value": "likes_strong_coffee",
        "confidence_score": 0.90,
        "validation_state": "stable",
        "temporal_scope": "persistent",
        "decay_policy": "",
        "evidence_events": ["evt-1", "evt-2", "evt-3"],
        "volatility_index": 0.1,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    # Insert a mood assertion so snapshot isn't trivial
    await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "mood",
        "trait_name": "mood",
        "trait_value": "content",
        "confidence_score": 0.60,
        "validation_state": "corroborated",
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "evidence_events": ["evt-4"],
        "volatility_index": 0.5,
        "source_domain": "chat",
        "inference_depth": "direct",
        "first_inferred_at": now,
        "last_validated_at": now,
    })

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    trajectory = snapshot.get("mood_trajectory", [])
    # Only mood assertion, not preference_profile
    assert len(trajectory) == 1
    assert trajectory[0]["family"] == "mood"
    assert all(e["family"] in {"mood", "stress", "engagement"} for e in trajectory)


@pytest.mark.asyncio
async def test_snapshot_mood_trajectory_capped_at_limit(tmp_path):
    """Mood trajectory should keep only the most recent entries when exceeding limit."""
    from magi.memory.l2.store import L2CognitionStore, _MOOD_TRAJECTORY_LIMIT

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    now = time.time()
    count = _MOOD_TRAJECTORY_LIMIT + 5

    # Simulate accumulation by alternating mood values and refreshing each time
    for i in range(count):
        await store.upsert_assertion_candidate({
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "mood",
            "trait_name": "mood",
            "trait_value": f"mood_{i}",
            "confidence_score": 0.60,
            "validation_state": "corroborated",
            "temporal_scope": "session",
            "decay_policy": "session_decay",
            "evidence_events": [f"evt-{i}"],
            "volatility_index": 0.5,
            "source_domain": "chat",
            "inference_depth": "direct",
            "first_inferred_at": now + i * 600,
            "last_validated_at": now + i * 600,
        })
        await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")

    snapshot = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    trajectory = snapshot.get("mood_trajectory", [])
    assert len(trajectory) == _MOOD_TRAJECTORY_LIMIT

    # Should contain the most recent entries
    assert trajectory[-1]["value"] == f"mood_{count - 1}"
    assert trajectory[0]["value"] == f"mood_{count - _MOOD_TRAJECTORY_LIMIT}"


# ---------------------------------------------------------------------------
# Preference enrichment from taste_profile / preference_profile assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_preferences_enriched_from_taste_profile_assertions(tmp_path):
    """taste_profile assertions should appear in snapshot preferences with affinity."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "taste_profile",
            "trait_name": "jazz_affinity",
            "trait_value": "enjoys jazz guitar",
            "confidence_score": 0.75,
            "evidence_events": ["evt-jazz-1", "evt-jazz-2", "evt-jazz-3"],
            "volatility_index": 0.3,
            "source_domain": "sensor",
            "inference_depth": "direct",
            "validation_state": "stable",
            "first_inferred_at": now - 3600,
            "last_validated_at": now,
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "persistent",
            "decay_policy": "none",
            "decay_anchor_at": now,
            "context_ref_id": "",
            "expires_at": None,
        }
    )

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    pref = snapshot["preferences"].get("jazz_affinity")
    assert pref is not None
    assert pref["value"] == "enjoys jazz guitar"
    assert pref["family"] == "taste_profile"
    # affinity = min(1.0, 0.75 * (1 + 0.1 * 3)) = 0.75 * 1.3 = 0.975
    assert 0.9 < pref["affinity"] <= 1.0


@pytest.mark.asyncio
async def test_snapshot_preferences_enriched_from_preference_profile_assertions(tmp_path):
    """preference_profile assertions should also appear in preferences with affinity."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "communication_style",
            "trait_value": "concise",
            "confidence_score": 0.60,
            "evidence_events": ["evt-style-1"],
            "volatility_index": 0.2,
            "source_domain": "chat",
            "inference_depth": "direct",
            "validation_state": "stable",
            "first_inferred_at": now - 7200,
            "last_validated_at": now,
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "persistent",
            "decay_policy": "none",
            "decay_anchor_at": now,
            "context_ref_id": "",
            "expires_at": None,
        }
    )

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    pref = snapshot["preferences"].get("communication_style")
    assert pref is not None
    assert pref["value"] == "concise"
    assert pref["family"] == "preference_profile"
    # affinity = min(1.0, 0.60 * (1 + 0.1 * 1)) = 0.60 * 1.1 = 0.66
    assert 0.6 < pref["affinity"] < 0.7


@pytest.mark.asyncio
async def test_snapshot_preference_affinity_computation(tmp_path):
    """Affinity must scale with confidence and evidence count, capped at 1.0."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    # High confidence + many evidence → capped at 1.0
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "taste_profile",
            "trait_name": "coffee_preference",
            "trait_value": "strong espresso",
            "confidence_score": 0.95,
            "evidence_events": [f"evt-coffee-{i}" for i in range(10)],
            "volatility_index": 0.1,
            "source_domain": "chat",
            "inference_depth": "direct",
            "validation_state": "stable",
            "first_inferred_at": now - 86400,
            "last_validated_at": now,
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "persistent",
            "decay_policy": "none",
            "decay_anchor_at": now,
            "context_ref_id": "",
            "expires_at": None,
        }
    )

    # Low confidence + single evidence → low affinity
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "taste_profile",
            "trait_name": "tea_preference",
            "trait_value": "green tea",
            "confidence_score": 0.30,
            "evidence_events": ["evt-tea-1"],
            "volatility_index": 0.5,
            "source_domain": "chat",
            "inference_depth": "direct",
            "validation_state": "stable",
            "first_inferred_at": now - 600,
            "last_validated_at": now,
            "target_entity_id": "",
            "target_entity_type": "",
            "target_scope": "global",
            "temporal_scope": "persistent",
            "decay_policy": "none",
            "decay_anchor_at": now,
            "context_ref_id": "",
            "expires_at": None,
        }
    )

    snapshot = await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    assert snapshot is not None

    coffee = snapshot["preferences"]["coffee_preference"]
    # 0.95 * (1 + 0.1 * 5) = 0.95 * 1.5 = 1.425 → capped at 1.0
    assert coffee["affinity"] == 1.0

    tea = snapshot["preferences"]["tea_preference"]
    # 0.30 * (1 + 0.1 * 1) = 0.30 * 1.1 = 0.33
    assert tea["affinity"] == 0.33


# ── P0: State Memory Supersession Tests ─────────────────────────────


def _make_assertion_candidate(
    *,
    entity_id: str = "user:u1",
    entity_type: str = "user",
    trait_family: str = "emotion",
    trait_name: str = "mood",
    trait_value: str = "happy",
    confidence_score: float = 0.25,
    evidence_events: list | None = None,
    volatility_index: float = 0.5,
    source_domain: str = "chat",
    inference_depth: str = "surface",
    validation_state: str = "tentative",
    first_inferred_at: float = 1710000000.0,
    last_validated_at: float = 1710000000.0,
    target_entity_id: str = "",
    target_entity_type: str = "",
    target_scope: str = "global",
    temporal_scope: str = "persistent",
    decay_policy: str = "standard_decay",
    decay_anchor_at: float | None = None,
    context_ref_id: str = "",
    expires_at: float | None = None,
) -> dict:
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "trait_family": trait_family,
        "trait_name": trait_name,
        "trait_value": trait_value,
        "confidence_score": confidence_score,
        "evidence_events": evidence_events or ["evt-1"],
        "volatility_index": volatility_index,
        "source_domain": source_domain,
        "inference_depth": inference_depth,
        "validation_state": validation_state,
        "first_inferred_at": first_inferred_at,
        "last_validated_at": last_validated_at,
        "target_entity_id": target_entity_id,
        "target_entity_type": target_entity_type,
        "target_scope": target_scope,
        "temporal_scope": temporal_scope,
        "decay_policy": decay_policy,
        "decay_anchor_at": decay_anchor_at,
        "context_ref_id": context_ref_id,
        "expires_at": expires_at,
    }


@pytest.mark.asyncio
async def test_persistent_value_change_supersedes_old_assertion(tmp_path):
    """When a persistent-scope assertion value changes, old is superseded and new is inserted."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    # Insert initial assertion
    c1 = _make_assertion_candidate(trait_value="happy", evidence_events=["evt-1"])
    id1 = await store.upsert_assertion_candidate(c1)

    # Change value — should supersede
    c2 = _make_assertion_candidate(
        trait_value="sad",
        evidence_events=["evt-2"],
        last_validated_at=1710010000.0,
    )
    id2 = await store.upsert_assertion_candidate(c2)

    assert id1 != id2

    old = await store.get_tom_assertion(assertion_id=id1)
    new = await store.get_tom_assertion(assertion_id=id2)

    assert old is not None
    assert old["status"] == "superseded"
    assert old["superseded_by"] == id2
    assert old["superseded_at"] is not None

    assert new is not None
    assert new["status"] == "tentative"
    assert new["trait_value"] == "sad"


@pytest.mark.asyncio
async def test_session_scope_value_change_updates_in_place(tmp_path):
    """Session-scope assertions update in place on value change, not supersede."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    c1 = _make_assertion_candidate(
        trait_value="happy",
        temporal_scope="session",
        evidence_events=["evt-1"],
    )
    id1 = await store.upsert_assertion_candidate(c1)

    c2 = _make_assertion_candidate(
        trait_value="sad",
        temporal_scope="session",
        evidence_events=["evt-2"],
        last_validated_at=1710010000.0,
    )
    id2 = await store.upsert_assertion_candidate(c2)

    # Same assertion_id — updated in place
    assert id1 == id2

    a = await store.get_tom_assertion(assertion_id=id1)
    assert a is not None
    assert a["trait_value"] == "sad"
    assert a["status"] == "contradicted"


@pytest.mark.asyncio
async def test_same_value_corroboration_keeps_same_id(tmp_path):
    """Repeated same-value evidence corroborates without superseding."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    c1 = _make_assertion_candidate(trait_value="happy", evidence_events=["evt-1"])
    id1 = await store.upsert_assertion_candidate(c1)

    c2 = _make_assertion_candidate(
        trait_value="happy",
        evidence_events=["evt-2"],
        last_validated_at=1710010000.0,
    )
    id2 = await store.upsert_assertion_candidate(c2)

    assert id1 == id2

    a = await store.get_tom_assertion(assertion_id=id1)
    assert a is not None
    assert a["status"] == "corroborated"
    assert a["confidence_score"] > 0.3


@pytest.mark.asyncio
async def test_user_correction_supersedes_and_creates_stable(tmp_path):
    """correct_assertion creates a new stable assertion and supersedes the old."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    c1 = _make_assertion_candidate(
        trait_name="location",
        trait_value="Hangzhou",
        evidence_events=["evt-1"],
    )
    id1 = await store.upsert_assertion_candidate(c1)

    result = await store.correct_assertion(
        assertion_id=id1,
        new_value="Shanghai",
        reason="I moved",
    )

    assert result is not None
    assert result["trait_value"] == "Shanghai"
    assert result["status"] == "stable"
    assert result["confidence_score"] == 0.95
    assert result["source_domain"] == "user_correction"

    old = await store.get_tom_assertion(assertion_id=id1)
    assert old is not None
    assert old["status"] == "superseded"
    assert old["superseded_by"] == result["assertion_id"]


@pytest.mark.asyncio
async def test_superseded_assertion_excluded_from_new_upsert(tmp_path):
    """A superseded assertion should not be found by the upsert query."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    c1 = _make_assertion_candidate(trait_value="A", evidence_events=["evt-1"])
    id1 = await store.upsert_assertion_candidate(c1)

    # Supersede via value change
    c2 = _make_assertion_candidate(
        trait_value="B",
        evidence_events=["evt-2"],
        last_validated_at=1710010000.0,
    )
    id2 = await store.upsert_assertion_candidate(c2)

    # Now insert same value as original — should create new, not match superseded
    c3 = _make_assertion_candidate(
        trait_value="B",
        evidence_events=["evt-3"],
        last_validated_at=1710020000.0,
    )
    id3 = await store.upsert_assertion_candidate(c3)

    # Should corroborate id2, not resurrect id1
    assert id3 == id2

    old = await store.get_tom_assertion(assertion_id=id1)
    assert old["status"] == "superseded"


@pytest.mark.asyncio
async def test_assertion_row_includes_status_columns(tmp_path):
    """_assertion_row_to_dict includes status, superseded_by, superseded_at, privacy_scope."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    c1 = _make_assertion_candidate(trait_value="test", evidence_events=["evt-1"])
    id1 = await store.upsert_assertion_candidate(c1)

    a = await store.get_tom_assertion(assertion_id=id1)
    assert a is not None
    assert "status" in a
    assert "superseded_by" in a
    assert "superseded_at" in a
    assert "privacy_scope" in a
    assert a["privacy_scope"] == "private"


@pytest.mark.asyncio
async def test_schema_migration_adds_new_columns(tmp_path):
    """Existing DB without status columns gets them added on init."""
    import aiosqlite as _aiosqlite

    db_path = tmp_path / "l2.db"
    # Create a minimal old-schema table
    async with _aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE tom_trait_assertions (
                assertion_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'user',
                trait_family TEXT NOT NULL,
                trait_name TEXT NOT NULL,
                trait_value TEXT NOT NULL,
                confidence_score REAL NOT NULL DEFAULT 0.5,
                evidence_events TEXT NOT NULL DEFAULT '[]',
                volatility_index REAL NOT NULL DEFAULT 0.5,
                source_domain TEXT NOT NULL DEFAULT 'chat',
                inference_depth TEXT NOT NULL DEFAULT 'surface',
                validation_state TEXT NOT NULL DEFAULT 'tentative',
                first_inferred_at REAL NOT NULL,
                last_validated_at REAL NOT NULL,
                target_entity_id TEXT NOT NULL DEFAULT '',
                target_entity_type TEXT NOT NULL DEFAULT '',
                target_scope TEXT NOT NULL DEFAULT 'global',
                temporal_scope TEXT NOT NULL DEFAULT 'session',
                decay_policy TEXT,
                decay_anchor_at REAL,
                context_ref_id TEXT NOT NULL DEFAULT '',
                expires_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(entity_id, entity_type, trait_name, target_entity_id)
            );
            """
        )
        await db.commit()

    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(db_path))
    await store.initialize()

    async with _aiosqlite.connect(db_path) as db:
        async with db.execute("PRAGMA table_info(tom_trait_assertions)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}

    assert "status" in columns
    assert "superseded_by" in columns
    assert "superseded_at" in columns
    assert "privacy_scope" in columns
