"""Verify ``infer_allowed_evidence_classes`` fires on rule-only fallback paths
(no LLM).

Phase 1 only invoked the evidence-class routing inside
``LLMIntentDecider.apply``. The rule-only fallback (LLM disabled, timed out, or
returning invalid JSON) and the ``service_plan_augmentation`` L2 injection path
silently bypassed the filter, so the original bug — Chrome ``INTERESTED_IN``
flood polluting self-preference queries — would recur whenever the LLM intent
path degraded.

These tests demonstrate the gap and lock in the fix.
"""

from __future__ import annotations

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    L2Conditions,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.rule_intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.service_plan_augmentation import (
    HybridRetrievalPlanAugmentationMixin,
)


def test_rule_fallback_applies_evidence_routing_for_self_preference():
    """When the rule-only intent decider produces an L2 plan for a
    self-preference query, ``allowed_evidence_classes`` must be populated by
    the same static rule that ``LLMIntentDecider.apply`` uses."""
    decider = RuleBasedIntentDecider()
    inp = IntentDeciderInput(
        query="我喜欢什么浏览器",
        query_mode_hint="exact_fact",
    )
    decision = decider.evaluate(inp)

    l2_plan = next(
        (
            p
            for p in decision.plans
            if p.layer == "L2" and isinstance(p.conditions, L2Conditions)
        ),
        None,
    )
    assert l2_plan is not None, "expected an L2 plan from the rule-only decider"

    conditions = l2_plan.conditions
    assert isinstance(conditions, L2Conditions)
    # Sanity: enrichment should have classified this as self-preference.
    assert conditions.predicate_family == "preference"
    assert conditions.subject_hint == "self"

    assert conditions.allowed_evidence_classes == {
        EvidenceClass.USER_SELF_REPORT.label
    }, (
        "rule fallback must apply evidence routing; got "
        f"{conditions.allowed_evidence_classes!r}"
    )


def test_rule_fallback_no_filter_when_family_unknown():
    """If the predicate family is unknown (no routing rule matches), the
    rule fallback must leave ``allowed_evidence_classes`` unset so the
    retriever applies no hard filter."""
    decider = RuleBasedIntentDecider()
    inp = IntentDeciderInput(
        query="测试一下不触发任何家族的查询语句",
        query_mode_hint="exact_fact",
    )
    decision = decider.evaluate(inp)

    l2_plan = next(
        (
            p
            for p in decision.plans
            if p.layer == "L2" and isinstance(p.conditions, L2Conditions)
        ),
        None,
    )
    if l2_plan is None:
        # No L2 plan produced — nothing to assert beyond that.
        return
    conditions = l2_plan.conditions
    assert isinstance(conditions, L2Conditions)
    if conditions.predicate_family in {None, "unknown"}:
        assert conditions.allowed_evidence_classes is None


class _AugmentHost(HybridRetrievalPlanAugmentationMixin):
    """Minimal host exposing the mixin's protected augmentation hook."""

    def augment(
        self,
        primary_plans,
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
    ):
        return self._augment_primary_plans(
            primary_plans, request=request, payload=payload
        )


def test_service_plan_augmentation_applies_evidence_routing():
    """When the service plan augmenter injects an L2 plan for a temporal-anchored
    self-preference query (because no L2 plan was produced upstream), the same
    evidence-class routing rule must apply."""
    host = _AugmentHost()
    # ``has_temporal_anchor`` matches English temporal markers reliably, so we
    # use that to exercise the temporal-anchor injection branch.
    request = RetrievalQuery(
        query="yesterday what browser did I like",
        user_id=None,
        session_id=None,
        time_range={},
    )
    payload = RetrievalPayload()

    # Pass an empty primary plan list so the augmenter must inject an L2 plan
    # via the temporal-anchor branch.
    augmented = host.augment([], request=request, payload=payload)

    l2_plan = next(
        (
            p
            for p in augmented
            if p.layer == "L2" and isinstance(p.conditions, L2Conditions)
        ),
        None,
    )
    assert l2_plan is not None, (
        "expected service_plan_augmentation to inject an L2 plan for a "
        "temporal-anchored query"
    )

    conditions = l2_plan.conditions
    assert isinstance(conditions, L2Conditions)
    # Sanity: the augmenter forces subject_hint='self' and enrich classifies
    # this as preference.
    assert conditions.subject_hint == "self"
    assert conditions.predicate_family == "preference"

    assert conditions.allowed_evidence_classes == {
        EvidenceClass.USER_SELF_REPORT.label
    }, (
        "service_plan_augmentation must apply evidence routing on its "
        "injected L2 plan; got "
        f"{conditions.allowed_evidence_classes!r}"
    )
