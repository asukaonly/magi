"""Unresolved query roles never broaden facts or borrow another entity's identity."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.l2_intent import enrich_l2_conditions
from magi.memory.hybrid_retrieval.l2_query_execution import _build_query_plan
from magi.memory.hybrid_retrieval.models import L2Conditions, L2SemanticFrame
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.store import L2CognitionStore


@pytest.fixture
async def role_store(tmp_path: Path) -> L2CognitionStore:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_unresolved_subject_does_not_retrieve_other_subject_facts(role_store):
    store = role_store
    now = time.time()
    await store.upsert_assertion_candidate({
        "entity_id": "user:unrelated",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.music",
        "trait_value": "爵士音乐",
        "natural_summary": "用户喜欢爵士音乐",
        "confidence_score": 0.9,
        "volatility_index": 0.1,
        "evidence_events": ["other-source"],
        "source_domain": "user_authored",
        "inference_depth": "semantic",
        "validation_state": "stable",
        "first_inferred_at": now - 100,
        "last_validated_at": now - 1,
        "temporal_scope": "persistent",
    })
    await store.upsert_knowledge_edge(
        subject_id="user:unrelated",
        subject_type="user",
        predicate="LIKES",
        object_id="concept:jazz",
        object_type="concept",
        evidence_event_ids=["other-source"],
        confidence=0.9,
        observed_at=now - 60,
        source_type="conversation",
        extraction_method="explicit",
    )
    conditions = L2Conditions(
        content_query="Alice 喜欢爵士音乐吗",
        semantic_frame=L2SemanticFrame(
            query_family="affinity",
            subject_scope="explicit",
            answer_kind="topic",
            subject_mentions=["Alice"],
        ),
        include_relationships=True,
        include_tom_snapshot=False,
    )

    result = await L2Handler(store).execute(conditions, user_id="u1")

    assert result["assertions"] == []
    assert result["relationships"] == []
    assert result["trace"]["grounding_plan"]["fact_abstention_reason"]


def test_partial_multi_subject_does_not_degrade_to_single_subject():
    conditions = L2Conditions(
        content_query="Alice 和 Bob 的共同偏好是什么",
        semantic_frame=L2SemanticFrame(
            query_family="affinity",
            subject_scope="multi",
            answer_kind="topic",
            subject_mode="multi",
            subject_mentions=["Alice", "Bob"],
        ),
    )
    enrich_l2_conditions(conditions)

    plan = build_grounding_plan(
        conditions,
        resolved_entities=[{
            "entity_id": "person:alice",
            "entity_type": "person",
            "canonical_name": "Alice",
        }],
        user_id="u1",
    )

    assert plan.subject_entity_ids == []
    assert plan.fact_abstention_reason


@pytest.mark.asyncio
async def test_vector_candidate_does_not_impersonate_exact_subject_mention(role_store, monkeypatch):
    catalog = L2EntityCatalog(db_path=role_store.db_path, vector_enabled=False)
    try:
        await catalog.upsert_entity(
            entity_id="person:ann", entity_type="person", canonical_name="Ann",
        )
        await catalog.upsert_entity(
            entity_id="person:annette", entity_type="person", canonical_name="Annette",
        )
        # Exercise the real catalog merge and resolver with a semantic candidate,
        # without loading an embedding model or making a model request.
        monkeypatch.setattr(catalog, "search_entities_semantic", AsyncMock(return_value=[{
            "entity_id": "person:annette",
            "entity_type": "person",
            "canonical_name": "Annette",
        }]))
        conditions = L2Conditions(
            content_query="Ann 的偏好",
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="explicit",
                answer_kind="topic",
                subject_mentions=["Ann"],
            ),
        )

        plan = await _build_query_plan(
            L2Handler(role_store, catalog), conditions, time_range=None, user_id="u1",
        )

        assert plan.subject_entity_ids == ["person:ann"]
        assert plan.fact_abstention_reason is None
    finally:
        await catalog.close()
