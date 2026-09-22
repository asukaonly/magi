"""Regression coverage for query-aware, governed assertion candidate selection."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.hybrid_retrieval.assertion_relevance import ASSERTION_PAGE_SIZE, rank_assertions
from magi.memory.hybrid_retrieval.governed_l2_recall import GovernedL2RecallView
from magi.memory.hybrid_retrieval.grounding import GroundedEntityCandidate, L2GroundingPlan
from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.l2_subdomain_retrievers import retrieve_assertions
from magi.memory.hybrid_retrieval.models import L2Conditions, RetrievalConfig
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l2.store import L2CognitionStore
from magi.memory.retrieval_projection_findings import _attach_score, _project_assertions


async def _seed(store, name, text, *, user_id="local_user", **overrides):
    now = time.time()
    return await store.upsert_assertion_candidate({
        "entity_id": f"user:{user_id}", "entity_type": "user",
        "trait_family": "preference_profile", "trait_name": f"preference.{name}",
        "trait_value": name, "natural_summary": text,
        "confidence_score": 0.9, "volatility_index": 0.1,
        "evidence_events": [f"event-{name}"], "source_domain": "user_authored",
        "inference_depth": "semantic", "validation_state": "stable",
        "first_inferred_at": now - 100, "last_validated_at": now - 1,
        "temporal_scope": "persistent", **overrides,
    })


@pytest.fixture
async def assertion_store(tmp_path):
    path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(path)
    store = L2CognitionStore(db_path=path)
    await store.initialize()
    return store


def _plan(query):
    return L2GroundingPlan(
        query_kind="preference", content_query=query, subject_scope="self",
        subject_candidates=[GroundedEntityCandidate("user:local_user", "user", "self", 1.0)],
    )


@pytest.mark.asyncio
async def test_old_relevant_assertion_survives_three_hundred_newer_distractors(assertion_store):
    old = await _seed(assertion_store, "music", "用户喜欢爵士音乐", trait_value="爵士音乐")
    for index in range(300):
        await _seed(assertion_store, f"food{index}", f"用户喜欢食物编号{index}")
    trace = {}
    rows = await retrieve_assertions(
        _plan("我喜欢什么音乐"),
        GovernedL2RecallView(assertion_store, context_scope={}, effective_at=time.time()),
        limit=3, trace=trace,
    )
    assert rows[0]["assertion_id"] == old
    assert len(rows) == 1
    assert trace["candidate_count"] == 301
    assert trace["page_count"] > 1
    assert trace["coverage"] == "all_governed_slots"
    assert trace["ranking"] == "lexical"
    assert trace["fallback_reason"] == "local_model_disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["我喜欢什么音乐", "What kind of music do I enjoy?"])
async def test_local_semantic_ranking_sees_old_fact_and_only_governed_rows(
    assertion_store, monkeypatch, query,
):
    from magi.memory.hybrid_retrieval import cross_encoder
    old = await _seed(assertion_store, "affinity", "用户喜欢爵士乐")
    for index in range(100):
        await _seed(assertion_store, f"food{index}", f"用户喜欢食物编号{index}")
    await _seed(assertion_store, "private_other", "OTHER-USER-CANARY", user_id="other")
    await _seed(assertion_store, "expired", "EXPIRED-CANARY", expires_at=time.time() - 10)
    await _seed(assertion_store, "scoped", "SCOPED-CANARY", scope={
        "all_of": [{"dimension": "project", "context_id": "ctx_project_" + "a" * 64}],
    })
    seen = []
    class Scorer:
        async def score_pairs(self, pairs):
            seen.extend(pairs)
            return [0.99 if "爵士乐" in text else 0.01 for _, text in pairs]
    monkeypatch.setattr(cross_encoder, "_resolve_cross_encoder_paths", lambda config: (Path("/model"), Path("/model/model.onnx")))
    monkeypatch.setattr(cross_encoder, "_get_or_create_scorer", AsyncMock(return_value=Scorer()))
    handler = L2Handler(assertion_store, config=RetrievalConfig(cross_encoder_enabled=True))
    result = await handler.execute(L2Conditions(
        content_query=query, subject_hint="self", predicate_family="preference",
        include_tom_snapshot=False, include_relationships=False, limit=3,
    ), user_id="local_user")
    rows = result["assertions"]
    assert rows[0]["assertion_id"] == old
    assert rows[0]["_query_relevance_score"] == 0.99
    assert len(seen) == 101
    assert all(text_query == query for text_query, _ in seen)
    assert all("CANARY" not in text for _, text in seen)
    assert result["trace"]["assertion_retrieval"]["ranking"] == "semantic_local"
    assert len(rows) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_missing_or_failing_local_model_reports_lexical_fallback(monkeypatch, fails):
    from magi.memory.hybrid_retrieval import cross_encoder
    if fails:
        monkeypatch.setattr(cross_encoder, "_resolve_cross_encoder_paths", lambda config: (Path("/model"), Path("/model/model.onnx")))
        monkeypatch.setattr(cross_encoder, "_get_or_create_scorer", AsyncMock(side_effect=RuntimeError("unavailable")))
    else:
        monkeypatch.setattr(cross_encoder, "_resolve_cross_encoder_paths", lambda config: None)
    trace = {}
    rows = await rank_assertions([
        {"assertion_id": "food", "natural_summary": "用户喜欢火锅", "trait_name": "preference.affinity", "target_entity_name": "火锅", "trait_value": "like"},
        {"assertion_id": "music", "natural_summary": "用户喜欢爵士音乐", "trait_name": "preference.affinity", "target_entity_name": "爵士音乐", "trait_value": "like"},
    ], query="音乐", limit=1, config=RetrievalConfig(cross_encoder_enabled=True), trace=trace)
    assert rows[0]["assertion_id"] == "music"
    assert trace["ranking"] == "lexical"
    assert trace["fallback_reason"] == "local_model_unavailable_or_failed"


@pytest.mark.asyncio
async def test_all_pages_compete_for_global_top_k():
    async def pages(**kwargs):
        assert kwargs["page_size"] == ASSERTION_PAGE_SIZE
        yield [{"assertion_id": "food", "trait_value": "火锅"}]
        yield [{"assertion_id": "music", "trait_value": "爵士音乐"}]
    trace = {}
    rows = await retrieve_assertions(
        _plan("音乐"), SimpleNamespace(iter_tom_assertions=pages), limit=1, trace=trace,
    )
    assert [row["assertion_id"] for row in rows] == ["music"]
    assert trace["page_count"] == 2
    assert trace["candidate_count"] == 2
    assert trace["coverage"] == "all_governed_slots"


@pytest.mark.asyncio
async def test_empty_candidate_pool_does_not_attempt_model():
    trace = {}
    assert await rank_assertions([], query="音乐", limit=2, config=RetrievalConfig(cross_encoder_enabled=True), trace=trace) == []
    assert trace["ranking"] == "not_needed"


def test_service_wires_and_refreshes_local_ranking_configuration():
    original = RetrievalConfig(cross_encoder_enabled=False)
    changed = RetrievalConfig(cross_encoder_enabled=True, cross_encoder_model_id="local-model")
    memory = SimpleNamespace(l1=None, l2=object(), l3=None, l4=None)
    service = HybridRetrievalService(memory, config=original, config_getter=lambda: changed)
    assert service._l2._config == original
    service._refresh_runtime_config()
    assert service._l2._config == changed


def test_answer_projection_preserves_query_relevance_over_assertion_confidence():
    findings, _ = _project_assertions([
        {"entity_id": "user:local_user", "trait_name": "preference.music", "trait_value": "jazz", "confidence_score": 0.7, "_fusion_score": 0.8},
        {"entity_id": "user:local_user", "trait_name": "preference.food", "trait_value": "hotpot", "confidence_score": 1.0, "_fusion_score": 0.3},
    ])
    for finding in findings:
        _attach_score(finding, mode="fact", answer_kind="unknown", polarity="positive")
    assert findings[0]["_score"] > findings[1]["_score"]


@pytest.mark.asyncio
async def test_zero_relevance_produces_not_found_in_answer_contract(assertion_store):
    from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
    from magi.memory.retrieval_projection import project_historical_recall

    for index in range(3):
        await _seed(assertion_store, f"food{index}", f"用户喜欢火锅餐厅{index}")
    handler = L2Handler(assertion_store)
    result = await handler.execute(L2Conditions(
        content_query="我偏爱什么运动", subject_hint="self", predicate_family="preference",
        include_relationships=False, include_tom_snapshot=False,
    ), user_id="local_user")
    assert result["assertions"] == []
    assert result["trace"]["assertion_retrieval"]["abstained"] is True
    recall = project_historical_recall(
        payload=RetrievalPayload(l2_assertions=result["assertions"]),
        request=RetrievalQuery(query="我偏爱什么运动", user_id="local_user", query_mode="exact_fact"),
    )
    assert recall.status == "not_found"
    assert recall.insufficient_evidence is True


@pytest.mark.asyncio
async def test_governed_slot_winner_is_chosen_before_query_matching(assertion_store):
    from _shared.context_scope import context_scope

    scope = context_scope(project="work")
    await _seed(assertion_store, "drink", "用户喜欢咖啡", trait_value="咖啡")
    winner = await _seed(assertion_store, "drink", "用户喜欢绿茶", trait_value="绿茶", scope=scope)
    for index in range(80):
        await _seed(assertion_store, f"noise{index}", f"用户喜欢菜品{index}")
    view = GovernedL2RecallView(assertion_store, context_scope=scope, effective_at=time.time())
    assert await retrieve_assertions(_plan("咖啡"), view, limit=3) == []
    rows = await retrieve_assertions(_plan("绿茶"), view, limit=3)
    assert [row["assertion_id"] for row in rows] == [winner]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["我有什么听歌口味", "What kind of music do I enjoy?"])
async def test_lexical_degradation_abstains_instead_of_inventing_semantics(query):
    trace = {}
    rows = await rank_assertions([
        {"assertion_id": "food", "natural_summary": "用户喜欢火锅", "trait_name": "preference.affinity", "target_entity_name": "火锅", "trait_value": "like"},
        {"assertion_id": "music", "natural_summary": "用户偏爱爵士乐"},
    ], query=query, limit=3, config=RetrievalConfig(), trace=trace)
    assert rows == []
    assert trace["ranking"] == "lexical"
    assert trace["fallback_reason"] == "local_model_disabled"
    assert trace["abstained"] is True
