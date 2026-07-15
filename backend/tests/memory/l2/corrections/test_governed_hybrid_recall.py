from __future__ import annotations

import time

import pytest

from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.governed_l2_recall import GovernedL2RecallView
from magi.memory.hybrid_retrieval.models import L2Conditions, TimeRange
from magi.memory.l2.corrections.models import CorrectionKind


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
) -> str:  # type: ignore[no-untyped-def]
    return await store.upsert_knowledge_edge(
        subject_id=subject_id,
        subject_type="user",
        predicate=predicate,
        object_id=object_id,
        object_type="place",
        evidence_event_ids=["evt-relationship"],
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

    assert [item["trait_value"] for item in before["assertions"]] == ["Hangzhou"]
    assert [item["trait_value"] for item in historical["assertions"]] == ["Hangzhou"]
    assert [item["trait_value"] for item in after["assertions"]] == ["Shanghai"]
    assert {item["trait_value"] for item in spanning["assertions"]} == {
        "Hangzhou",
        "Shanghai",
    }


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
        scope={"project": "magi"},
    )
    assert corrected is not None
    handler = L2Handler(store)

    global_result = await handler.execute(_assertion_conditions(), user_id="u1")
    mismatch = await handler.execute(
        _assertion_conditions(context_scope={"project": "other"}),
        user_id="u1",
    )
    matching = await handler.execute(
        _assertion_conditions(context_scope={"project": "magi"}),
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
        scope={"project": "magi"},
        evidence_event="evt-assertion-project",
    )
    await _seed_location_assertion(
        store,
        value="Activity",
        scope={"project": "magi", "activity": "coding"},
        evidence_event="evt-assertion-activity",
    )
    handler = L2Handler(store)

    result = await handler.execute(
        _assertion_conditions(
            context_scope={"project": "magi", "activity": "coding", "place": "home"}
        ),
        user_id="u1",
    )
    spanning = await handler.execute(
        _assertion_conditions(
            context_scope={"project": "magi", "activity": "coding", "place": "home"}
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
        scope={"project": "magi"},
        evidence_event="evt-project-history",
        observed_at=scoped_from,
    )
    handler = L2Handler(store)

    result = await handler.execute(
        _assertion_conditions(context_scope={"project": "magi"}),
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
    assert [item["triple_id"] for item in relationships["user:b"]] == [
        b_relationship
    ]


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

    assert [item["object_id"] for item in before["relationships"]] == ["place:hangzhou"]
    assert [item["object_id"] for item in historical["relationships"]] == [
        "place:hangzhou"
    ]
    assert [item["object_id"] for item in after["relationships"]] == ["place:shanghai"]
    assert {item["object_id"] for item in spanning["relationships"]} == {
        "place:hangzhou",
        "place:shanghai",
    }


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
        scope={"project": "magi"},
    )
    assert corrected is not None
    handler = L2Handler(store)

    global_result = await handler.execute(_relationship_conditions(), user_id="u1")
    mismatch = await handler.execute(
        _relationship_conditions(context_scope={"project": "other"}),
        user_id="u1",
    )
    matching = await handler.execute(
        _relationship_conditions(context_scope={"project": "magi"}),
        user_id="u1",
    )

    assert global_result["relationships"] == []
    assert mismatch["relationships"] == []
    assert [item["object_id"] for item in matching["relationships"]] == [
        "place:shanghai"
    ]


@pytest.mark.asyncio
async def test_memory_query_tool_passes_superset_scope_through_real_hybrid_recall(
    l2_store_with_schema,
):
    """The chat-facing tool must reach scoped claims through the real service."""
    from types import SimpleNamespace

    from magi.memory.hybrid_retrieval import build_query
    from magi.memory.hybrid_retrieval.models import ConversationTurn, RetrievalConfig
    from magi.memory.hybrid_retrieval.service import HybridRetrievalService
    from magi.memory.retrieval_projection import project_historical_recall
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.tools.schema import ToolExecutionContext
    from magi_plugin_sdk.capabilities import ToolCapabilities

    store = l2_store_with_schema
    assertion_id = await _seed_location_assertion(store, value="Shanghai")
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="tool-hybrid-scope",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope={"project": "magi"},
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
        async def get_canonical_names(_db_path, _entity_ids):  # type: ignore[no-untyped-def]
            return {}

        @staticmethod
        async def query(request):  # type: ignore[no-untyped-def]
            return await service.query(request)

    tool = MemoryQueryTool()
    context = ToolExecutionContext(
        agent_id="agent-1",
        capabilities=ToolCapabilities(memory_query=_MemoryQueryPort()),
        env_vars={"user_id": "u1"},
    )

    hidden = await tool.execute(
        {"query": "Where do I live?", "query_mode": "exact_fact"},
        context,
    )
    visible = await tool.execute(
        {
            "query": "Where do I live in the Magi project?",
            "query_mode": "exact_fact",
            "context_scope": {"project": "magi", "activity": "coding"},
        },
        context,
    )

    assert hidden.success is True
    assert hidden.data["historical_recall"]["status"] == "not_found"
    assert visible.success is True
    assert visible.data["historical_recall"]["status"] == "found"
    assert any(
        "Shanghai" in finding["statement"]
        for finding in visible.data["historical_recall"]["findings"]
    )
