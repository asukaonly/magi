"""Intent decider for hybrid memory retrieval.

Provides rule-based and LLM-based intent analysis to determine which
memory layers to query and under what conditions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .answerability import (
    extract_comparison_spans,
    extract_query_tokens,
    extract_quoted_spans,
)
from .models import (
    IntentDeciderInput,
    IntentDecision,
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    SemanticConstraint,
    TimeRange,
)
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

_VALID_SUBJECT_HINTS = {"self", "explicit", "none"}
_VALID_PREDICATE_FAMILIES = {"preference", "relationship", "profile_fact", "activity", "unknown"}
_VALID_QUERY_FAMILIES = {"affinity", "relationship", "profile", "activity", "lookup"}
_VALID_ANSWER_KINDS = {"creator", "place", "topic", "person", "software", "unknown"}
_VALID_ANSWER_UNITS = {"identity", "presence", "place", "topic", "mixed"}
_VALID_CONSTRAINT_SCOPES = {"target", "interaction"}
_VALID_CONSTRAINT_FACETS = {"platform", "located_in", "category"}
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


# ---------------------------------------------------------------------------
# L2 condition enrichment (shared by rule engine and LLM post-processing)
# ---------------------------------------------------------------------------


def enrich_l2_conditions(
    conditions: L2Conditions,
    query: str,
) -> None:
    """Fill missing L2 structural fields using rule-based inference.

    Modifies *conditions* in-place.  Only fills fields that are still at
    their default/empty values so that explicitly-set values are preserved.
    """
    if not conditions.entities:
        conditions.entities = None

    if not conditions.subject_hint or conditions.subject_hint == "none":
        family = conditions.predicate_family or "unknown"
        if family == "unknown":
            family = _infer_predicate_family(query)
            conditions.predicate_family = family
        if family in {"preference", "profile_fact"}:
            conditions.subject_hint = "self"
        else:
            conditions.subject_hint = "none"

    if not conditions.predicate_family or conditions.predicate_family == "unknown":
        conditions.predicate_family = _infer_predicate_family(query)

    if conditions.semantic_frame is None:
        conditions.semantic_frame = _infer_semantic_frame(
            query=query,
            subject_hint=conditions.subject_hint or "none",
            predicate_family=conditions.predicate_family or "unknown",
        )


def _infer_default_query_mode(query: str) -> str:
    lowered = query.lower()
    if any(keyword in lowered for keyword in _SUMMARY_MODE_KEYWORDS):
        return "summary"
    return "exact_fact"


def _infer_predicate_family(
    query: str,
) -> str:
    """Infer the broad predicate family for L2 graph planning.

    Uses minimal keyword heuristics.  The LLM intent decider handles
    richer classification.
    """
    lowered = query.lower()
    _PREFERENCE_KW = (
        "喜欢", "讨厌", "偏好", "偏爱", "感兴趣", "关注",
        "like", "dislike", "prefer", "favorite", "interested",
        "follow", "hate",
    )
    if any(kw in lowered for kw in _PREFERENCE_KW):
        return "preference"
    _RELATIONSHIP_KW = (
        "关系", "约定", "认识",
        "relationship", "agreement", "know",
    )
    if any(kw in lowered for kw in _RELATIONSHIP_KW):
        return "relationship"
    _PROFILE_KW = (
        "默认", "设置", "工作目录", "常用",
        "default", "setting", "workspace", "configuration",
    )
    if any(kw in lowered for kw in _PROFILE_KW):
        return "profile_fact"
    return "unknown"


def _infer_semantic_frame(
    *,
    query: str,
    subject_hint: str,
    predicate_family: str,
) -> L2SemanticFrame | None:
    """Infer a minimal semantic frame for L2 graph search."""
    query_family = _infer_query_family(predicate_family)
    if query_family == "lookup":
        return None

    return L2SemanticFrame(
        query_family=query_family,
        subject_scope=subject_hint if subject_hint in _VALID_SUBJECT_HINTS else "none",
        answer_kind="unknown",
        answer_unit="mixed",
        entity_mentions=[],
        constraints=[],
        ranking_mode="affinity" if query_family == "affinity" else "confidence",
    )


def _infer_query_family(predicate_family: str) -> str:
    if predicate_family == "preference":
        return "affinity"
    if predicate_family == "relationship":
        return "relationship"
    if predicate_family == "profile_fact":
        return "profile"
    if predicate_family == "activity":
        return "activity"
    return "lookup"





# ---------------------------------------------------------------------------
# LLMIntentDecider
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are a fast memory-retrieval refinement agent.

The host has already chosen which memory layers to query (L1/L2/L3/L4) based on the
caller's ``query_mode``. Your job is to **refine** the retrieval inputs that will be
applied to those layers, not to re-decide the routing.

You produce a single refinement object that is applied to every routed plan:

- ``content_query``: the answer-oriented retrieval phrase. Must match the user's
  query language. Do not hallucinate, do not expand with invented details, do not
  replace quoted titles with broad topics. Keep it tight.
- ``entities`` (optional, L2): proper-noun mentions in the query.
- ``subject_hint`` (optional, L2): "self" when the user is asking about themselves,
  "explicit" when an entity is mentioned, "none" otherwise.
- ``predicate_family`` (optional, L2): one of ``preference``, ``profile_fact``,
  ``relationship``, ``activity``, ``unknown``.
- ``semantic_frame`` (optional, L2): structured query semantics with the schema:
    {
      "query_family": "affinity" | "relationship" | "profile" | "activity" | "lookup",
      "subject_scope": "self" | "explicit" | "none",
      "answer_kind": "creator" | "place" | "topic" | "person" | "software" | "unknown",
      "answer_unit": "identity" | "presence" | "place" | "topic" | "mixed",
      "entity_mentions": [string, ...],
      "constraints": [{"scope": "target"|"interaction",
                       "facet": "platform"|"located_in"|"category",
                       "raw_value": string,
                       "resolved_entity_id": string?,
                       "resolved_facet_value": string?}],
      "ranking_mode": "confidence" | string
    }
- ``reasoning``: brief one-sentence explanation.

Rules:
- Time range parsing is handled elsewhere. Do not output time ranges.
- Layer routing is handled elsewhere. Do not output a ``layers`` array.
- For comparison questions ("X 还是 Y"), keep both candidates explicit in
  ``content_query``.
- Keep quoted titles verbatim.

Return JSON only:
{
  "content_query": "string",
  "entities": ["string", ...],
  "subject_hint": "self" | "explicit" | "none",
  "predicate_family": "preference" | "profile_fact" | "relationship" | "activity" | "unknown",
  "semantic_frame": { ... } | null,
  "reasoning": "string"
}"""

