"""Phase 2A north star: LLM-produced evidence_focus drives allowed_evidence_classes
directly, bypassing the static (predicate_family, subject_scope) rule that Phase 1
relied on. Validates the LLMIntentDecider.apply priority chain end-to-end.
"""

from __future__ import annotations

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


@pytest.mark.parametrize(
    "response,expected",
    [
        ('{"content_query":"q"}', None),
        ('{"content_query":"q","evidence_focus":"garbage"}', None),
        ('{"content_query":"q","evidence_focus":"declared"}', "declared"),
        ('{"content_query":"q","evidence_focus":"observed"}', "observed"),
        ('{"content_query":"q","evidence_focus":"both"}', "both"),
    ],
)
def test_evidence_focus_response_boundary_preserves_valid_focus(response, expected):
    parsed = LLMIntentDecider(provider_bridge=None)._parse_response(response)
    assert parsed is not None
    assert parsed.content_query == "q"
    assert parsed.evidence_focus == expected
