"""Exercise the existing provider boundary through host routing and service output.

Responses are scripted: these are policy tests, not semantic accuracy claims.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.combined_intent_decider import IntentDecider
from magi.memory.hybrid_retrieval.llm_intent import LLMIntentDecider
from magi.memory.hybrid_retrieval.models import IntentDeciderInput, RetrievalConfig, RetrievalQuery
from magi.memory.hybrid_retrieval.rule_intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.service import HybridRetrievalService


def _decider(response):
    bridge = SimpleNamespace(chat=AsyncMock(return_value=json.dumps(response)))
    return IntentDecider(rule_engine=RuleBasedIntentDecider(), llm_decider=LLMIntentDecider(bridge)), bridge


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "mode", "focus"), [
    ("我比较喜欢什么音乐", "exact_fact", "declared"),
    ("不用总结，只告诉我喜欢的乐队", "exact_fact", "declared"),
    ("我没告诉过你，但浏览记录能说明我偏好什么", "exact_fact", "observed"),
    ("Summarize my music interests from browsing, not from what I told you", "summary", "observed"),
])
async def test_semantic_intent_is_not_overwritten_by_query_words(query, mode, focus):
    decider, bridge = _decider({"content_query": query, "query_mode": mode, "evidence_focus": focus,
        "semantic_frame": {"query_family": "affinity", "subject_scope": "self", "answer_kind": "media"}})
    result = await decider.decide(IntentDeciderInput(query=query))
    assert result.query_mode == mode
    l2 = next((p.conditions for p in result.plans if p.layer == "L2"), None)
    if l2 is not None:
        assert l2.allowed_evidence_classes == {
            EvidenceClass.EXTERNAL_OBSERVATION.label if focus == "observed" else EvidenceClass.USER_SELF_REPORT.label
        }
        assert l2.evidence_focus_source == "llm"
    assert bridge.chat.await_count == 1
    # The existing query-only request must not acquire private memory rows.
    assert bridge.chat.call_args.kwargs["messages"] == [{"role": "user", "content": f"user query: {query}"}]


@pytest.mark.asyncio
async def test_explicit_caller_mode_and_filters_override_model_suggestion():
    decider, _ = _decider({"content_query": "music", "query_mode": "summary"})
    result = await decider.decide(IntentDeciderInput(query="music", query_mode_hint="exact_fact", source_filters=["chat"], domain_filters=["user_authored"]))
    assert result.query_mode == "exact_fact"
    assert result.plans[0].layer == "L2"
    l1 = next(p.conditions for p in result.plans if p.layer == "L1")
    assert l1.source_filters == ["chat"] and l1.domain_filters == ["user_authored"]


@pytest.mark.asyncio
async def test_invalid_semantics_defaults_without_keyword_fallback():
    decider, _ = _decider({"content_query": "不用总结", "query_mode": ["summary"], "evidence_focus": "invented", "recall_shape": {"operation": "delete"}})
    result = await decider.decide(IntentDeciderInput(query="不用总结"))
    assert result.query_mode == "exact_fact"
    assert result.recall_shape.desired_coverage == "unknown"
    assert result.plans[0].conditions.allowed_evidence_classes is None


@pytest.mark.asyncio
async def test_semantic_mode_and_shape_reach_service_without_new_provider_call():
    decider, bridge = _decider({"content_query": "photos", "query_mode": "summary", "recall_shape": {"domain_hint": "photo", "operation": "count"}})
    memory = SimpleNamespace(l0=None, l1=None, l2=None, l2_entity_catalog=None, l3=None, l4=None)
    service = HybridRetrievalService(memory, config=RetrievalConfig(intent_decider_llm_enabled=False))
    service._intent_decider = decider
    payload = await service.query(RetrievalQuery(query="How many photos?"))
    assert payload.trace["resolved_query_mode"] == "summary"
    assert payload.trace["mode_source"] == "semantic"
    assert payload.trace["mode_explicit"] is False
    assert payload.trace["recall_shape"]["operation"] == "count"
    assert bridge.chat.await_count == 1