_VALID_LAYERS = {"L1", "L2", "L3", "L4"}

_VALID_CONSTRAINT_SCOPES = {"target", "interaction"}
_VALID_CONSTRAINT_FACETS = {"platform", "located_in", "category"}


@dataclass
class LLMRefinement:
    """Flat retrieval-refinement object produced by :class:`LLMIntentDecider`.

    The host's rule engine owns layer routing — this object only refines
    *how* each routed layer is queried. Fields are optional and applied
    selectively per layer (e.g. ``entities`` and ``semantic_frame`` only
    affect L2 plans).
    """

    content_query: str = ""
    entities: Optional[list[str]] = None
    subject_hint: Optional[str] = None
    predicate_family: Optional[str] = None
    semantic_frame: Optional[L2SemanticFrame] = None
    reasoning: str = ""


def _parse_semantic_frame(raw: dict | None) -> L2SemanticFrame | None:
    """Parse an LLM-returned semantic_frame dict into a typed dataclass."""
    if not raw or not isinstance(raw, dict):
        return None
    try:
        constraints: list[SemanticConstraint] = []
        for c in raw.get("constraints") or []:
            if not isinstance(c, dict):
                continue
            scope = c.get("scope", "")
            facet = c.get("facet", "")
            if scope not in _VALID_CONSTRAINT_SCOPES or facet not in _VALID_CONSTRAINT_FACETS:
                continue
            constraints.append(SemanticConstraint(
                scope=scope,
                facet=facet,
                raw_value=c.get("raw_value", ""),
                resolved_entity_id=c.get("resolved_entity_id"),
                resolved_facet_value=c.get("resolved_facet_value"),
            ))
        return L2SemanticFrame(
            query_family=raw.get("query_family", "lookup"),
            subject_scope=raw.get("subject_scope", "none"),
            answer_kind=raw.get("answer_kind", "unknown"),
            answer_unit=raw.get("answer_unit", "mixed"),
            entity_mentions=raw.get("entity_mentions") or [],
            constraints=constraints,
            ranking_mode=raw.get("ranking_mode", "confidence"),
        )
    except (TypeError, KeyError):
        return None


