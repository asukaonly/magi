"""Typed fact-slot retrieval must not require the question to contain its answer."""

from __future__ import annotations

import json

import pytest

from magi.memory.hybrid_retrieval import HybridRetrievalService, build_query
from magi.memory.hybrid_retrieval.assertion_query import parse_assertion_query
from magi.memory.hybrid_retrieval.assertion_relevance import rank_assertions
from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
from magi.memory.hybrid_retrieval.l2_intent import _parse_semantic_frame
from magi.memory.hybrid_retrieval.models import (
    AssertionQuery,
    L2Conditions,
    L2SemanticFrame,
    RetrievalConfig,
    SemanticConstraint,
)
from magi.memory.l2.corrections.models import CorrectionKind
from memory.l2.test_claim_text_pipeline import _ingest, _open_store, _response


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        [],
        {"predicates": [], "value_scope": "any"},
        {"predicates": ["REAL_NAME", "INVENTED"], "value_scope": "any"},
        {"predicates": ["REAL_NAME"], "value_scope": []},
        {"predicates": "REAL_NAME", "value_scope": "any"},
    ],
)
def test_invalid_slot_selection_never_becomes_unrestricted_query(raw):
    assert parse_assertion_query(raw) is None


@pytest.mark.parametrize(
    "query", ["", "我叫什么名字？", "What is my name?", "私の名前は何ですか？"]
)
@pytest.mark.asyncio
async def test_named_slot_retrieves_unknown_answer_without_unrelated_profile_facts(query):
    rows = await rank_assertions(
        [
            {"assertion_id": "name", "trait_name": "identity.real_name", "trait_value": "明日香"},
            {
                "assertion_id": "birth",
                "trait_name": "identity.birth_date",
                "trait_value": "1990-01-01",
            },
            {
                "assertion_id": "food",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target": "火锅",
            },
        ],
        query=query,
        limit=10,
        config=RetrievalConfig(),
        trace={},
        assertion_query=AssertionQuery(predicates=["REAL_NAME"], value_scope="any"),
    )
    assert [row["assertion_id"] for row in rows] == ["name"]


@pytest.mark.asyncio
async def test_preference_slot_distinguishes_like_dislike_and_unresolved_target():
    rows = await rank_assertions(
        [
            {
                "assertion_id": "like",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target": "爵士乐",
            },
            {
                "assertion_id": "dislike",
                "trait_name": "preference.affinity",
                "trait_value": "dislike",
                "target": "火锅",
            },
            {
                "assertion_id": "missing",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target_entity_id": "opaque",
            },
        ],
        query="我喜欢什么？",
        limit=10,
        config=RetrievalConfig(),
        trace={},
        assertion_query=AssertionQuery(predicates=["LIKES"], value_scope="any"),
    )
    assert [row["assertion_id"] for row in rows] == ["like"]


@pytest.mark.asyncio
async def test_category_restriction_does_not_accept_every_matching_preference_slot():
    rows = await rank_assertions(
        [
            {
                "assertion_id": "food",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target": "火锅",
            },
        ],
        query="我喜欢什么音乐？",
        limit=10,
        config=RetrievalConfig(),
        trace={},
        assertion_query=AssertionQuery(predicates=["LIKES"], value_scope="constrained"),
    )
    assert rows == []


@pytest.mark.asyncio
async def test_typed_slot_top_k_uses_recency_without_changing_slot_membership():
    rows = await rank_assertions(
        [
            {
                "assertion_id": "old",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target": "爵士乐",
                "updated_at": 10,
            },
            {
                "assertion_id": "new",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target": "钢琴曲",
                "updated_at": 20,
            },
            {
                "assertion_id": "newest-dislike",
                "trait_name": "preference.affinity",
                "trait_value": "dislike",
                "target": "火锅",
                "updated_at": 30,
            },
        ],
        query="我喜欢什么？",
        limit=1,
        config=RetrievalConfig(),
        trace={},
        assertion_query=AssertionQuery(predicates=["LIKES"], value_scope="any"),
    )
    assert [row["assertion_id"] for row in rows] == ["new"]


