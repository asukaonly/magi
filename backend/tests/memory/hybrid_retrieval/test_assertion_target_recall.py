"""Answer-bearing objects survive ingestion, governance and final recall."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import sqlite3
import time
from types import SimpleNamespace

import pytest

from magi.events.events import EventLevel, EventTypes
from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.models import L2Conditions, RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection import project_historical_recall
from magi.memory.tool_context_historical import compact_historical_recall
from memory.l2.test_claim_text_pipeline import _open_store, _response


async def _say_literal(store, adapter, event_id, target, *, negative=False):
    content = f"我{'不再' if negative else '一直'}喜欢{target}"
    adapter._responses = [_response(
        event_id=event_id, object_ref=target, evidence=content,
        entities=[], object_type="concept", polarity="negative" if negative else "positive",
    )]
    adapter._fallback_response = "{}"
    before = store.get_l2_pipeline_stats()["extract_completed"]
    await store.ingest_event({
        "id": event_id, "type": EventTypes.USER_MESSAGE, "source": "chat",
        "timestamp": time.time(), "level": EventLevel.INFO.value,
        "data": {"user_id": "u1", "session_id": f"session-{event_id}", "content": content},
    })
    for _ in range(800):
        stats = store.get_l2_pipeline_stats()
        if stats["extract_completed"] > before or stats["extract_failed"]:
            break
        await asyncio.sleep(0.01)
    assert stats["extract_failed"] == 0, stats
    assert stats["extract_completed"] == before + 1, stats


async def _recall(store, query):
    result = await L2Handler(store.l2, entity_catalog=store.l2_entity_catalog).execute(
        L2Conditions(content_query=query, subject_hint="self", predicate_family="preference",
                     include_relationships=False, include_tom_snapshot=False),
        user_id="u1",
    )
    recall = project_historical_recall(
        payload=RetrievalPayload(l2_assertions=result["assertions"]),
        request=RetrievalQuery(query=query, user_id="u1", query_mode="exact_fact"),
        canonical_names={"user:u1": "用户"},
    )
    return recall, result


@pytest.mark.asyncio
async def test_literal_preference_recalls_complete_object_then_withdraws(tmp_path):
    store, adapter = await _open_store(tmp_path, "{}")
    try:
        await _say_literal(store, adapter, "quiet-positive", "安静的地方")
        recall, result = await _recall(store, "安静的地方")
        assert recall.status == "found", result
        assert recall.findings[0]["target"] == "安静的地方"
        rendered = compact_historical_recall(asdict(recall), max_items=10, max_text_chars=1000)
        assert "安静的地方" in rendered and "like" in rendered
        await _say_literal(store, adapter, "quiet-withdrawal", "安静的地方", negative=True)
        recall, result = await _recall(store, "安静的地方")
        assert recall.status == "not_found", result
        assert recall.insufficient_evidence is True
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["我喜欢什么音乐", "我喜欢什么运动", "What music do I like?"])
async def test_shared_relation_words_cannot_make_a_different_object_an_answer(tmp_path, query):
    store, adapter = await _open_store(tmp_path, "{}")
    try:
        await _say_literal(store, adapter, "food-positive", "火锅")
        recall, result = await _recall(store, query)
        assert recall.status == "not_found", result
        assert recall.insufficient_evidence is True
        assert result["trace"]["assertion_retrieval"]["relevance_gate"] == "positive_answer_field_overlap"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_literal_target_survives_real_memory_query_tool_contract(tmp_path):
    from magi.core.tool_capabilities import ToolCapabilities
    from magi.memory.hybrid_retrieval import build_query
    from magi.memory.hybrid_retrieval.models import ConversationTurn, RetrievalConfig
    from magi.memory.hybrid_retrieval.service import HybridRetrievalService
    from magi.tools.builtin.memory_query_tool import MemoryQueryTool
    from magi.tools.schema import ToolExecutionContext

    store, adapter = await _open_store(tmp_path, "{}")
    try:
        await _say_literal(store, adapter, "quiet-tool", "安静的地方")
        memory = SimpleNamespace(l0=None, l1=None, l2=store.l2, l2_entity_catalog=store.l2_entity_catalog,
                                 l3=None, l4=None, memory_db_path=store.l2.db_path)
        service = HybridRetrievalService(memory, config=RetrievalConfig(intent_decider_llm_enabled=False))
        class Port:
            memory_db_path = store.l2.db_path
            @staticmethod
            def build_query(**kwargs):
                return build_query(**kwargs)
            make_conversation_turn = staticmethod(ConversationTurn)
            project_historical_recall = staticmethod(project_historical_recall)
            query = staticmethod(service.query)
            @staticmethod
            async def get_canonical_names(_ids):
                return {"user:u1": "用户"}
        context = ToolExecutionContext(agent_id="probe", capabilities=ToolCapabilities(memory_query=Port()), env_vars={"user_id": "u1"})
        result = await MemoryQueryTool().execute({"query": "安静的地方", "query_mode": "exact_fact"}, context)
        assert result.success
        assert result.data["historical_recall"]["status"] == "found", result.data
        assert "安静的地方" in compact_historical_recall(result.data["historical_recall"], max_items=10, max_text_chars=1000)
        missing = await MemoryQueryTool().execute({"query": "我喜欢什么音乐", "query_mode": "exact_fact"}, context)
        assert missing.data["historical_recall"]["status"] == "not_found", missing.data
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidated_contract", [
    "projection_receipt", "route_outcome", "route_slot", "route_trait",
    "claim_interval", "source_forgetting",
])
async def test_literal_target_requires_current_governed_support(tmp_path, invalidated_contract):
    store, adapter = await _open_store(tmp_path, "{}")
    try:
        await _say_literal(store, adapter, "quiet-supported", "安静的地方")
        recall, _ = await _recall(store, "安静的地方")
        assert recall.status == "found"
        if invalidated_contract == "source_forgetting":
            assert await store.forget_source_event("quiet-supported")
        else:
            # Break one independent persisted support contract in synthetic storage.
            updates = {
                "projection_receipt": "UPDATE l2_claim_projection_outcomes SET invalidated_at = 1 WHERE target_kind = 'assertion'",
                "route_outcome": "UPDATE l2_claim_projection_outcomes SET outcome = 'unrouted' WHERE target_kind = 'route'",
                "route_slot": "UPDATE l2_claim_projection_outcomes SET target_slot_key = 'another-slot' WHERE target_kind = 'route'",
                "route_trait": "UPDATE l2_claim_projection_outcomes SET details_json = json_set(details_json, '$.trait_code', 'another.trait') WHERE target_kind = 'route'",
                "claim_interval": "UPDATE l2_grounded_claims SET fact_valid_from = 0, fact_valid_to = 1",
            }
            with sqlite3.connect(store.l2.db_path) as db:
                db.execute(updates[invalidated_contract])
        recall, result = await _recall(store, "安静的地方")
        assert recall.status == "not_found", result
        assert recall.insufficient_evidence is True
        assert "安静的地方" not in compact_historical_recall(asdict(recall), max_items=10, max_text_chars=1000)
    finally:
        await store.shutdown()
