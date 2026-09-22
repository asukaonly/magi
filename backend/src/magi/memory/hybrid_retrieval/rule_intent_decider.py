"""Rule-based intent routing for hybrid memory retrieval."""

from __future__ import annotations

from typing import Optional

from .intent_time import parse_raw_time_range
from .mode_registry import MODE_REGISTRY
from .models import (
    IntentDeciderInput,
    IntentDecision,
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    TimeRange,
)

class RuleBasedIntentDecider:
    """Host-owned plan construction from typed intent and caller constraints."""

    def evaluate(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce a full intent decision from rules alone."""
        time_range = parse_raw_time_range(inp.raw_time_range) if inp.raw_time_range is not None else None
        plans = self._route_layers(inp)

        for plan in plans:
            plan.time_range = time_range

        return IntentDecision(
            plans=plans,
            time_range=time_range,
            reasoning=self._build_reasoning(plans, time_range),
            source="rule_fallback",
            query_mode=inp.query_mode_hint if inp.query_mode_hint in MODE_REGISTRY else "exact_fact",
        )

    def _route_layers(self, inp: IntentDeciderInput) -> list[LayerQueryPlan]:
        """Determine which layers to query."""
        mode = inp.query_mode_hint
        if not mode or mode not in MODE_REGISTRY:
            mode = "exact_fact"

        plan_def = MODE_REGISTRY[mode]

        plans: list[LayerQueryPlan] = []
        for layer in plan_def.primary_layers:
            plans.append(self._make_plan(layer, inp, is_fallback=False, mode=mode))
        for layer in plan_def.fallback_layers:
            if layer not in plan_def.primary_layers:
                plans.append(self._make_plan(layer, inp, is_fallback=True, mode=mode))

        return plans

    def _make_plan(
        self,
        layer: str,
        inp: IntentDeciderInput,
        *,
        is_fallback: bool,
        mode: str | None = None,
        source_filters: Optional[list[str]] = None,
        domain_filters: Optional[list[str]] = None,
    ) -> LayerQueryPlan:
        """Create a LayerQueryPlan for the given layer."""
        final_sources = source_filters or inp.source_filters or None
        final_domains = domain_filters or inp.domain_filters or None

        if layer == "L1":
            conditions = L1Conditions(
                content_query=inp.query,
                source_filters=final_sources,
                domain_filters=final_domains,
                context_scope=dict(inp.context_scope or {}),
                limit=inp.l1_limit,
            )
        elif layer == "L2":
            conditions = L2Conditions(
                content_query=inp.query,
                context_scope=dict(inp.context_scope or {}),
                include_tom_snapshot=True,
                include_relationships=True,
                include_assertions=True,
                include_episodes=False,
                include_experiences=mode in {"episode_recall", "experience_recall"},
            )
        elif layer == "L3":
            conditions = L3Conditions(
                content_query=inp.query,
                summary_categories=list(inp.summary_categories) if inp.summary_categories else None,
                limit=5,
            )
        elif layer == "L4":
            conditions = L4Conditions(
                content_query=inp.query,
                limit=5,
            )
        else:
            conditions = L1Conditions(content_query=inp.query)

        return LayerQueryPlan(layer=layer, conditions=conditions, is_fallback=is_fallback)

    def _infer_source_domain(
        self,
        query_lower: str,
        inp: IntentDeciderInput,
    ) -> tuple[Optional[list[str]], Optional[list[str]]]:
        """Return caller-provided source/domain filters, or (None, None)."""
        if inp.source_filters or inp.domain_filters:
            return inp.source_filters or None, inp.domain_filters or None
        return None, None

    def _build_reasoning(
        self,
        plans: list[LayerQueryPlan],
        time_range: Optional[TimeRange],
    ) -> str:
        layers = [f"{p.layer}({'fallback' if p.is_fallback else 'primary'})" for p in plans]
        parts = [f"layers={'+'.join(layers)}"]
        if time_range and (time_range.start or time_range.end):
            parts.append(f"time_range=[{time_range.start}, {time_range.end}]")
        return ", ".join(parts)



__all__ = ["RuleBasedIntentDecider"]