@pytest.mark.asyncio
async def test_constrained_slot_cannot_widen_when_rewritten_query_is_missing():
    rows = await rank_assertions(
        [
            {
                "assertion_id": "food",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "target": "火锅",
            },
        ],
        query="",
        limit=10,
        config=RetrievalConfig(),
        trace={},
        assertion_query=AssertionQuery(predicates=["LIKES"], value_scope="constrained"),
    )
    assert rows == []


@pytest.mark.parametrize(
    "restriction",
    [
        {"object_mentions": ["火锅"]},
        {"constraints": [SemanticConstraint(scope="target", facet="category", raw_value="音乐")]},
    ],
)
def test_structural_restrictions_override_unrestricted_slot_judgment(restriction):
    frame = L2SemanticFrame(
        query_family="affinity",
        subject_scope="self",
        answer_kind="unknown",
        assertion_query=AssertionQuery(predicates=["LIKES"], value_scope="any"),
        **restriction,
    )
    plan = build_grounding_plan(
        L2Conditions(content_query="query", semantic_frame=frame),
        resolved_entities=[],
        user_id="u1",
    )
    assert plan.assertion_query.value_scope == "constrained"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query", ["我的名字是什么？", "What is my real name?", "私の名前を覚えていますか？"]
)
async def test_public_recall_returns_corrected_name_through_typed_intent(tmp_path, query):
    response = _response(
        event_id="name-source",
        object_ref="明日香",
        evidence="我叫明日香",
        entities=[],
        predicate="REAL_NAME",
        object_type="person",
        fact_kind="explicit_fact",
    )
    store, _ = await _open_store(tmp_path, response)
    try:
        await _ingest(store, event_id="name-source", content="我叫明日香")
        current = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        await store.l2.apply_assertion_correction(
            assertion_id=current["assertion_id"],
            request_id="correct-name",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="新名字",
        )

        class IntentBridge:
            async def chat(self, **kwargs):
                assert "REAL_NAME" in kwargs["system_prompt"]
                assert "新名字" not in str(kwargs)
                return json.dumps(
                    {
                        "query_mode": "exact_fact",
                        "content_query": query,
                        "semantic_frame": {
                            "query_family": "profile",
                            "subject_scope": "self",
                            "answer_kind": "person",
                            "relation_shape": "single_fact",
                            "assertion_query": {"predicates": ["REAL_NAME"], "value_scope": "any"},
                        },
                        "evidence_focus": "declared",
                        "query_temporal": {"kind": "none"},
                    }
                )

        service = HybridRetrievalService(
            store,
            llm_provider_bridge=IntentBridge(),
            config=RetrievalConfig(
                intent_shadow_eval_enabled=False,
                grounding_filter_enabled=False,
                query_expansion_enabled=False,
            ),
        )
        result = await service.query(
            build_query(query=query, user_id="u1", query_mode="exact_fact")
        )
        assert [item["trait_value"] for item in result.l2_assertions] == ["新名字"]

        await store.l2.apply_assertion_correction(
            assertion_id=result.l2_assertions[0]["assertion_id"],
            request_id="remove-name",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
        )
        result = await service.query(
            build_query(query=query, user_id="u1", query_mode="exact_fact")
        )
        assert result.l2_assertions == []
    finally:
        await store.shutdown()


def test_typed_slot_selection_survives_intent_parsing():
    frame = _parse_semantic_frame(
        {
            "query_family": "profile",
            "subject_scope": "self",
            "answer_kind": "person",
            "assertion_query": {"predicates": ["REAL_NAME", "REAL_NAME"], "value_scope": "any"},
        }
    )
    assert frame.assertion_query == AssertionQuery(predicates=["REAL_NAME"], value_scope="any")
