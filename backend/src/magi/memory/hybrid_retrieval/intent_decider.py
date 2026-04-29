"""Intent decider for hybrid memory retrieval.

Provides rule-based and LLM-based intent analysis to determine which
memory layers to query and under what conditions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
from .l2_intent import enrich_l2_conditions
from .llm_intent import LLMIntentDecider, LLMRefinement
from .mode_registry import MODE_REGISTRY
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


logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# RuleBasedIntentDecider
# ---------------------------------------------------------------------------


class RuleBasedIntentDecider:
    """Rule-based intent decider with time parsing and keyword routing."""

    def evaluate(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce a full intent decision from rules alone."""
        time_range = self._parse_time_range(inp.query, inp.raw_time_range)
        plans = self._route_layers(inp)

        # Apply time_range to all plans
        for plan in plans:
            plan.time_range = time_range

        return IntentDecision(
            plans=plans,
            time_range=time_range,
            reasoning=self._build_reasoning(plans, time_range),
            source="rule_fallback",
        )

    # -----------------------------------------------------------------------
    # Time range parsing
    # -----------------------------------------------------------------------

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
        """Parse time expressions from natural language query.

        Uses a hybrid strategy:
        1. Chinese-specific regex extraction → ``dateparser.parse()``
        2. ``dateparser.search.search_dates()`` for English (and simple Chinese)
        3. Range-width heuristics via ``_range_from_match``
        """
        return parse_time_from_query(query)

    # -----------------------------------------------------------------------
    # Chinese temporal extraction
    # -----------------------------------------------------------------------

    def _try_chinese_temporal(
        self, query: str, now: Any,
    ) -> Optional[TimeRange]:
        """Extract and resolve Chinese temporal expressions.

        ``dateparser.search_dates`` misses many Chinese relative patterns
        (e.g. "N天前", "上周三", "3月10号").  This method detects them via
        lightweight regex, then resolves via ``dateparser.parse()`` where
        possible and manual calculation otherwise.
        """
        return try_chinese_temporal(query, now)

    # -----------------------------------------------------------------------
    # Range width heuristics
    # -----------------------------------------------------------------------

    def _range_from_match(
        self, matched_text: str, resolved_dt: Any, now: Any,
    ) -> TimeRange:
        """Infer an appropriate time range from a dateparser match.

        Uses simple heuristics on *matched_text* to decide whether the
        expression refers to an hour, day, week, or month window.
        """
        return range_from_match(matched_text, resolved_dt, now)

    # -----------------------------------------------------------------------
    # Layer routing
    # -----------------------------------------------------------------------

    def _route_layers(self, inp: IntentDeciderInput) -> list[LayerQueryPlan]:
        """Determine which layers to query.

        Routing is handled by the LLM intent decider when available.
        The rule engine uses ``query_mode`` hint from the caller and
        the MODE_REGISTRY for routing.  Defaults to ``exact_fact``.
        """
        mode = inp.query_mode_hint
        if not mode or mode not in MODE_REGISTRY:
            mode = _infer_default_query_mode(inp.query)

        plan_def = MODE_REGISTRY[mode]

        plans: list[LayerQueryPlan] = []
        for layer in plan_def.primary_layers:
            plans.append(self._make_plan(layer, inp, is_fallback=False))
        for layer in plan_def.fallback_layers:
            if layer not in plan_def.primary_layers:
                plans.append(self._make_plan(layer, inp, is_fallback=True))

        return plans

    def _make_plan(
        self,
        layer: str,
        inp: IntentDeciderInput,
        *,
        is_fallback: bool,
        source_filters: Optional[list[str]] = None,
        domain_filters: Optional[list[str]] = None,
    ) -> LayerQueryPlan:
        """Create a LayerQueryPlan for the given layer."""
        # Merge inferred filters with caller-passed filters
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
            )
            enrich_l2_conditions(
                conditions, inp.query,
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

    # -----------------------------------------------------------------------
    # Source/domain inference
    # -----------------------------------------------------------------------

    def _infer_source_domain(
        self,
        query_lower: str,
        inp: IntentDeciderInput,
    ) -> tuple[Optional[list[str]], Optional[list[str]]]:
        """Return caller-provided source/domain filters, or (None, None)."""
        if inp.source_filters or inp.domain_filters:
            return inp.source_filters or None, inp.domain_filters or None
        return None, None

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Combined IntentDecider (LLM primary + rule shadow)
# ---------------------------------------------------------------------------


@dataclass
class EvaluationRecord:
    """Shadow evaluation record for logging."""

    query: str
    user_id: Optional[str]
    session_id: Optional[str]
    rule_decision: IntentDecision
    llm_refinement: Optional[LLMRefinement]
    final_decision: IntentDecision
    decision_source: str
    llm_latency_ms: Optional[float]
    llm_error: Optional[str]
    refinement_applied: bool
    diff_summary: str


def compute_diff(
    rule_decision: IntentDecision,
    llm_refinement: Optional[LLMRefinement],
) -> tuple[bool, str]:
    """Summarise whether the LLM produced a usable refinement.

    Layer routing is rule-canonical (driven by ``query_mode``); only
    retrieval refinements come from the LLM. The returned bool indicates
    whether refinements were applied.
    """
    if llm_refinement is None:
        return False, "llm_failed"

    parts: list[str] = []
    rule_content_query = (
        rule_decision.plans[0].conditions.content_query if rule_decision.plans else ""
    )
    if llm_refinement.content_query and llm_refinement.content_query != rule_content_query:
        parts.append("content_query")
    if llm_refinement.entities is not None:
        parts.append("entities")
    if llm_refinement.subject_hint is not None:
        parts.append("subject_hint")
    if llm_refinement.predicate_family is not None:
        parts.append("predicate_family")
    if llm_refinement.semantic_frame is not None:
        parts.append("semantic_frame")
    summary = "applied: " + ",".join(parts) if parts else "applied: empty"
    return True, summary


class IntentDecider:
    """Combined intent decider: LLM primary + rule shadow + evaluation logging."""

    def __init__(
        self,
        *,
        rule_engine: RuleBasedIntentDecider,
        llm_decider: Optional[LLMIntentDecider] = None,
        llm_enabled: bool = True,
        shadow_eval_enabled: bool = True,
        eval_callback: Optional[Any] = None,
    ):
        self._rule_engine = rule_engine
        self._llm_decider = llm_decider
        self._llm_enabled = llm_enabled and llm_decider is not None
        self._shadow_eval_enabled = shadow_eval_enabled
        self._eval_callback = eval_callback  # async callable(EvaluationRecord)
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def decide(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce final intent decision: rule-canonical routing + LLM refinements."""
        # 1. Rule layer always runs (sync) — owns layer routing + time parsing.
        rule_decision = self._rule_engine.evaluate(inp)

        # 2. LLM refinement (best-effort).
        llm_refinement: Optional[LLMRefinement] = None
        llm_latency_ms: Optional[float] = None
        llm_error: Optional[str] = None

        if self._llm_enabled and self._llm_decider is not None:
            t0 = time.monotonic()
            try:
                llm_refinement = await self._llm_decider.evaluate(inp)
            except Exception as exc:
                llm_error = str(exc)
                logger.warning("LLM intent decider error: %s", exc)
            llm_latency_ms = (time.monotonic() - t0) * 1000

        # 3. Determine final decision.
        if llm_refinement is not None and self._llm_decider is not None:
            final_decision = self._llm_decider.apply(
                original_query=inp.query,
                rule_decision=rule_decision,
                refinement=llm_refinement,
            )
            decision_source = "llm"
        else:
            final_decision = rule_decision
            decision_source = "rule_fallback"

        final_decision.source = decision_source

        # 4. Shadow evaluation (async, non-blocking)
        if self._shadow_eval_enabled and self._eval_callback is not None:
            refinement_applied, diff_summary = compute_diff(rule_decision, llm_refinement)
            record = EvaluationRecord(
                query=inp.query,
                user_id=inp.user_id,
                session_id=inp.session_id,
                rule_decision=rule_decision,
                llm_refinement=llm_refinement,
                final_decision=final_decision,
                decision_source=decision_source,
                llm_latency_ms=llm_latency_ms,
                llm_error=llm_error,
                refinement_applied=refinement_applied,
                diff_summary=diff_summary,
            )
            task = asyncio.create_task(self._safe_log(record))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return final_decision

    async def _safe_log(self, record: EvaluationRecord) -> None:
        """Log evaluation, swallowing errors."""
        try:
            await self._eval_callback(record)
        except Exception:
            logger.debug("Shadow eval logging error", exc_info=True)
