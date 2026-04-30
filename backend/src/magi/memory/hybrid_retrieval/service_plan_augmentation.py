"""Primary plan augmentation helpers for hybrid retrieval service queries."""

from __future__ import annotations

from typing import Any

from .answerability import has_temporal_anchor
from .intent_decider import enrich_l2_conditions
from .models import L1Conditions, L2Conditions, LayerQueryPlan, RetrievalPayload, RetrievalQuery
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
    ) -> list[LayerQueryPlan]:
        """Add service-level evidence plans for semantic affinity queries when needed."""
        seen_signatures = {self._plan_signature(plan) for plan in primary_plans}
        augmented_plans = list(primary_plans)
        added_joint_l1_plan = False

        for plan in primary_plans:
            joint_l1_plan = self._build_joint_l1_evidence_plan(plan, request=request)
            if joint_l1_plan is None:
                continue
            signature = self._plan_signature(joint_l1_plan)
            if signature in seen_signatures:
                continue
            augmented_plans.append(joint_l1_plan)
            seen_signatures.add(signature)
            added_joint_l1_plan = True

        if added_joint_l1_plan:
            payload.trace["joint_l1_affinity_evidence"] = True

        has_l1 = any(p.layer == "L1" for p in augmented_plans)
        if not has_l1:
            l1_plan = LayerQueryPlan(
                layer="L1",
                conditions=L1Conditions(
                    content_query=request.query,
                    source_filters=request.source_filters or None,
                    domain_filters=request.domain_filters or None,
                    limit=request.limit,
                ),
                is_fallback=False,
            )
            augmented_plans.append(l1_plan)
            payload.trace["l1_always_injected"] = True

        has_l2 = any(p.layer == "L2" for p in augmented_plans)
        if not has_l2 and has_temporal_anchor(request.query):
            l2_conditions = L2Conditions(
                content_query=request.query,
                subject_hint="self",
                include_tom_snapshot=True,
                include_relationships=True,
                include_assertions=True,
            )
            enrich_l2_conditions(l2_conditions, request.query)
            l2_plan = LayerQueryPlan(
                layer="L2",
                conditions=l2_conditions,
                is_fallback=False,
            )
            augmented_plans.append(l2_plan)
            payload.trace["l2_temporal_injected"] = True

        return augmented_plans

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
                limit=request.limit,
            ),
            time_range=plan.time_range,
            is_fallback=False,
        )


__all__ = ["HybridRetrievalPlanAugmentationMixin"]
