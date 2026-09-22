"""Unavailable semantics must not turn query substrings into hard restrictions."""
import pytest
from magi.memory.hybrid_retrieval.models import IntentDeciderInput, L2Conditions, RetrievalQuery, TimeRange
from magi.memory.hybrid_retrieval.rule_intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.service_plan_augmentation import _temporal_l2_plan

@pytest.mark.parametrize("query", [
    "我没告诉过你，但浏览记录能说明我偏好什么", "我比较喜欢什么音乐",
    "不用总结，只告诉我爵士乐的偏好", "What do my visits suggest, not what I said?",
    "Alice likes jazz. What about Bob?", "I dislike the summary; find the exact fact",
])
def test_unknown_semantics_does_not_invent_owner_family_or_evidence_filter(query):
    decision = RuleBasedIntentDecider().evaluate(IntentDeciderInput(query=query))
    assert decision.query_mode == "exact_fact"
    conditions = next(p.conditions for p in decision.plans if p.layer == "L2")
    assert isinstance(conditions, L2Conditions)
    assert conditions.allowed_evidence_classes is None
    assert conditions.semantic_frame is None
    assert conditions.subject_hint is None
    assert conditions.predicate_family is None


def test_temporal_augmentation_does_not_invent_self_attribution():
    plan = _temporal_l2_plan(RetrievalQuery(query="Yesterday Alice liked jazz"), time_range=TimeRange(start=1, end=2))
    assert plan.conditions.subject_hint is None
    assert plan.conditions.allowed_evidence_classes is None
