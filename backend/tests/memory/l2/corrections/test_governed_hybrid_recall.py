from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from _shared.context_scope import context_scope
from magi.memory.l2.retrieval import relationship_history
from magi.memory.l2.retrieval.common import bounded_scoped_candidate_limit
from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.graph_spreader import GraphSpreader
from magi.memory.hybrid_retrieval.governed_l2_recall import (
    GovernedL2RecallView,
    governed_temporal_bounds,
)
from magi.memory.hybrid_retrieval.mode_registry import MODE_REGISTRY
from magi.memory.hybrid_retrieval.models import (
    L2Conditions,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
    TimeRange,
)
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l2.corrections.models import (
    CorrectionKind,
    CorrectionTargetKind,
    NewMemoryCorrection,
)
from magi.memory.l2.corrections.repository import MemoryCorrectionRepository


async def _seed_location_assertion(
    store,
    *,
    value: str = "Hangzhou",
    scope: dict | None = None,
    evidence_event: str = "evt-assertion",
    entity_id: str = "user:u1",
    trait_name: str = "location.home",
    observed_at: float | None = None,
) -> str:  # type: ignore[no-untyped-def]
    inferred_at = observed_at if observed_at is not None else time.time() - 3600
    return await store.upsert_assertion_candidate(
        {
            "entity_id": entity_id,
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": trait_name,
            "trait_value": value,
            "confidence_score": 0.8,
            "evidence_events": [evidence_event],
            "volatility_index": 0.2,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": inferred_at,
            "last_validated_at": inferred_at,
            "temporal_scope": "persistent",
            "scope": dict(scope or {}),
        }
    )


async def _seed_location_relationship(
    store,
    *,
    object_id: str = "place:hangzhou",
    subject_id: str = "user:u1",
    predicate: str = "CURRENT_LIVES_IN",
    evidence_event: str = "evt-relationship",
) -> str:  # type: ignore[no-untyped-def]
    return await store.upsert_knowledge_edge(
        subject_id=subject_id,
        subject_type="user",
        predicate=predicate,
        object_id=object_id,
        object_type="place",
        evidence_event_ids=[evidence_event],
        confidence=0.9,
        observed_at=time.time() - 3600,
        source_type="conversation",
        extraction_method="explicit",
    )


def _assertion_conditions(*, context_scope: dict | None = None) -> L2Conditions:
    return L2Conditions(
        content_query="Where do I live?",
        subject_hint="self",
        context_scope=dict(context_scope or {}),
        include_tom_snapshot=False,
        include_relationships=False,
        include_assertions=True,
        limit=10,
    )


def test_governed_temporal_bounds_cover_current_past_range_and_future() -> None:
    now = 1_000.0

    current = governed_temporal_bounds(None, now=now)
    past = governed_temporal_bounds(TimeRange(as_of=900.0), now=now)
    historical_range = governed_temporal_bounds(
        TimeRange(start=800.0, end=900.0),
        now=now,
    )
    future = governed_temporal_bounds(TimeRange(start=1_100.0), now=now)

    assert (current.effective_at, current.effective_range, current.include_history) == (
        now,
        None,
        False,
    )
    assert (past.effective_at, past.effective_range, past.include_history) == (
        900.0,
        None,
        True,
    )
    assert (
        historical_range.effective_at,
        historical_range.effective_range,
        historical_range.include_history,
    ) == (900.0, (800.0, 900.0), True)
    assert (future.effective_at, future.effective_range, future.include_history) == (
        1_100.0,
        (1_100.0, None),
        True,
    )


def _relationship_conditions(*, context_scope: dict | None = None) -> L2Conditions:
    return L2Conditions(
        content_query="Where do I live?",
        subject_hint="self",
        predicates=["CURRENT_LIVES_IN"],
        predicate_family="profile_fact",
        context_scope=dict(context_scope or {}),
        include_tom_snapshot=False,
        include_relationships=True,
        include_assertions=False,
        limit=10,
    )