class LLMIntentDecider:
    """LLM-based retrieval refinement.

    The rule engine owns layer routing (driven by the caller's
    ``query_mode``); this decider contributes *retrieval refinements*
    (``content_query``, ``entities``, ``subject_hint``,
    ``predicate_family``, ``semantic_frame``) that are applied onto the
    rule-routed plans.
    """

    def __init__(self, provider_bridge: Any, *, timeout_seconds: float = 3.0):
        self._bridge = provider_bridge
        self._timeout = timeout_seconds

    async def evaluate(self, inp: IntentDeciderInput) -> LLMRefinement | None:
        """Call the LLM for retrieval refinements. Returns ``None`` on any failure."""
        prompt_lines = [f"user query: {inp.query}"]
        if inp.query_mode_hint:
            prompt_lines.append(f"query_mode_hint: {inp.query_mode_hint}")
        if inp.source_filters:
            prompt_lines.append(f"source_filters_hint: {json.dumps(inp.source_filters, ensure_ascii=False)}")
        if inp.domain_filters:
            prompt_lines.append(f"domain_filters_hint: {json.dumps(inp.domain_filters, ensure_ascii=False)}")
        user_prompt = "\n".join(prompt_lines)
        model = getattr(getattr(self._bridge, "llm", None), "model_name", "unknown")
        base_url = str(getattr(getattr(self._bridge, "llm", None), "base_url", "unknown"))
        t0 = time.monotonic()
        try:
            raw = await self._bridge.chat(
                system_prompt=_LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=512,
                temperature=0.3,
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=self._timeout,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "LLM intent decider completed model=%s base_url=%s elapsed_ms=%.1f timeout=%s prompt_len=%d",
                model, base_url, elapsed_ms, self._timeout, len(user_prompt),
            )
            return self._parse_response(raw)
        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "LLM intent decider failed model=%s base_url=%s elapsed_ms=%.1f timeout=%s prompt_len=%d"
                "\n  disable_thinking=True json_mode=True max_tokens=512 temperature=0.3"
                "\n  system_prompt:\n%s"
                "\n  user_prompt:\n%s",
                model, base_url, elapsed_ms, self._timeout, len(user_prompt),
                _LLM_SYSTEM_PROMPT, user_prompt,
                exc_info=True,
            )
            return None

    def _parse_response(self, raw: str) -> LLMRefinement | None:
        """Parse the LLM JSON response into a :class:`LLMRefinement`."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM intent decider returned invalid JSON")
            return None
        if not isinstance(data, dict):
            return None

        content_query = str(data.get("content_query") or "").strip()
        entities_raw = data.get("entities")
        entities: Optional[list[str]] = None
        if isinstance(entities_raw, list):
            entities = [str(e) for e in entities_raw if isinstance(e, (str, int, float))]
            entities = [e for e in entities if e]
            if not entities:
                entities = None

        subject_hint_raw = data.get("subject_hint")
        subject_hint = (
            str(subject_hint_raw)
            if isinstance(subject_hint_raw, str) and subject_hint_raw in _VALID_SUBJECT_HINTS
            else None
        )

        predicate_family_raw = data.get("predicate_family")
        predicate_family = (
            str(predicate_family_raw)
            if isinstance(predicate_family_raw, str) and predicate_family_raw in _VALID_PREDICATE_FAMILIES
            else None
        )

        semantic_frame = _parse_semantic_frame(data.get("semantic_frame"))
        reasoning = str(data.get("reasoning") or "")

        if not content_query and entities is None and semantic_frame is None:
            # Nothing useful came back; let caller fall through to rule output.
            return None

        return LLMRefinement(
            content_query=content_query,
            entities=entities,
            subject_hint=subject_hint,
            predicate_family=predicate_family,
            semantic_frame=semantic_frame,
            reasoning=reasoning,
        )

    def apply(
        self,
        *,
        original_query: str,
        rule_decision: IntentDecision,
        refinement: LLMRefinement,
    ) -> IntentDecision:
        """Apply ``refinement`` onto the rule-routed plans.

        - ``content_query`` is overlaid on every plan, after L1 validation.
        - ``entities`` / ``subject_hint`` / ``predicate_family`` /
          ``semantic_frame`` only affect L2 plans.
        - The decision's ``reasoning`` is augmented with the LLM's reasoning.
        """
        refined_query = (refinement.content_query or "").strip()
        for plan in rule_decision.plans:
            conditions = plan.conditions
            if plan.layer == "L1" and isinstance(conditions, L1Conditions):
                conditions.content_query = self._validate_l1_content_query(
                    original_query=original_query,
                    content_query=refined_query or conditions.content_query,
                )
            elif plan.layer == "L2" and isinstance(conditions, L2Conditions):
                if refined_query:
                    conditions.content_query = refined_query
                if refinement.entities is not None:
                    conditions.entities = refinement.entities
                if refinement.subject_hint is not None:
                    conditions.subject_hint = refinement.subject_hint
                if refinement.predicate_family is not None:
                    conditions.predicate_family = refinement.predicate_family
                if refinement.semantic_frame is not None:
                    conditions.semantic_frame = refinement.semantic_frame
                enrich_l2_conditions(conditions, original_query)
            elif plan.layer == "L3" and isinstance(conditions, L3Conditions):
                if refined_query:
                    conditions.content_query = refined_query
            elif plan.layer == "L4" and isinstance(conditions, L4Conditions):
                if refined_query:
                    conditions.content_query = refined_query

        merged_reasoning = rule_decision.reasoning
        if refinement.reasoning:
            merged_reasoning = (
                f"{merged_reasoning}; llm: {refinement.reasoning}"
                if merged_reasoning
                else f"llm: {refinement.reasoning}"
            )
        rule_decision.reasoning = merged_reasoning
        rule_decision.source = "llm"
        return rule_decision

    @staticmethod
    def _validate_l1_content_query(*, original_query: str, content_query: str) -> str:
        """Rewrite clearly over-broad L1 queries back to the original user query."""
        normalized_query = str(original_query or "").strip()
        normalized_content_query = str(content_query or "").strip()
        if not normalized_query:
            return normalized_content_query
        if not normalized_content_query:
            return normalized_query

        content_tokens = set(extract_query_tokens(normalized_content_query))
        normalized_content = " ".join(extract_query_tokens(normalized_content_query))

        quoted_spans = extract_quoted_spans(normalized_query)
        if quoted_spans and not any(span and span in normalized_content for span in quoted_spans):
            return normalized_query

        comparison_spans = extract_comparison_spans(normalized_query)
        if comparison_spans:
            has_comparison_coverage = any(
                set(extract_query_tokens(span)).issubset(content_tokens)
                for span in comparison_spans
                if span
            )
            if not has_comparison_coverage:
                return normalized_query

        # Guard: reject LLM expansions that hallucinate too many novel tokens.
        # Extra AND terms in FTS5 make the query overly restrictive.
        _PREFIX_LEN = 5
        original_tokens = set(extract_query_tokens(normalized_query))
        if original_tokens:

            def _overlaps_original(tok: str) -> bool:
                for orig in original_tokens:
                    if tok == orig:
                        return True
                    if (
                        len(tok) >= _PREFIX_LEN
                        and len(orig) >= _PREFIX_LEN
                        and tok[:_PREFIX_LEN] == orig[:_PREFIX_LEN]
                    ):
                        return True
                return False

            novel_count = sum(1 for t in content_tokens if not _overlaps_original(t))
            if novel_count > len(original_tokens):
                return normalized_query

        return normalized_content_query


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
