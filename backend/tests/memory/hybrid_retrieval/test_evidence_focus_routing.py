"""Phase 2A north star: LLM-produced evidence_focus drives allowed_evidence_classes
directly, bypassing the static (predicate_family, subject_scope) rule that Phase 1
relied on. Validates the LLMIntentDecider.apply priority chain end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.llm_intent import (
    LLMIntentDecider,
    LLMRefinement,
)
from magi.memory.hybrid_retrieval.models import (
    IntentDecision,
    L2Conditions,
    LayerQueryPlan,
)


def _make_l2_plan(conditions: L2Conditions) -> IntentDecision:
    return IntentDecision(
        plans=[LayerQueryPlan(layer="L2", conditions=conditions)],
        reasoning="",
        source="rule",
    )


def test_llm_evidence_focus_directly_sets_allowed_evidence_classes():
    """When LLM produced evidence_focus='observed', the apply step must set
    allowed_evidence_classes to {EXTERNAL_OBSERVATION} regardless of what
    predicate_family/subject_hint say."""
    decider = LLMIntentDecider(provider_bridge=None)
    conditions = L2Conditions(
        content_query="我浏览过哪些公司",
        subject_hint="self",
        predicate_family="preference",  # Phase 1 rule would say {USER_SELF_REPORT}
    )
    decision = _make_l2_plan(conditions)
    refinement = LLMRefinement(
        content_query="我浏览过哪些公司",
        subject_hint="self",
        predicate_family="preference",
        evidence_focus="observed",  # LLM direct call overrides family-derived
    )

    decider.apply(
        original_query="我浏览过哪些公司",
        rule_decision=decision,
        refinement=refinement,
    )

    assert conditions.allowed_evidence_classes == {
        EvidenceClass.EXTERNAL_OBSERVATION.label
    }, (
        f"expected LLM evidence_focus to override family rule; got "
        f"{conditions.allowed_evidence_classes!r}"
    )


def test_llm_refinement_parses_evidence_focus_from_response():
    decider = LLMIntentDecider(provider_bridge=None)
    raw = '{"content_query": "q", "evidence_focus": "declared"}'
    parsed = decider._parse_response(raw)
    assert parsed is not None
    assert parsed.evidence_focus == "declared"


def test_llm_refinement_evidence_focus_is_none_when_absent():
    decider = LLMIntentDecider(provider_bridge=None)
    raw = '{"content_query": "q"}'
    parsed = decider._parse_response(raw)
    assert parsed is not None
    assert parsed.evidence_focus is None


def test_llm_refinement_rejects_invalid_evidence_focus():
    decider = LLMIntentDecider(provider_bridge=None)
    raw = '{"content_query": "q", "evidence_focus": "garbage"}'
    parsed = decider._parse_response(raw)
    assert parsed is not None
    assert parsed.evidence_focus is None  # invalid value silently dropped


from magi.memory.hybrid_retrieval.evidence_routing import classes_from_focus


def test_classes_from_focus_declared():
    assert classes_from_focus("declared") == {EvidenceClass.USER_SELF_REPORT.label}


def test_classes_from_focus_observed():
    assert classes_from_focus("observed") == {EvidenceClass.EXTERNAL_OBSERVATION.label}


def test_classes_from_focus_both():
    assert classes_from_focus("both") == {
        EvidenceClass.USER_SELF_REPORT.label,
        EvidenceClass.EXTERNAL_OBSERVATION.label,
    }


def test_classes_from_focus_none_returns_none():
    assert classes_from_focus(None) is None
