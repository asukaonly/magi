"""Rule-based intent routing for hybrid memory retrieval."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .evidence_routing import (
    classes_from_focus,
    infer_allowed_evidence_classes,
    infer_evidence_focus_heuristic,
)
from .intent_time import (
    day_range,
    end_of_day,
    month_range,
    parse_raw_time_range,
    parse_time_from_query,
    parse_time_range,
    range_from_match,
    start_of_day,
    try_chinese_temporal,
)
from .l2_intent import enrich_l2_conditions
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

_SUMMARY_MODE_KEYWORDS = (
    "总结",
    "汇总",
    "概括",
    "回顾",
    "summary",
    "summarize",
    "recap",
    "digest",
)


class RuleBasedIntentDecider:
    """Rule-based intent decider with time parsing and keyword routing."""

    def evaluate(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce a full intent decision from rules alone."""
        time_range = self._parse_time_range(inp.query, inp.raw_time_range)
        plans = self._route_layers(inp)

        for plan in plans:
            plan.time_range = time_range

        return IntentDecision(
            plans=plans,
            time_range=time_range,
            reasoning=self._build_reasoning(plans, time_range),
            source="rule_fallback",
        )

    def _parse_time_range(
        self,
        query: str,
        raw_time_range: Optional[Dict[str, Any]],
    ) -> Optional[TimeRange]:
        """Extract time range from query keywords and raw_time_range."""
        return parse_time_range(query, raw_time_range)

    def _parse_raw_time_range(self, raw: Dict[str, Any]) -> Optional[TimeRange]:
        """Parse raw_time_range dict passed by caller."""
        return parse_raw_time_range(raw)

    def _parse_time_from_query(self, query: str) -> Optional[TimeRange]:
        """Parse time expressions from natural language query."""
        return parse_time_from_query(query)

    def _try_chinese_temporal(self, query: str, now: Any) -> Optional[TimeRange]:
        """Extract and resolve Chinese temporal expressions."""
        return try_chinese_temporal(query, now)

    def _range_from_match(self, matched_text: str, resolved_dt: Any, now: Any) -> TimeRange:
        """Infer an appropriate time range from a dateparser match."""
        return range_from_match(matched_text, resolved_dt, now)

    def _route_layers(self, inp: IntentDeciderInput) -> list[LayerQueryPlan]:
        """Determine which layers to query."""
        mode = inp.query_mode_hint
        if not mode or mode not in MODE_REGISTRY:
            mode = _infer_default_query_mode(inp.query)

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
                limit=inp.l1_limit,
            )
        elif layer == "L2":
            conditions = L2Conditions(
                content_query=inp.query,
                include_tom_snapshot=True,
                include_relationships=True,
                include_assertions=True,
                include_episodes=False,
                include_experiences=mode in {"episode_recall", "experience_recall"},
            )
            enrich_l2_conditions(conditions, inp.query)
            if conditions.allowed_evidence_classes is None:
                focused = classes_from_focus(infer_evidence_focus_heuristic(inp.query))
                if focused is not None:
                    conditions.allowed_evidence_classes = focused
                    conditions.evidence_focus_source = "rule_heuristic"
                else:
                    inferred = infer_allowed_evidence_classes(
                        predicate_family=conditions.predicate_family,
                        subject_scope=conditions.subject_hint,
                    )
                    if inferred is not None:
                        conditions.allowed_evidence_classes = inferred
                        conditions.evidence_focus_source = "family_fallback"
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

    @staticmethod
    def _day_range(dt: Any) -> TimeRange:
        return day_range(dt)

    @staticmethod
    def _month_range(*, year: int, month: int, now: Any) -> TimeRange:
        return month_range(year=year, month=month, now=now)

    @staticmethod
    def _start_of_day(dt: Any) -> float:
        return start_of_day(dt)

    @staticmethod
    def _end_of_day(dt: Any) -> float:
        return end_of_day(dt)


def _infer_default_query_mode(query: str) -> str:
    lowered = query.lower()
    if any(keyword in lowered for keyword in _SUMMARY_MODE_KEYWORDS):
        return "summary"
    return "exact_fact"


__all__ = ["RuleBasedIntentDecider", "_infer_default_query_mode"]
