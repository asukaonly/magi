from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


async def _build_user_message(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "message": text},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


async def _build_group_timeline_message(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type="TIMELINE_EVENT",
            data={"title": "Group chat", "summary": text},
            source="group_chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"timeline": {"source_type": "group_chat"}, "user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


async def _build_contradiction(text: str, *, correlation_id: str, timestamp: float):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "message": text},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=correlation_id,
            metadata={"user_id": "u1"},
            timestamp=timestamp,
        ),
        event_id=correlation_id,
    )


@pytest.mark.asyncio
async def test_tom_assertion_starts_tentative_with_low_confidence(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    event = await _build_user_message(
        "I have been really stressed about work lately.",
        correlation_id="evt-1",
        timestamp=1710000000.0,
    )
    result = await store.apply_memory_event(event)

    assertions = await store.list_tom_assertions(entity_id="user:self")

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
        await store.apply_memory_event(event)

    assertions = await store.list_tom_assertions(entity_id="user:self")
    snapshot = await store.get_tom_snapshot(entity_id="user:self", entity_type="user")

    assert assertions[0]["validation_state"] == "stable"
    assert assertions[0]["confidence_score"] >= 0.8
    assert snapshot is not None
    assert snapshot["core_traits"]["stress_level"] == "high"


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
        await store.apply_memory_event(
            await _build_user_message(text, correlation_id=correlation_id, timestamp=timestamp)
        )

    await store.apply_memory_event(
        await _build_contradiction(
            "I actually feel calm and relaxed about work now.",
            correlation_id="evt-4",
            timestamp=1710275000.0,
        )
    )

    assertions = await store.list_tom_assertions(entity_id="user:self")

    assert assertions[0]["validation_state"] == "contradicted"
    assert assertions[0]["confidence_score"] < 0.8


@pytest.mark.asyncio
async def test_group_content_avoids_deep_psychology(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.apply_memory_event(
        await _build_group_timeline_message(
            "The group felt tense and Alice openly praised Bob.",
            correlation_id="evt-1",
            timestamp=1710000000.0,
        )
    )

    assertions = await store.list_tom_assertions(entity_id="user:self")

    assert assertions == []


@pytest.mark.asyncio
async def test_preference_reversal_deprecates_opposite_graph_edge(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:self",
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
        subject_id="user:self",
        subject_type="user",
        predicate="DISLIKES",
        object_id="food:sushi",
        object_type="food",
        evidence_event_ids=["evt-dislike-1"],
        confidence=0.86,
        observed_at=1710090000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:self", limit=10)

    assert len(active_edges) == 1
    assert active_edges[0]["predicate"] == "DISLIKES"

    deprecated_like_edges = await store.get_relationships(subject_id="user:self", limit=10, status="deprecated")
    assert len(deprecated_like_edges) == 1
    assert deprecated_like_edges[0]["predicate"] == "LIKES"
    assert deprecated_like_edges[0]["deprecated_by"] == active_edges[0]["triple_id"]


@pytest.mark.asyncio
async def test_upsert_knowledge_edge_normalizes_alias_object_type(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="DISLIKES",
        object_id="dish:west-lake-vinegar-fish",
        object_type="dish",
        evidence_event_ids=["evt-food-1"],
        confidence=0.85,
        observed_at=1710000000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:self", limit=10)

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
        subject_id="user:self",
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
        subject_id="user:self",
        subject_type="user",
        predicate="REJECTS",
        object_id="topic:remote-work",
        object_type="topic",
        evidence_event_ids=["evt-reject-1"],
        confidence=0.78,
        observed_at=1710090000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:self", limit=10)
    conflicted_edges = await store.get_relationships(subject_id="user:self", limit=10, status="conflicted")

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
        subject_id="user:self",
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
        subject_id="user:self",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:tokyo",
        object_type="place",
        evidence_event_ids=["evt-home-2"],
        confidence=0.91,
        observed_at=1710090000.0,
        source_type="chat",
    )

    active_edges = await store.get_relationships(subject_id="user:self", limit=10)
    deprecated_edges = await store.get_relationships(subject_id="user:self", limit=10, status="deprecated")

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
        subject_id="user:self",
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
        subject_id="user:self",
        subject_type="user",
        predicate="REJECTS",
        object_id="topic:hybrid-work",
        object_type="topic",
        evidence_event_ids=["evt-2"],
        confidence=0.72,
        observed_at=1710090000.0,
        source_type="chat",
    )

    conflicted_edges = await store.get_relationships(subject_id="user:self", limit=10, status="conflicted")

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
