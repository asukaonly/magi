"""Primary plan augmentation helpers for hybrid retrieval service queries."""

from __future__ import annotations

from typing import Any

from .answerability import has_temporal_anchor
from .evidence_routing import (
    classes_from_focus,
    infer_allowed_evidence_classes,
    infer_evidence_focus_heuristic,
)
from .intent_decider import enrich_l2_conditions
from .intent_time import parse_time_range
from .models import (
    L1Conditions,
    L2Conditions,
    LayerQueryPlan,
    RetrievalPayload,
    RetrievalQuery,
    TimeRange,
)
from .service_policy import plan_signature


class HybridRetrievalPlanAugmentationMixin:
    """Add deterministic evidence plans around primary intent-decider plans."""

    @staticmethod
    def _plan_signature(plan: Any) -> tuple[str, str, bool]:
        """Build a stable identity for a layer query plan."""
        return plan_signature(plan)

    def _augment_primary_plans(
        self,
        primary_plans: list[LayerQueryPlan],
        *,
        request: RetrievalQuery,
        payload: RetrievalPayload,
        time_range: TimeRange | None = None,
    ) -> list[LayerQueryPlan]:
        """Add service-level evidence plans for semantic affinity queries when needed."""
        resolved_time_range = _resolved_augmentation_time_range(
            primary_plans,
            request=request,
            time_range=time_range,
        )
        _apply_request_constraints(
            primary_plans,
            request=request,
            time_range=resolved_time_range,
        )
        seen_signatures = {self._plan_signature(plan) for plan in primary_plans}
        augmented_plans = list(primary_plans)
        if self._add_joint_l1_evidence_plans(
            primary_plans=primary_plans,
            augmented_plans=augmented_plans,
            seen_signatures=seen_signatures,
            request=request,
        ):
            payload.trace["joint_l1_affinity_evidence"] = True

        if self._ensure_l1_plan(
            augmented_plans,
            request=request,
            time_range=resolved_time_range,
        ):
            payload.trace["l1_always_injected"] = True

        if self._inject_temporal_l2_plan(
            augmented_plans,
            request=request,
            time_range=resolved_time_range,
        ):
            payload.trace["l2_temporal_injected"] = True

        return augmented_plans

    def _add_joint_l1_evidence_plans(
        self,
        *,
        primary_plans: list[LayerQueryPlan],
        augmented_plans: list[LayerQueryPlan],
        seen_signatures: set[tuple[str, str, bool]],
        request: RetrievalQuery,
    ) -> bool:
        added_plan = False
        for plan in primary_plans:
            joint_l1_plan = self._build_joint_l1_evidence_plan(plan, request=request)
            if joint_l1_plan is None:
                continue
            signature = self._plan_signature(joint_l1_plan)
            if signature in seen_signatures:
                continue
            augmented_plans.append(joint_l1_plan)
            seen_signatures.add(signature)
            added_plan = True
        return added_plan

    @staticmethod
    def _ensure_l1_plan(
        augmented_plans: list[LayerQueryPlan],
        *,
        request: RetrievalQuery,
        time_range: TimeRange | None,
    ) -> bool:
        if any(plan.layer == "L1" for plan in augmented_plans):
            return False
        augmented_plans.append(_base_l1_plan(request, time_range=time_range))
        return True

    @staticmethod
    def _inject_temporal_l2_plan(
        augmented_plans: list[LayerQueryPlan],
        *,
        request: RetrievalQuery,
        time_range: TimeRange | None,
    ) -> bool:
        if any(plan.layer == "L2" for plan in augmented_plans):
            return False
        if time_range is None and not request.time_range and not has_temporal_anchor(
            request.query
        ):
            return False
        augmented_plans.append(_temporal_l2_plan(request, time_range=time_range))
        return True

    @staticmethod
    def _build_joint_l1_evidence_plan(
        plan: LayerQueryPlan,
        *,
        request: RetrievalQuery,
    ) -> LayerQueryPlan | None:
        """Build an auxiliary L1 evidence plan for time-bounded interaction affinity queries."""
        if plan.layer != "L2" or not isinstance(plan.conditions, L2Conditions):
            return None

        semantic_frame = plan.conditions.semantic_frame
        if semantic_frame is None:
            return None
        if semantic_frame.query_family != "affinity":
            return None
        if not any(constraint.scope == "interaction" for constraint in semantic_frame.constraints):
            return None
        if plan.time_range is None or (plan.time_range.start is None and plan.time_range.end is None):
            return None

        return LayerQueryPlan(
            layer="L1",
            conditions=L1Conditions(
                content_query=request.query,
                source_filters=request.source_filters or None,
                domain_filters=request.domain_filters or None,
                context_scope=dict(request.context_scope or {}),
                limit=request.limit,
            ),
            time_range=plan.time_range,
            is_fallback=False,
        )


def _base_l1_plan(
    request: RetrievalQuery,
    *,
    time_range: TimeRange | None,
) -> LayerQueryPlan:
    return LayerQueryPlan(
        layer="L1",
        conditions=L1Conditions(
            content_query=request.query,
            source_filters=request.source_filters or None,
            domain_filters=request.domain_filters or None,
            context_scope=dict(request.context_scope or {}),
            limit=request.limit,
        ),
        time_range=time_range,
        is_fallback=False,
    )


def _apply_request_constraints(
    plans: list[LayerQueryPlan],
    *,
    request: RetrievalQuery,
    time_range: TimeRange | None,
) -> None:
    """Apply caller-owned time and correction scope to every primary plan."""
    for plan in plans:
        if plan.time_range is None:
            plan.time_range = time_range
        if isinstance(plan.conditions, (L1Conditions, L2Conditions)):
            plan.conditions.context_scope = dict(request.context_scope or {})


def _temporal_l2_plan(
    request: RetrievalQuery,
    *,
    time_range: TimeRange | None,
) -> LayerQueryPlan:
    l2_conditions = L2Conditions(
        content_query=request.query,
        subject_hint="self",
        context_scope=dict(request.context_scope or {}),
        include_tom_snapshot=True,
        include_relationships=True,
        include_assertions=True,
    )
    enrich_l2_conditions(l2_conditions, request.query)
    _apply_l2_evidence_focus_fallback(l2_conditions, request.query)
    return LayerQueryPlan(
        layer="L2",
        conditions=l2_conditions,
        time_range=time_range,
        is_fallback=False,
    )


def _resolved_augmentation_time_range(
    primary_plans: list[LayerQueryPlan],
    *,
    request: RetrievalQuery,
    time_range: TimeRange | None,
) -> TimeRange | None:
    if time_range is not None:
        return time_range
    for plan in primary_plans:
        if plan.time_range is not None:
            return plan.time_range
    if request.time_range:
        return parse_time_range(request.query, request.time_range)
    return None


def _apply_l2_evidence_focus_fallback(
    l2_conditions: L2Conditions,
    query: str,
) -> None:
    if l2_conditions.allowed_evidence_classes is not None:
        return
    focused = classes_from_focus(infer_evidence_focus_heuristic(query))
    if focused is not None:
        l2_conditions.allowed_evidence_classes = focused
        l2_conditions.evidence_focus_source = "rule_heuristic"
        return
    inferred = infer_allowed_evidence_classes(
        predicate_family=l2_conditions.predicate_family,
        subject_scope=l2_conditions.subject_hint,
    )
    if inferred is not None:
        l2_conditions.allowed_evidence_classes = inferred
        l2_conditions.evidence_focus_source = "family_fallback"


__all__ = ["HybridRetrievalPlanAugmentationMixin"]
