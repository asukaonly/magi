"""Verification tests for P1-C2: background LLM cost, retrieval latency, and daily budget guard."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.config.models import LLMScenario
from magi.llm.background_budget import (
    BackgroundBudgetExceededError,
    BackgroundLLMBudgetGuard,
    is_background_request_kind,
    set_background_llm_budget_guard,
)
from magi.llm.provider_bridge.models import ProviderResponse
from magi.llm.provider_bridge.requests import ProviderBridgeRequestMixin
from magi.llm.usage_store import LLMUsageStore
from magi.memory.hybrid_retrieval.combined_intent_decider import IntentDecider
from magi.memory.hybrid_retrieval.grounding_filter import GroundingFilter
from magi.memory.hybrid_retrieval.llm_intent import LLMIntentDecider
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.rule_intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l2.llm_json_client import L2LLMBudgetExceededError, L2LLMJsonClientMixin
from magi.memory.l2.models import L2BatchEvent, L2EventWindow, L2Phase1Result
from magi.memory.l2.promotion_counter import L2PromotionCounter
from magi.memory.l2.self_report_review import review_self_report_claims
from magi.memory.l3.models import TemporalEvidencePack
from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService


def _temporal_pack(service: TemporalSummaryLLMService, category: str) -> TemporalEvidencePack:
    return service.build_evidence_pack(
        events=[
            {
                "event_id": "e1",
                "event_type": "UserMessage",
                "content": "Worked on Rust parser",
                "memory_domain": "user_authored",
                "importance_score": 0.7,
                "timestamp": 1_760_000_100.0,
            },
            {
                "event_id": "e2",
                "event_type": "AIResponse",
                "content": "Reviewed benchmarks",
                "memory_domain": "user_authored",
                "importance_score": 0.7,
                "timestamp": 1_760_000_200.0,
            },
        ],
        summary_category=category,
        period_start=1_760_000_000.0,
        period_end=1_760_003_600.0,
    )


@pytest.mark.asyncio
async def test_24h_simulation_reduces_background_llm_calls_by_over_65_percent(monkeypatch, tmp_path):
    """Simulate 24 hourly + 1 daily L3 + 20 routine chats + 50 passive source events."""
    # Baseline before P1-B3 + P1-C2:
    # - 24 hourly L3 * 2 LLM calls = 48
    # - 1 daily L3 * 2 LLM calls = 2
    # - 20 routine self-report chat turns * (1 extract + 1 CORE review) = 40
    # - 50 passive source events (e.g. repeated visits/plays without 6h cooldown) = 50
    baseline_background_calls = 48 + 2 + 40 + 50  # 140 calls

    hour_llm_calls = 0
    day_llm_calls = 0
    review_llm_calls = 0

    monkeypatch.setattr("magi.i18n.get_preferred_language", lambda default="zh-CN": "en")
    temporal_service = TemporalSummaryLLMService()

    async def fake_generate_prose(pack, **_kwargs):
        nonlocal hour_llm_calls, day_llm_calls
        if pack.summary_category == "hour":
            hour_llm_calls += 1
        else:
            day_llm_calls += 1
        return "Focused on Rust parser implementation and verified benchmarks."

    async def fake_generate_structure(pack, **_kwargs):
        nonlocal hour_llm_calls, day_llm_calls
        if pack.summary_category == "hour":
            hour_llm_calls += 1
        else:
            day_llm_calls += 1
        return {
            "key_topics": ["Rust parser"],
            "key_entities": [],
            "sentiment_summary": None,
            "change_and_pattern": None,
            "unsupported_claims": [],
        }

    monkeypatch.setattr(temporal_service._model_client, "call_prose_model", fake_generate_prose)
    monkeypatch.setattr(temporal_service._model_client, "call_structure_model", fake_generate_structure)
    monkeypatch.setattr(temporal_service, "_get_adapter", lambda: object())

    # 1. 24 hourly summaries -> 0 LLM calls (deterministic local aggregation)
    for _ in range(24):
        result = await temporal_service.generate_temporal_candidate(
            _temporal_pack(temporal_service, "hour"),
            fallback_summary="Deterministic hourly summary",
        )
        assert result.used_fallback is True
    assert hour_llm_calls == 0

    # 2. 1 daily summary -> 2 LLM calls (prose + structure, thinking disabled)
    day_result = await temporal_service.generate_temporal_candidate(
        _temporal_pack(temporal_service, "day"),
        fallback_summary="Deterministic daily summary",
    )
    assert day_result.used_fallback is False
    assert day_llm_calls == 2

    # 3. 20 routine chat turns: 17 benign activity facts (skip review) + 3 high-risk preference/identity claims (trigger AUXILIARY review)
    async def fake_review(**kwargs):
        nonlocal review_llm_calls
        review_llm_calls += 1
        assert kwargs["scenario"] is LLMScenario.AUXILIARY
        assert kwargs["disable_thinking"] is True
        return {"reviews": [{"claim_index": 0, "verdict": "direct_self_report"}]}

    l2_extract_calls = 20
    for idx in range(20):
        predicate = "LIKES" if idx < 3 else "READ"
        phase1 = L2Phase1Result.from_dict(
            {
                "fact_claims": [
                    {
                        "subject_ref": "user:self",
                        "predicate": predicate,
                        "object_ref": f"topic:item-{idx}",
                        "object_type": "topic",
                        "confidence": 0.9,
                        "evidence_text": f"I read item {idx}",
                        "supporting_event_ids": ["#E1"],
                        "evidence_mode": "direct",
                    }
                ]
            }
        )
        await review_self_report_claims(
            generate_json=fake_review,
            result=phase1,
            event_window=L2EventWindow(
                events=[L2BatchEvent(event_id="evt", content=f"I read item {idx}", source="chat")]
            ),
            context_messages=[],
        )
    assert review_llm_calls == 3

    # 4. 50 passive source events across 5 recurring keys within 24h (6h cooldown + 3x threshold)
    counter = L2PromotionCounter(str(tmp_path / "promo.db"))
    await counter.initialize()
    passive_llm_calls = 0
    base_ts = 1_760_000_000.0
    for i in range(50):
        key = f"chrome:domain-{i % 5}"
        _count, admitted = await counter.bump(
            "chrome", key, f"evt-{i}", threshold=3, now=base_ts + i * 600.0
        )
        if admitted:
            passive_llm_calls += 1
    assert passive_llm_calls <= 10

    total_new_calls = hour_llm_calls + day_llm_calls + l2_extract_calls + review_llm_calls + passive_llm_calls
    reduction_ratio = 1.0 - (total_new_calls / baseline_background_calls)
    assert reduction_ratio >= 0.65, f"Expected >=65% reduction, got {reduction_ratio:.2%} ({total_new_calls} vs {baseline_background_calls})"


@pytest.mark.asyncio
async def test_memory_query_fast_path_and_merged_intent_with_thresholded_grounding():
    """Simple explicit-time+keyword query uses 0 aux LLM calls; complex query uses <= 2."""
    events = [
        {"event_id": f"e-{i}", "source": "chat", "content": f"Rust async note {i}", "timestamp": 1_760_000_000.0 + i}
        for i in range(5)
    ]
    l1 = AsyncMock()
    l1.bm25_search.return_value = [(e["event_id"], -1.0) for e in events]
    l1.vector_search.return_value = []
    l1.query_events.return_value = events
    l1.search_events.return_value = events
    l1.resolve_event_entities.return_value = []
    l1.find_events_by_entities.return_value = []
    l1.expand_by_entities.return_value = []
    l1.filter_ids_by_user.return_value = []
    l1.fetch_events.return_value = events
    memory = SimpleNamespace(l0=None, l1=l1, l2=None, l2_entity_catalog=None, l3=None, l4=None)

    bridge = SimpleNamespace(
        chat=AsyncMock(
            return_value=json.dumps(
                {
                    "query_mode": "exact_fact",
                    "content_query": "Rust async",
                    "expanded_queries": ["tokio runtime", "async await rust"],
                    "reasoning": "lookup with synonyms",
                }
            )
        )
    )
    service = HybridRetrievalService(
        memory,
        config=RetrievalConfig(
            intent_decider_llm_enabled=True,
            query_expansion_enabled=True,
            grounding_filter_enabled=True,
            grounding_filter_min_candidates=16,
        ),
        llm_provider_bridge=bridge,
    )

    # 1. Simple explicit time + concise keyword -> rule fast-path: 0 LLM calls total
    fast_payload = await service.query(
        RetrievalQuery(
            query="Rust async",
            time_range={"relative": "7d"},
            query_mode="event_stream",
        )
    )
    assert fast_payload.trace["intent_source"] == "rule_fast_path"
    assert fast_payload.trace["query_expansion_skipped"] == "rule_fast_path"
    assert fast_payload.trace["grounding_filter"]["applied"] is False
    assert fast_payload.trace["grounding_filter"]["skipped_reason"] == "below_candidate_threshold"
    assert bridge.chat.await_count == 0

    # 2. Complex unbounded question -> 1 merged intent+expansion LLM call, 0 standalone expansion, 0 grounding (<=15 items)
    complex_payload = await service.query(
        RetrievalQuery(query="我最近为什么一直在研究 Rust 异步和数据库性能优化？")
    )
    assert complex_payload.trace["intent_source"] == "llm"
    assert complex_payload.trace["query_expansion_source"] == "merged_intent"
    assert complex_payload.trace["query_expansion_queries"] == ["tokio runtime", "async await rust"]
    assert complex_payload.trace["grounding_filter"]["applied"] is False
    assert bridge.chat.await_count == 1

    # 3. GroundingFilter fires only when candidate count >= 16 (> 15)
    filter_bridge = SimpleNamespace(chat=AsyncMock(return_value=json.dumps({"keep": [1, 2], "why": "top matches"})))
    gf = GroundingFilter(llm_bridge=filter_bridge, min_candidates=16)

    small_payload = RetrievalPayload(
        l1_events=[{"event_id": f"s-{i}", "content": f"item {i}"} for i in range(15)]
    )
    await gf.apply(small_payload, RetrievalQuery(query="test"))
    assert filter_bridge.chat.await_count == 0
    assert small_payload.trace["grounding_filter"]["skipped_reason"] == "below_candidate_threshold"

    large_payload = RetrievalPayload(
        l1_events=[{"event_id": f"l-{i}", "content": f"item {i}"} for i in range(16)]
    )
    await gf.apply(large_payload, RetrievalQuery(query="test"))
    assert filter_bridge.chat.await_count == 1
    assert large_payload.trace["grounding_filter"]["applied"] is True
    assert len(large_payload.l1_events) == 2


@pytest.mark.asyncio
async def test_daily_background_budget_blocks_background_allows_chat_and_resets_next_day(tmp_path, ensure_db_schema, monkeypatch):
    """Tiny daily budget blocks L2/L3/background bridge calls, never blocks chat, and resets across midnight."""
    db_path = tmp_path / "llm_usage.db"
    ensure_db_schema("llm_usage", str(db_path))
    store = LLMUsageStore(db_path)

    now_ts = time.time()
    today_recent = max(
        datetime.now().replace(hour=0, minute=0, second=1, microsecond=0).timestamp(),
        now_ts - 60.0,
    )
    tomorrow_morning = (datetime.now().replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)).timestamp()

    await store.record_call(
        {
            "request_id": "bg-1",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "request_kind": "memory:l2_extract",
            "success": True,
            "usage_available": True,
            "prompt_tokens": 600,
            "completion_tokens": 400,
            "total_tokens": 1000,
            "created_at": today_recent,
        }
    )

    guard = BackgroundLLMBudgetGuard(usage_store=store, cache_ttl_seconds=0.0)
    monkeypatch.setattr(guard, "_configured_budget", lambda: 500)
    set_background_llm_budget_guard(guard)
    try:
        # Foreground chat & online retrieval are NEVER blocked
        assert is_background_request_kind("chat:response") is False
        assert is_background_request_kind("memory:hybrid_retrieval_intent") is False
        chat_decision = await guard.check("chat:response", now=now_ts)
        assert chat_decision.allowed is True

        # Background L2/L3/Reflection are blocked with observable reason
        bg_decision = await guard.check("memory:l2_extract", now=now_ts)
        assert bg_decision.allowed is False
        assert bg_decision.reason == "daily_background_token_budget_exceeded"
        assert bg_decision.used_tokens == 1000
        assert bg_decision.budget_tokens == 500

        # L2LLMJsonClientMixin enforces budget and raises retryable L2LLMBudgetExceededError
        class _FakeL2Client(L2LLMJsonClientMixin):
            def __init__(self):
                self._scenario_llm_pool = None
                self._llm_adapter = SimpleNamespace(model_name="fake")

        l2_client = _FakeL2Client()
        with pytest.raises(L2LLMBudgetExceededError) as exc_info:
            await l2_client._generate_json(
                system_prompt="sys",
                prompt="user",
                request_kind="memory:l2_extract",
            )
        assert exc_info.value.retryable is True

        # TemporalSummaryLLMService degrades smoothly to deterministic fallback without calling model
        temporal_service = TemporalSummaryLLMService()
        monkeypatch.setattr(temporal_service, "_get_adapter", lambda: object())
        mock_prose = AsyncMock()
        monkeypatch.setattr(temporal_service._model_client, "call_prose_model", mock_prose)
        day_result = await temporal_service.generate_temporal_candidate(
            _temporal_pack(temporal_service, "day"),
            fallback_summary="Deterministic day fallback",
        )
        assert day_result.used_fallback is True
        assert mock_prose.await_count == 0

        # ProviderBridge blocks background request_kind, allows foreground chat request_kind
        class _FakeBridge(ProviderBridgeRequestMixin):
            def __init__(self):
                self.llm = SimpleNamespace(is_plugin_provider=False, _client=None, model_name="fake", chat=AsyncMock(return_value="ok"))

            def is_anthropic(self):
                return False

            def _convert_messages_to_openai(self, messages):
                return list(messages)

            def _mark_message_cache_breakpoints(self, _orig, api_messages):
                return api_messages

            def _cache_marked_system(self, system_prompt, *, cache_whole=False):
                return system_prompt

            def _apply_provider_options(self, kwargs, _thinking_depth):
                return kwargs

            def _apply_cache_routing(self, kwargs, _event_context):
                return kwargs

            def _build_content_response(self, content: str) -> ProviderResponse:
                return ProviderResponse(content=content)

        from magi.config.models import ThinkingDepth

        fake_bridge = _FakeBridge()
        with pytest.raises(BackgroundBudgetExceededError):
            await fake_bridge._chat_response_impl(
                system_prompt="sys",
                messages=[{"role": "user", "content": "bg"}],
                max_tokens=100,
                temperature=0.0,
                thinking_depth=ThinkingDepth.NONE,
                json_mode=False,
                timeout_seconds=5.0,
                event_context={"request_kind": "memory:l3_episodic_summary_prose"},
            )
        chat_resp = await fake_bridge._chat_response_impl(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
            temperature=0.0,
            thinking_depth=ThinkingDepth.NONE,
            json_mode=False,
            timeout_seconds=5.0,
            event_context={"request_kind": "chat:response"},
        )
        assert chat_resp.content == "ok"

        # Next calendar day automatically resets daily usage to 0 -> background allowed again
        next_day_decision = await guard.check("memory:l2_extract", now=tomorrow_morning)
        assert next_day_decision.allowed is True
        assert next_day_decision.used_tokens == 0
    finally:
        set_background_llm_budget_guard(None)