@pytest.mark.asyncio
async def test_hybrid_assertion_recall_respects_scheduled_change_and_as_of(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    assertion_id = await _seed_location_assertion(store)
    effective_at = time.time() + 600
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="hybrid-assertion-scheduled-change",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert corrected is not None
    handler = L2Handler(store)

    before = await handler.execute(_assertion_conditions(), user_id="u1")
    historical = await handler.execute(
        _assertion_conditions(),
        TimeRange(as_of=effective_at - 1),
        user_id="u1",
    )
    after = await handler.execute(
        _assertion_conditions(),
        TimeRange(as_of=effective_at + 1),
        user_id="u1",
    )
    spanning = await handler.execute(
        _assertion_conditions(),
        TimeRange(start=effective_at - 1, end=effective_at + 1),
        user_id="u1",
    )
    with patch("time.time", return_value=effective_at + 1):
        due_but_unprocessed = await handler.execute(
            _assertion_conditions(),
            user_id="u1",
        )

    assert [item["trait_value"] for item in before["assertions"]] == ["Hangzhou"]
    assert [item["trait_value"] for item in historical["assertions"]] == ["Hangzhou"]
    assert [item["trait_value"] for item in after["assertions"]] == ["Shanghai"]
    assert {item["trait_value"] for item in spanning["assertions"]} == {
        "Hangzhou",
        "Shanghai",
    }
    assert [item["trait_value"] for item in due_but_unprocessed["assertions"]] == ["Hangzhou"]


@pytest.mark.asyncio
async def test_hybrid_assertion_recall_requires_matching_scope(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_location_assertion(store, value="Shanghai")
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="hybrid-assertion-scope",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope=context_scope(project="magi"),
    )
    assert corrected is not None
    handler = L2Handler(store)

    global_result = await handler.execute(_assertion_conditions(), user_id="u1")
    mismatch = await handler.execute(
        _assertion_conditions(context_scope=context_scope(project="other")),
        user_id="u1",
    )
    matching = await handler.execute(
        _assertion_conditions(context_scope=context_scope(project="magi")),
        user_id="u1",
    )

    assert global_result["assertions"] == []
    assert mismatch["assertions"] == []
    assert [item["trait_value"] for item in matching["assertions"]] == ["Shanghai"]


@pytest.mark.asyncio
async def test_hybrid_assertion_recall_prefers_most_specific_matching_scope(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    await _seed_location_assertion(
        store,
        value="Global",
        evidence_event="evt-assertion-global",
    )
    await _seed_location_assertion(
        store,
        value="Project",
        scope=context_scope(project="magi"),
        evidence_event="evt-assertion-project",
    )
    await _seed_location_assertion(
        store,
        value="Activity",
        scope=context_scope(project="magi", activity="coding"),
        evidence_event="evt-assertion-activity",
    )
    handler = L2Handler(store)

    result = await handler.execute(
        _assertion_conditions(
            context_scope=context_scope(project="magi", activity="coding", place="home")
        ),
        user_id="u1",
    )
    spanning = await handler.execute(
        _assertion_conditions(
            context_scope=context_scope(project="magi", activity="coding", place="home")
        ),
        TimeRange(start=time.time() - 3500, end=time.time() + 1),
        user_id="u1",
    )

    assert [item["trait_value"] for item in result["assertions"]] == ["Activity"]
    assert [item["trait_value"] for item in spanning["assertions"]] == ["Activity"]


@pytest.mark.asyncio
async def test_scoped_assertion_masks_global_only_while_scope_is_valid(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    base = time.time() - 3600
    scoped_from = base + 1800
    await _seed_location_assertion(
        store,
        value="Global",
        evidence_event="evt-global-history",
        observed_at=base,
    )
    await _seed_location_assertion(
        store,
        value="Project",
        scope=context_scope(project="magi"),
        evidence_event="evt-project-history",
        observed_at=scoped_from,
    )
    handler = L2Handler(store)

    result = await handler.execute(
        _assertion_conditions(context_scope=context_scope(project="magi")),
        TimeRange(start=base, end=time.time()),
        user_id="u1",
    )

    assert {item["trait_value"] for item in result["assertions"]} == {
        "Global",
        "Project",
    }


@pytest.mark.asyncio
async def test_governed_batch_recall_preserves_each_entity_limit(l2_store_with_schema):
    store = l2_store_with_schema
    b_assertion = await _seed_location_assertion(
        store,
        entity_id="user:b",
        value="B",
        evidence_event="evt-b",
    )
    await _seed_location_assertion(
        store,
        entity_id="user:a",
        trait_name="preference.one",
        value="A1",
        evidence_event="evt-a1",
    )
    await _seed_location_assertion(
        store,
        entity_id="user:a",
        trait_name="preference.two",
        value="A2",
        evidence_event="evt-a2",
    )
    b_relationship = await _seed_location_relationship(
        store,
        subject_id="user:b",
        object_id="place:b",
        predicate="LIKES",
    )
    await _seed_location_relationship(
        store,
        subject_id="user:a",
        object_id="place:a1",
        predicate="LIKES",
    )
    await _seed_location_relationship(
        store,
        subject_id="user:a",
        object_id="place:a2",
        predicate="LIKES",
    )
    view = GovernedL2RecallView(
        store,
        context_scope=None,
        effective_at=time.time(),
    )

    assertions = await view.batch_list_tom_assertions(
        entity_ids=["user:a", "user:b"],
        limit_per_entity=1,
    )
    relationships = await view.batch_get_relationships(
        entity_ids=["user:a", "user:b"],
        direction="outgoing",
        predicates=["LIKES"],
        limit_per_entity=1,
    )

    assert len(assertions["user:a"]) == 1
    assert [item["assertion_id"] for item in assertions["user:b"]] == [b_assertion]
    assert len(relationships["user:a"]) == 1
    assert [item["triple_id"] for item in relationships["user:b"]] == [b_relationship]


@pytest.mark.asyncio
async def test_governed_batch_view_uses_batch_store_boundaries() -> None:
    store = SimpleNamespace(
        batch_list_current_assertions=AsyncMock(
            return_value={
                "user:a": [{"assertion_id": "assert-a"}],
                "user:b": [{"assertion_id": "assert-b"}],
            }
        ),
        batch_list_current_relationships=AsyncMock(
            return_value={
                "user:a": [{"triple_id": "rel-a"}],
                "user:b": [{"triple_id": "rel-b"}],
            }
        ),
        list_current_assertions=AsyncMock(),
        list_current_relationships=AsyncMock(),
    )
    view = GovernedL2RecallView(
        store,
        context_scope=context_scope(project="magi"),
        effective_at=123.0,
        effective_range=(100.0, 123.0),
        include_relationship_history=True,
    )

    assertions = await view.batch_list_tom_assertions(
        entity_ids=["user:a", "user:b", "user:a"],
        limit_per_entity=2,
    )
    relationships = await view.batch_get_relationships(
        entity_ids=["user:a", "user:b", "user:a"],
        direction="both",
        limit_per_entity=2,
    )

    assert list(assertions) == ["user:a", "user:b"]
    assert list(relationships) == ["user:a", "user:b"]
    store.batch_list_current_assertions.assert_awaited_once()
    store.batch_list_current_relationships.assert_awaited_once()
    store.list_current_assertions.assert_not_awaited()
    store.list_current_relationships.assert_not_awaited()
    assertion_call = store.batch_list_current_assertions.await_args.kwargs
    relationship_call = store.batch_list_current_relationships.await_args.kwargs
    assert assertion_call["entity_ids"] == ["user:a", "user:b"]
    assert assertion_call["effective_range"] == (100.0, 123.0)
    assert relationship_call["entity_ids"] == ["user:a", "user:b"]
    assert relationship_call["include_history"] is True


@pytest.mark.asyncio
async def test_governed_historical_batch_keeps_each_entity_candidate_window(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    for index in range(bounded_scoped_candidate_limit(1) + 2):
        await _seed_location_relationship(
            store,
            subject_id="user:a",
            object_id=f"place:a{index}",
            predicate="LIKES",
            evidence_event=f"evt-a{index}",
        )
    b_relationship = await _seed_location_relationship(
        store,
        subject_id="user:b",
        object_id="place:b",
        predicate="LIKES",
        evidence_event="evt-b",
    )
    view = GovernedL2RecallView(
        store,
        context_scope=None,
        effective_at=time.time(),
        include_relationship_history=True,
    )

    relationships = await view.batch_get_relationships(
        entity_ids=["user:a", "user:b"],
        direction="outgoing",
        predicates=["LIKES"],
        limit_per_entity=1,
    )

    assert len(relationships["user:a"]) == 1
    assert [item["triple_id"] for item in relationships["user:b"]] == [b_relationship]


@pytest.mark.asyncio
async def test_hybrid_relationship_recall_respects_scheduled_change_and_as_of(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    old_id = await _seed_location_relationship(store)
    effective_at = time.time() + 600
    corrected = await store.apply_relationship_correction(
        triple_id=old_id,
        request_id="hybrid-relationship-scheduled-change",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=effective_at,
    )
    assert corrected is not None
    handler = L2Handler(store)

    before = await handler.execute(_relationship_conditions(), user_id="u1")
    historical = await handler.execute(
        _relationship_conditions(),
        TimeRange(as_of=effective_at - 1),
        user_id="u1",
    )
    after = await handler.execute(
        _relationship_conditions(),
        TimeRange(as_of=effective_at + 1),
        user_id="u1",
    )
    spanning = await handler.execute(
        _relationship_conditions(),
        TimeRange(start=effective_at - 1, end=effective_at + 1),
        user_id="u1",
    )
    with patch("time.time", return_value=effective_at + 1):
        due_but_unprocessed = await handler.execute(
            _relationship_conditions(),
            user_id="u1",
        )

    assert [item["object_id"] for item in before["relationships"]] == ["place:hangzhou"]
    assert [item["object_id"] for item in historical["relationships"]] == ["place:hangzhou"]
    assert [item["object_id"] for item in after["relationships"]] == ["place:shanghai"]
    assert {item["object_id"] for item in spanning["relationships"]} == {
        "place:hangzhou",
        "place:shanghai",
    }
    assert [item["object_id"] for item in due_but_unprocessed["relationships"]] == [
        "place:hangzhou"
    ]


@pytest.mark.asyncio
async def test_chat_recall_keeps_governed_relationship_correction_without_l1_event(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    old_id = await _seed_location_relationship(store)
    corrected = await store.apply_relationship_correction(
        triple_id=old_id,
        request_id="chat-recall-evidence-free-correction",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
    )
    assert corrected is not None
    assert corrected["current_relationship"]["evidence_event_ids"] == []

    l1 = AsyncMock()
    l1.filter_ids_by_user.return_value = []
    handler = L2Handler(store, l1_store=l1)

    result = await handler.execute(_relationship_conditions(), user_id="u1")

    assert [item["object_id"] for item in result["relationships"]] == ["place:shanghai"]
    l1.filter_ids_by_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_future_start_only_range_recalls_scheduled_assertion_and_relationship(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    effective_at = time.time() + 600
    assertion_id = await _seed_location_assertion(store)
    await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-start-assertion",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    relationship_id = await _seed_location_relationship(store)
    await store.apply_relationship_correction(
        triple_id=relationship_id,
        request_id="future-start-relationship",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=effective_at,
    )
    handler = L2Handler(store)
    future_range = TimeRange(start=effective_at + 1)

    assertion_result = await handler.execute(
        _assertion_conditions(),
        future_range,
        user_id="u1",
    )
    relationship_result = await handler.execute(
        _relationship_conditions(),
        future_range,
        user_id="u1",
    )

    assert [item["trait_value"] for item in assertion_result["assertions"]] == ["Shanghai"]
    assert [item["object_id"] for item in relationship_result["relationships"]] == [
        "place:shanghai"
    ]


@pytest.mark.asyncio
async def test_hybrid_relationship_recall_requires_matching_scope(l2_store_with_schema):
    store = l2_store_with_schema
    triple_id = await _seed_location_relationship(store, object_id="place:shanghai")
    corrected = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="hybrid-relationship-scope",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope=context_scope(project="magi"),
    )
    assert corrected is not None
    handler = L2Handler(store)

    global_result = await handler.execute(_relationship_conditions(), user_id="u1")
    mismatch = await handler.execute(
        _relationship_conditions(context_scope=context_scope(project="other")),
        user_id="u1",
    )
    matching = await handler.execute(
        _relationship_conditions(context_scope=context_scope(project="magi")),
        user_id="u1",
    )

    assert global_result["relationships"] == []
    assert mismatch["relationships"] == []
    assert [item["object_id"] for item in matching["relationships"]] == ["place:shanghai"]


@pytest.mark.asyncio
async def test_fact_authoritative_l1_suppresses_all_correction_kinds(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    record_error_id = await _seed_location_assertion(
        store,
        value="Incorrect",
        trait_name="identity.record_error",
        evidence_event="evt-record-error",
    )
    changed_id = await _seed_location_assertion(
        store,
        value="Before",
        trait_name="identity.situation_changed",
        evidence_event="evt-situation-changed",
    )
    scoped_id = await _seed_location_relationship(
        store,
        object_id="topic:scoped",
        predicate="WORKS_ON",
        evidence_event="evt-scope-refinement",
    )
    await store.apply_assertion_correction(
        assertion_id=record_error_id,
        request_id="l1-filter-record-error",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )
    await store.apply_assertion_correction(
        assertion_id=changed_id,
        request_id="l1-filter-situation-changed",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="After",
        effective_at=time.time(),
    )
    await store.apply_relationship_correction(
        triple_id=scoped_id,
        request_id="l1-filter-scope-refinement",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope=context_scope(project="magi"),
    )
    memory = SimpleNamespace(
        l0=None,
        l1=None,
        l2=store,
        l2_entity_catalog=None,
        l3=None,
        l4=None,
    )
    service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    payload = RetrievalPayload(
        l1_events=[
            {"event_id": "evt-record-error", "content": "old record"},
            {"event_id": "evt-situation-changed", "content": "old state"},
            {"event_id": "evt-scope-refinement", "content": "unscoped claim"},
        ]
    )

    await service._apply_l1_correction_governance(
        payload,
        mode_plan=MODE_REGISTRY["exact_fact"],
        host=service,
    )

    assert payload.l1_events == []
    assert payload.trace["l1_correction_governance"] == "applied"
    assert payload.trace["l1_correction_governance_granularity"] == "event"
    assert payload.trace["l1_correction_governance_dropped_count"] == 3

    cross_session_payload = RetrievalPayload(
        l1_events=[
            {"event_id": "evt-record-error", "content": "old record"},
            {"event_id": "evt-situation-changed", "content": "old state"},
            {"event_id": "evt-scope-refinement", "content": "unscoped claim"},
        ]
    )
    await service._apply_l1_correction_governance(
        cross_session_payload,
        mode_plan=MODE_REGISTRY["cross_session"],
        host=service,
    )
    assert cross_session_payload.l1_events == []


@pytest.mark.asyncio
async def test_real_service_hides_corrected_event_from_fact_but_keeps_history(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    event_id = "evt-old-home"
    triple_id = await _seed_location_relationship(
        store,
        evidence_event=event_id,
    )
    await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="service-record-error",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )
    event = {
        "event_id": event_id,
        "content": "I live in Hangzhou.",
        "timestamp": time.time() - 3600,
        "user_id": "u1",
        "l1_retrieval_scope": "fact_authoritative",
        "evidence_class": "user_statement",
        "score": 1.0,
    }
    l1 = AsyncMock()
    l1.db_path = store.db_path
    l1.bm25_search.return_value = [(event_id, -1.0)]
    l1.vector_search.return_value = []
    l1.query_events.return_value = [event]
    l1.fetch_events.return_value = [event]
    l1.resolve_event_entities.return_value = []
    l1.find_events_by_entities.return_value = []
    l1.expand_by_entities.return_value = []
    l1.filter_ids_by_user.return_value = [event_id]
    memory = SimpleNamespace(
        l0=None,
        l1=l1,
        l2=store,
        l2_entity_catalog=None,
        l3=None,
        l4=None,
    )
    service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )

    fact_result = await service.query(
        RetrievalQuery(
            query="Hangzhou",
            user_id="u1",
            query_mode="exact_fact",
        )
    )
    history_result = await service.query(
        RetrievalQuery(
            query="Hangzhou",
            user_id="u1",
            query_mode="event_stream",
        )
    )
    episode_result = await service.query(
        RetrievalQuery(
            query="Hangzhou",
            user_id="u1",
            query_mode="episode_recall",
        )
    )

    assert fact_result.l1_events == []
    assert fact_result.l2_relationships == []
    assert fact_result.trace["l1_correction_governance"] == "applied"
    assert fact_result.trace["l1_correction_governance_dropped_count"] == 1
    assert [item["event_id"] for item in history_result.l1_events] == [event_id]
    assert history_result.l1_events[0]["evidence_semantics"] == "historical_record"
    assert history_result.l1_events[0]["correction_status"] == "later_corrected"
    assert history_result.trace["l1_historical_corrected_event_count"] == 1
    assert [item["event_id"] for item in episode_result.l1_events] == [event_id]
    assert episode_result.l1_events[0]["evidence_semantics"] == "historical_record"
    assert episode_result.l1_events[0]["correction_status"] == "later_corrected"


@pytest.mark.asyncio
async def test_shared_evidence_event_stays_blocked_until_every_correction_is_reverted(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    first_id = await _seed_location_assertion(
        store,
        value="First",
        trait_name="shared_event.first",
        evidence_event="evt-shared",
    )
    second_id = await _seed_location_assertion(
        store,
        value="Second",
        trait_name="shared_event.second",
        evidence_event="evt-shared",
    )
    first = await store.apply_assertion_correction(
        assertion_id=first_id,
        request_id="shared-event-first",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )
    second = await store.apply_assertion_correction(
        assertion_id=second_id,
        request_id="shared-event-second",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )
    assert first is not None and second is not None

    assert await store.active_correction_evidence_event_ids(["evt-shared"]) == {"evt-shared"}
    await store.revert_assertion_correction(
        correction_id=first["correction"]["correction_id"],
        request_id="shared-event-revert-first",
        actor_id="user:u1",
    )
    assert await store.active_correction_evidence_event_ids(["evt-shared"]) == {"evt-shared"}
    await store.revert_assertion_correction(
        correction_id=second["correction"]["correction_id"],
        request_id="shared-event-revert-second",
        actor_id="user:u1",
    )
    assert await store.active_correction_evidence_event_ids(["evt-shared"]) == set()


@pytest.mark.asyncio
async def test_reverting_latest_replacement_restores_only_its_evidence_event(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    original_id = await _seed_location_assertion(
        store,
        value="Hangzhou",
        trait_name="replacement_chain.location",
        evidence_event="evt-original",
    )
    first = await store.apply_assertion_correction(
        assertion_id=original_id,
        request_id="replacement-chain-first",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=time.time(),
        source_event_id="evt-replacement-first",
    )
    assert first is not None and first["current_assertion"] is not None
    second = await store.apply_assertion_correction(
        assertion_id=first["current_assertion"]["assertion_id"],
        request_id="replacement-chain-second",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Beijing",
        effective_at=time.time(),
        source_event_id="evt-replacement-second",
    )
    assert second is not None

    candidates = ["evt-original", "evt-replacement-first"]
    assert await store.active_correction_evidence_event_ids(candidates) == set(candidates)
    await store.revert_assertion_correction(
        correction_id=second["correction"]["correction_id"],
        request_id="replacement-chain-revert-second",
        actor_id="user:u1",
    )

    assert await store.active_correction_evidence_event_ids(candidates) == {"evt-original"}


@pytest.mark.asyncio
async def test_new_correction_evidence_parser_accepts_two_nested_json_layers(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    await MemoryCorrectionRepository(store.db_path).create(
        NewMemoryCorrection(
            correction_id="correction-nested-evidence",
            request_id="request-nested-evidence",
            actor_id="user:u1",
            target_kind=CorrectionTargetKind.ASSERTION,
            target_id="assert-nested",
            slot_key="slot-nested",
            claim_fingerprint="claim-nested",
            correction_kind=CorrectionKind.RECORD_ERROR,
            before={"evidence_events": json.dumps(json.dumps(["evt-nested"]))},
            request_fingerprint="fingerprint-nested-evidence",
            created_at=now,
        )
    )

    assert await store.active_correction_evidence_event_ids(["evt-nested", "evt-unrelated"]) == {
        "evt-nested"
    }


@pytest.mark.asyncio
async def test_literal_star_evidence_id_does_not_govern_unrelated_events(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    await MemoryCorrectionRepository(store.db_path).create(
        NewMemoryCorrection(
            correction_id="correction-literal-star-evidence",
            request_id="request-literal-star-evidence",
            actor_id="user:u1",
            target_kind=CorrectionTargetKind.ASSERTION,
            target_id="assert-literal-star",
            slot_key="slot-literal-star",
            claim_fingerprint="claim-literal-star",
            correction_kind=CorrectionKind.RECORD_ERROR,
            before={"evidence_events": ["*"]},
            request_fingerprint="fingerprint-literal-star",
            created_at=now,
        )
    )

    assert await store.active_correction_evidence_event_ids(["*", "evt-unrelated"]) == {"*"}


@pytest.mark.asyncio
async def test_new_correction_evidence_parser_fails_closed_on_nonstring_item(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    await MemoryCorrectionRepository(store.db_path).create(
        NewMemoryCorrection(
            correction_id="correction-invalid-item",
            request_id="request-invalid-item",
            actor_id="user:u1",
            target_kind=CorrectionTargetKind.ASSERTION,
            target_id="assert-invalid-item",
            slot_key="slot-invalid-item",
            claim_fingerprint="claim-invalid-item",
            correction_kind=CorrectionKind.RECORD_ERROR,
            before={"evidence_events": ["evt-valid", {"event_id": "evt-invalid"}]},
            request_fingerprint="fingerprint-invalid-item",
            created_at=now,
        )
    )

    assert await store.active_correction_evidence_event_ids(["candidate-a", "candidate-b"]) == {
        "candidate-a",
        "candidate-b",
    }


@pytest.mark.asyncio
async def test_correction_evidence_lookup_handles_large_structured_recall_batch(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    assertion_id = await _seed_location_assertion(
        store,
        trait_name="large_batch.location",
        evidence_event="evt-1200",
    )
    await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="large-batch-correction",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )

    candidates = [f"evt-{index}" for index in range(2_000)]
    assert await store.active_correction_evidence_event_ids(candidates) == {"evt-1200"}


@pytest.mark.asyncio
async def test_graph_spread_respects_future_relationship_change(l2_store_with_schema):
    store = l2_store_with_schema
    now = time.time()
    old_id = await _seed_location_relationship(store)
    effective_at = now + 600
    await store.apply_relationship_correction(
        triple_id=old_id,
        request_id="spread-future-city",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=effective_at,
        source_event_id="evt-new-city",
    )
    spreader = GraphSpreader(store, max_hops=1)

    current = await spreader.spread(["user:u1"])
    future = await spreader.spread(
        ["user:u1"],
        temporal_bounds=governed_temporal_bounds(TimeRange(as_of=effective_at + 1)),
    )

    assert "place:hangzhou" in current.discovered_entities
    assert "place:shanghai" not in current.discovered_entities
    assert "evt-relationship" in current.scored_event_ids
    assert "place:shanghai" in future.discovered_entities
    assert "place:hangzhou" not in future.discovered_entities
    assert "evt-new-city" in future.scored_event_ids


@pytest.mark.asyncio
async def test_graph_spread_keeps_scoped_relationship_out_of_global_query(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _seed_location_relationship(store, object_id="place:shanghai")
    await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="spread-scoped-city",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope=context_scope(project="magi"),
    )
    spreader = GraphSpreader(store, max_hops=1)

    global_result = await spreader.spread(["user:u1"])
    scoped_result = await spreader.spread(
        ["user:u1"],
        context_scope=context_scope(project="magi", activity="coding"),
    )

    assert "place:shanghai" not in global_result.discovered_entities
    assert "place:shanghai" in scoped_result.discovered_entities


@pytest.mark.asyncio
async def test_edge_vector_overfetch_fills_limit_after_governance(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()

    async def seed(object_id: str, *, scope=None, valid_from=None):  # type: ignore[no-untyped-def]
        return await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="user",
            predicate="LIKES",
            object_id=object_id,
            object_type="topic",
            evidence_event_ids=[f"evt-{object_id}"],
            confidence=0.8,
            observed_at=now - 60,
            valid_from=valid_from,
            source_type="conversation",
            extraction_method="explicit",
            scope=scope,
        )

    scoped_id = await seed("topic:scoped", scope=context_scope(project="magi"))
    future_id = await seed("topic:future", valid_from=now + 3600)
    rejected_id = await seed("topic:rejected")
    await store.reject_edge(triple_id=rejected_id)
    global_id = await seed("topic:global")
    raw_candidates = [
        await store.get_relationship(triple_id=triple_id)
        for triple_id in (scoped_id, future_id, rejected_id, global_id)
    ]
    store.search_edges_by_embedding = AsyncMock(return_value=raw_candidates)
    view = GovernedL2RecallView(
        store,
        context_scope=None,
        effective_at=now,
    )

    results = await view.search_edges_by_embedding(
        vector_index=object(),
        embedding=[0.1, 0.2],
        limit=1,
    )

    assert [item["triple_id"] for item in results] == [global_id]
    requested_candidates = store.search_edges_by_embedding.call_args.kwargs["limit"]
    assert requested_candidates >= 4
    assert requested_candidates <= 256


@pytest.mark.asyncio
async def test_edge_vector_overfetch_grows_within_cap_when_first_window_is_filtered(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    scoped_ids = []
    for index in range(12):
        scoped_ids.append(
            await store.upsert_knowledge_edge(
                subject_id="user:u1",
                subject_type="user",
                predicate="LIKES",
                object_id=f"topic:scoped-{index}",
                object_type="topic",
                evidence_event_ids=[f"evt-scoped-{index}"],
                confidence=0.8,
                observed_at=now - 60,
                source_type="conversation",
                extraction_method="explicit",
                scope=context_scope(project="magi"),
            )
        )
    global_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="topic:global-after-window",
        object_type="topic",
        evidence_event_ids=["evt-global-after-window"],
        confidence=0.8,
        observed_at=now - 60,
        source_type="conversation",
        extraction_method="explicit",
    )
    raw_candidates = [
        await store.get_relationship(triple_id=triple_id) for triple_id in [*scoped_ids, global_id]
    ]

    async def vector_search(**kwargs):  # type: ignore[no-untyped-def]
        return raw_candidates[: int(kwargs["limit"])]

    store.search_edges_by_embedding = AsyncMock(side_effect=vector_search)
    view = GovernedL2RecallView(store, context_scope=None, effective_at=now)

    results = await view.search_edges_by_embedding(
        vector_index=object(),
        embedding=[0.1, 0.2],
        limit=1,
    )

    assert [item["triple_id"] for item in results] == [global_id]
    requested_limits = [
        int(call.kwargs["limit"]) for call in store.search_edges_by_embedding.call_args_list
    ]
    assert requested_limits == [9, 18]
    assert max(requested_limits) <= 256


@pytest.mark.asyncio
async def test_scoped_reads_stay_bounded_without_losing_specific_winner(
    l2_store_with_schema,
    monkeypatch,
):
    store = l2_store_with_schema
    await _seed_location_assertion(
        store,
        value="Scoped winner",
        scope=context_scope(project="magi"),
        evidence_event="evt-scoped-winner",
    )
    scoped_edge_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="topic:scoped-winner",
        object_type="topic",
        evidence_event_ids=["evt-scoped-edge-winner"],
        confidence=0.8,
        observed_at=time.time() - 120,
        source_type="conversation",
        extraction_method="explicit",
        scope=context_scope(project="magi"),
    )
    for index in range(48):
        observed_at = time.time()
        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": f"noise.{index}",
                "trait_value": f"noise-{index}",
                "confidence_score": 0.8,
                "evidence_events": [f"evt-noise-{index}"],
                "volatility_index": 0.2,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "validation_state": "stable",
                "first_inferred_at": observed_at,
                "last_validated_at": observed_at,
                "temporal_scope": "persistent",
            }
        )
        await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="user",
            predicate="LIKES",
            object_id=f"topic:noise-{index}",
            object_type="topic",
            evidence_event_ids=[f"evt-edge-noise-{index}"],
            confidence=0.8,
            observed_at=observed_at,
            source_type="conversation",
            extraction_method="explicit",
        )

    query_context_scope = context_scope(
        project="magi",
        activity="coding",
        place="home",
        person="alice",
        time="day",
    )
    loaded_candidate_counts: list[int] = []
    original_materializer = relationship_history._materialize_relationship_states

    def capture_loaded_snapshots(snapshots):  # type: ignore[no-untyped-def]
        loaded_candidate_counts.append(
            len({str(item.get("triple_id") or "") for item in snapshots})
        )
        return original_materializer(snapshots)

    monkeypatch.setattr(
        relationship_history,
        "_materialize_relationship_states",
        capture_loaded_snapshots,
    )
    assertions = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=query_context_scope,
        limit=1,
    )
    relationships = await store.list_current_relationships(
        context_scope=query_context_scope,
        effective_at=time.time(),
        limit=1,
    )

    assert [item["trait_value"] for item in assertions] == ["Scoped winner"]
    assert [item["triple_id"] for item in relationships] == [scoped_edge_id]
    assert loaded_candidate_counts == [bounded_scoped_candidate_limit(1)]


@pytest.mark.asyncio
async def test_memory_query_tool_passes_trusted_workspace_through_real_hybrid_recall(
    l2_store_with_schema,
    tmp_path,
):
    """The chat-facing tool must reach scoped claims through the real service."""
    from types import SimpleNamespace

    from magi.core.workspace import WorkspacePaths, WorkspaceStateStore
    from magi.memory.hybrid_retrieval import build_query
    from magi.memory.hybrid_retrieval.models import ConversationTurn, RetrievalConfig
    from magi.memory.hybrid_retrieval.service import HybridRetrievalService
    from magi.memory.context_scope import context_id_for_workspace
    from magi.memory.retrieval_projection import project_historical_recall
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.tools.schema import ToolExecutionContext
    from magi_plugin_sdk.capabilities import ToolCapabilities

    store = l2_store_with_schema
    magi_workspace = tmp_path / "Magi"
    other_workspace = tmp_path / "Other"
    magi_workspace.mkdir()
    other_workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(magi_workspace)).claim_identity()
    WorkspaceStateStore(WorkspacePaths.from_root(other_workspace)).claim_identity()
    magi_scope = {
        "all_of": [
            {
                "dimension": "project",
                "context_id": context_id_for_workspace(str(magi_workspace)),
            }
        ]
    }
    assertion_id = await _seed_location_assertion(store, value="Shanghai")
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="tool-hybrid-scope",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope=magi_scope,
    )
    assert corrected is not None

    memory = SimpleNamespace(
        l0=None,
        l1=None,
        l2=store,
        l2_entity_catalog=None,
        l3=None,
        l4=None,
        memory_db_path=store.db_path,
    )
    service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )

    class _MemoryQueryPort:
        memory_db_path = store.db_path

        @staticmethod
        def build_query(**kwargs):  # type: ignore[no-untyped-def]
            return build_query(**kwargs)

        @staticmethod
        def make_conversation_turn(**kwargs):  # type: ignore[no-untyped-def]
            return ConversationTurn(**kwargs)

        @staticmethod
        def project_historical_recall(**kwargs):  # type: ignore[no-untyped-def]
            return project_historical_recall(**kwargs)

        @staticmethod
        async def get_canonical_names(_entity_ids):  # type: ignore[no-untyped-def]
            return {}

        @staticmethod
        async def query(request):  # type: ignore[no-untyped-def]
            return await service.query(request)

    tool = MemoryQueryTool()
    hidden_context = ToolExecutionContext(
        agent_id="agent-1",
        capabilities=ToolCapabilities(memory_query=_MemoryQueryPort()),
        workspace=str(other_workspace),
        env_vars={
            "user_id": "u1",
            "memory_context_workspace": str(other_workspace),
        },
    )
    visible_context = hidden_context.model_copy(
        update={
            "workspace": str(magi_workspace),
            "env_vars": {
                "user_id": "u1",
                "memory_context_workspace": str(magi_workspace),
            },
        }
    )

    hidden = await tool.execute(
        {"query": "Where do I live?", "query_mode": "exact_fact"},
        hidden_context,
    )
    visible = await tool.execute(
        {
            "query": "Where do I live in the Magi project?",
            "query_mode": "exact_fact",
        },
        visible_context,
    )

    assert hidden.success is True
    assert hidden.data["historical_recall"]["status"] == "not_found"
    assert visible.success is True
    assert visible.data["historical_recall"]["status"] == "found"
    assert any(
        "Shanghai" in finding["statement"]
        for finding in visible.data["historical_recall"]["findings"]
    )
