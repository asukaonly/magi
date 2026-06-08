"""LLM relation_intent field parsing + apply (RFC #65 P1)."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.llm_intent import LLMIntentDecider, LLMRefinement
from magi.memory.hybrid_retrieval.models import IntentDecision, LayerQueryPlan, L2Conditions


def test_parse_extracts_relation_intent():
    decider = LLMIntentDecider(provider_bridge=None)
    raw = (
        '{"content_query": "songs I am listening to",'
        ' "relation_intent": "listening to / consuming media",'
        ' "reasoning": "x"}'
    )
    refinement = decider._parse_response(raw)
    assert refinement is not None
    assert refinement.relation_intent == "listening to / consuming media"


def test_parse_relation_intent_absent_is_none():
    decider = LLMIntentDecider(provider_bridge=None)
    raw = '{"content_query": "abc", "reasoning": "x"}'
    refinement = decider._parse_response(raw)
    assert refinement is not None
    assert refinement.relation_intent is None


def test_apply_writes_relation_intent_to_l2_conditions():
    decider = LLMIntentDecider(provider_bridge=None)
    conditions = L2Conditions(content_query="orig")
    decision = IntentDecision(plans=[LayerQueryPlan(layer="L2", conditions=conditions)])
    refinement = LLMRefinement(content_query="cq", relation_intent="likes / is fond of")
    decider.apply(original_query="q", rule_decision=decision, refinement=refinement)
    assert conditions.relation_intent == "likes / is fond of"
