"""Intent decider for hybrid memory retrieval.

Provides rule-based and LLM-based intent analysis to determine which
memory layers to query and under what conditions.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .answerability import (
    extract_comparison_spans,
    extract_query_tokens,
    extract_quoted_spans,
    extract_temporal_distance_queries,
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
from .rule_specs import (
    extract_entities,
    infer_answer_kind,
    infer_answer_shape,
    infer_polarity,
    infer_semantic_constraints,
    infer_source_domain_filters,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Time keyword patterns (Chinese + English)
# ---------------------------------------------------------------------------

_RELATIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "N天前" / "N days ago"
    (re.compile(r"(\d+)\s*天前", re.IGNORECASE), "days_ago"),
    (re.compile(r"(\d+)\s*days?\s*ago", re.IGNORECASE), "days_ago"),
    # "N小时前" / "N hours ago"
    (re.compile(r"(\d+)\s*小时前", re.IGNORECASE), "hours_ago"),
    (re.compile(r"(\d+)\s*hours?\s*ago", re.IGNORECASE), "hours_ago"),
    # "N周前" / "N weeks ago"
    (re.compile(r"(\d+)\s*周前", re.IGNORECASE), "weeks_ago"),
    (re.compile(r"(\d+)\s*weeks?\s*ago", re.IGNORECASE), "weeks_ago"),
    # "N个月前" / "N months ago"
    (re.compile(r"(\d+)\s*个?月前", re.IGNORECASE), "months_ago"),
    (re.compile(r"(\d+)\s*months?\s*ago", re.IGNORECASE), "months_ago"),
]

# Specific date patterns: "3月10号", "3月10日", "March 5th", "March 5"
_DATE_PATTERN_ZH = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]")
_DATE_PATTERN_EN = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?",
    re.IGNORECASE,
)
_MONTH_NAME_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Day-of-week mapping
_DAY_OF_WEEK_ZH = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "周天": 6}
_DAY_OF_WEEK_EN = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Static time keywords
_TIME_KEYWORDS: list[tuple[list[str], str]] = [
    (["昨天", "yesterday"], "yesterday"),
    (["前天", "day before yesterday"], "day_before_yesterday"),
    (["今天", "today"], "today"),
    (["这周", "本周", "this week"], "this_week"),
    (["上周", "last week"], "last_week"),
    (["上个月", "last month"], "last_month"),
    (["这个月", "本月", "this month"], "this_month"),
    (["最近", "recently", "近期"], "recently"),
]

# Mode -> layer mapping (for query_mode hint)
_MODE_LAYER_MAP: Dict[str, tuple[str, str]] = {
    "detail": ("L1", "L3"),
    "summary": ("L3", "L1"),
    "experience": ("L4", "L1"),
    "strategy": ("L4", "L1"),
    "graph": ("L2", "L1"),
}

_RECALL_INTENT_LAYER_MAP: Dict[str, tuple[str, str]] = {
    "event_recall": ("L1", "L3"),
    "preference_recall": ("L2", "L1"),
    "profile_fact_recall": ("L2", "L1"),
    "relationship_recall": ("L2", "L1"),
    "workflow_reuse": ("L4", "L1"),
}

_VALID_SUBJECT_HINTS = {"self", "explicit", "none"}
_VALID_PREDICATE_FAMILIES = {"preference", "relationship", "profile_fact", "activity", "unknown"}
_VALID_QUERY_FAMILIES = {"affinity", "relationship", "profile", "activity", "lookup"}
_VALID_ANSWER_KINDS = {"creator", "place", "topic", "person", "software", "unknown"}
_VALID_ANSWER_UNITS = {"identity", "presence", "place", "topic", "mixed"}
_VALID_ANSWER_SHAPES = {"list", "single", "boolean"}
_VALID_POLARITIES = {"positive", "negative", "neutral", "any"}
_VALID_CONSTRAINT_SCOPES = {"target", "interaction"}
_VALID_CONSTRAINT_FACETS = {"platform", "located_in", "category"}


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
        # 1. Explicit raw_time_range takes precedence
        if raw_time_range:
            parsed = self._parse_raw_time_range(raw_time_range)
            if parsed is not None:
                return parsed

        # 2. Parse from query text
        return self._parse_time_from_query(query)

    def _parse_raw_time_range(self, raw: Dict[str, Any]) -> Optional[TimeRange]:
        """Parse raw_time_range dict passed by caller."""
        if "start" in raw and "end" in raw:
            return TimeRange(start=float(raw["start"]), end=float(raw["end"]))

        if "relative" in raw:
            rel = str(raw["relative"]).strip().lower()
            now = time.time()
            # Parse "1d", "7d", "30d", "24h", "1w"
            m = re.match(r"(\d+)\s*([dhwm])", rel)
            if m:
                n, unit = int(m.group(1)), m.group(2)
                seconds = {"d": 86400, "h": 3600, "w": 604800, "m": 2592000}[unit]
                return TimeRange(start=now - n * seconds, end=now)

        return None

    def _parse_time_from_query(self, query: str) -> Optional[TimeRange]:
        """Parse time expressions from natural language query."""
        query_lower = query.lower()
        now = datetime.now(tz=timezone.utc)

        # 1. Check relative N-ago patterns first
        for pattern, kind in _RELATIVE_PATTERNS:
            m = pattern.search(query)
            if m:
                n = int(m.group(1))
                return self._resolve_n_ago(now, n, kind)

        # 2. Check "上周X" / "last Monday" style
        last_weekday = self._parse_last_weekday(query_lower, now)
        if last_weekday is not None:
            return last_weekday

        # 3. Check specific dates ("3月10号", "March 5th")
        specific_date = self._parse_specific_date(query, now)
        if specific_date is not None:
            return specific_date

        # 4. Check static keywords
        for keywords, kind in _TIME_KEYWORDS:
            if any(kw in query_lower for kw in keywords):
                return self._resolve_static_time(now, kind)

        return None

    def _resolve_n_ago(self, now: datetime, n: int, kind: str) -> TimeRange:
        if kind == "days_ago":
            target = now - timedelta(days=n)
            return self._day_range(target)
        if kind == "hours_ago":
            return TimeRange(
                start=(now - timedelta(hours=n)).timestamp(),
                end=now.timestamp(),
            )
        if kind == "weeks_ago":
            target = now - timedelta(weeks=n)
            monday = target - timedelta(days=target.weekday())
            sunday = monday + timedelta(days=6)
            return TimeRange(
                start=self._start_of_day(monday),
                end=self._end_of_day(sunday),
            )
        if kind == "months_ago":
            year = now.year
            month = now.month - n
            while month <= 0:
                month += 12
                year -= 1
            first_day = datetime(year, month, 1, tzinfo=timezone.utc)
            last_day_num = calendar.monthrange(year, month)[1]
            last_day = datetime(year, month, last_day_num, tzinfo=timezone.utc)
            return TimeRange(
                start=self._start_of_day(first_day),
                end=self._end_of_day(last_day),
            )
        return TimeRange()

    def _parse_last_weekday(self, query_lower: str, now: datetime) -> Optional[TimeRange]:
        """Parse '上周三' / 'last Wednesday' patterns."""
        # Chinese: "上周X"
        for day_name, weekday in _DAY_OF_WEEK_ZH.items():
            if f"上{day_name}" in query_lower:
                return self._last_week_day(now, weekday)

        # English: "last Monday" etc.
        for day_name, weekday in _DAY_OF_WEEK_EN.items():
            if f"last {day_name}" in query_lower:
                return self._last_week_day(now, weekday)

        return None

    def _last_week_day(self, now: datetime, target_weekday: int) -> TimeRange:
        """Get the date of a specific weekday in the previous week."""
        # Go to last week's Monday
        current_weekday = now.weekday()
        days_since_monday = current_weekday
        last_monday = now - timedelta(days=days_since_monday + 7)
        target_date = last_monday + timedelta(days=target_weekday)
        return self._day_range(target_date)

    def _parse_specific_date(self, query: str, now: datetime) -> Optional[TimeRange]:
        """Parse specific date like '3月10号' or 'March 5th'."""
        # Chinese pattern
        m = _DATE_PATTERN_ZH.search(query)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = now.year
            try:
                target = datetime(year, month, day, tzinfo=timezone.utc)
                return self._day_range(target)
            except ValueError:
                pass

        # English pattern
        m = _DATE_PATTERN_EN.search(query)
        if m:
            # Extract month name from the full match
            month_str = m.group(0).split()[0].lower()
            month = _MONTH_NAME_MAP.get(month_str)
            day = int(m.group(1))
            if month:
                year = now.year
                try:
                    target = datetime(year, month, day, tzinfo=timezone.utc)
                    return self._day_range(target)
                except ValueError:
                    pass

        return None

    def _resolve_static_time(self, now: datetime, kind: str) -> TimeRange:
        if kind == "yesterday":
            return self._day_range(now - timedelta(days=1))
        if kind == "day_before_yesterday":
            return self._day_range(now - timedelta(days=2))
        if kind == "today":
            return TimeRange(start=self._start_of_day(now), end=now.timestamp())
        if kind == "this_week":
            monday = now - timedelta(days=now.weekday())
            return TimeRange(start=self._start_of_day(monday), end=now.timestamp())
        if kind == "last_week":
            monday = now - timedelta(days=now.weekday() + 7)
            sunday = monday + timedelta(days=6)
            return TimeRange(start=self._start_of_day(monday), end=self._end_of_day(sunday))
        if kind == "last_month":
            year = now.year
            month = now.month - 1
            if month <= 0:
                month = 12
                year -= 1
            first = datetime(year, month, 1, tzinfo=timezone.utc)
            last_num = calendar.monthrange(year, month)[1]
            last = datetime(year, month, last_num, tzinfo=timezone.utc)
            return TimeRange(start=self._start_of_day(first), end=self._end_of_day(last))
        if kind == "this_month":
            first = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            return TimeRange(start=self._start_of_day(first), end=now.timestamp())
        if kind == "recently":
            return TimeRange(start=(now - timedelta(days=7)).timestamp(), end=now.timestamp())
        return TimeRange()

    # -----------------------------------------------------------------------
    # Layer routing
    # -----------------------------------------------------------------------

    def _route_layers(self, inp: IntentDeciderInput) -> list[LayerQueryPlan]:
        """Determine which layers to query.

        Routing is handled by the LLM intent decider when available.
        The rule engine only uses explicit hints (recall_intent, query_mode)
        and falls back to L1 primary + L2 fallback as a safe default.
        """
        # 1. If recall_intent hint is set, use it as the strongest routing signal.
        if inp.recall_intent_hint and inp.recall_intent_hint in _RECALL_INTENT_LAYER_MAP:
            primary_layer, fallback_layer = _RECALL_INTENT_LAYER_MAP[inp.recall_intent_hint]
            return [
                self._make_plan(primary_layer, inp, is_fallback=False),
                self._make_plan(fallback_layer, inp, is_fallback=True),
            ]

        # 2. If query_mode hint is set, use it as a strong signal for granularity.
        if inp.query_mode_hint and inp.query_mode_hint in _MODE_LAYER_MAP:
            primary_layer, fallback_layer = _MODE_LAYER_MAP[inp.query_mode_hint]
            return [
                self._make_plan(primary_layer, inp, is_fallback=False),
                self._make_plan(fallback_layer, inp, is_fallback=True),
            ]

        source_filters, domain_filters = self._infer_source_domain(inp.query.lower(), inp)

        # 3. Default: L1 primary + L2 fallback
        return [
            self._make_plan("L1", inp, is_fallback=False, source_filters=source_filters, domain_filters=domain_filters),
            self._make_plan("L2", inp, is_fallback=True, source_filters=source_filters, domain_filters=domain_filters),
        ]

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
                limit=10,
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
                recall_intent_hint=inp.recall_intent_hint,
            )
        elif layer == "L3":
            conditions = L3Conditions(
                content_query=inp.query,
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
        """Infer source and domain filters from query keywords."""
        # If caller already specified, use those
        if inp.source_filters or inp.domain_filters:
            return inp.source_filters or None, inp.domain_filters or None

        return infer_source_domain_filters(query_lower)

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
    def _day_range(dt: datetime) -> TimeRange:
        return TimeRange(
            start=RuleBasedIntentDecider._start_of_day(dt),
            end=RuleBasedIntentDecider._end_of_day(dt),
        )

    @staticmethod
    def _start_of_day(dt: datetime) -> float:
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    @staticmethod
    def _end_of_day(dt: datetime) -> float:
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()


# ---------------------------------------------------------------------------
# L2 condition enrichment (shared by rule engine and LLM post-processing)
# ---------------------------------------------------------------------------


def enrich_l2_conditions(
    conditions: L2Conditions,
    query: str,
    *,
    recall_intent_hint: str | None = None,
) -> None:
    """Fill missing L2 structural fields using rule-based inference.

    Modifies *conditions* in-place.  Only fills fields that are still at
    their default/empty values so that explicitly-set values are preserved.
    """
    if not conditions.entities:
        conditions.entities = extract_entities(query) or None

    if not conditions.subject_hint or conditions.subject_hint == "none":
        family = conditions.predicate_family or "unknown"
        if family == "unknown":
            family = _infer_predicate_family(query, recall_intent_hint=recall_intent_hint)
            conditions.predicate_family = family
        if family in {"preference", "profile_fact"}:
            conditions.subject_hint = "self"
        elif recall_intent_hint == "relationship_recall":
            conditions.subject_hint = "self"
        else:
            conditions.subject_hint = "none"

    if not conditions.predicate_family or conditions.predicate_family == "unknown":
        conditions.predicate_family = _infer_predicate_family(
            query, recall_intent_hint=recall_intent_hint,
        )

    if conditions.semantic_frame is None:
        conditions.semantic_frame = _infer_semantic_frame(
            query=query,
            subject_hint=conditions.subject_hint or "none",
            predicate_family=conditions.predicate_family or "unknown",
        )


def _infer_predicate_family(
    query: str,
    *,
    recall_intent_hint: str | None = None,
) -> str:
    """Infer the broad predicate family for L2 graph planning."""
    if recall_intent_hint == "preference_recall":
        return "preference"
    if recall_intent_hint == "profile_fact_recall":
        return "profile_fact"
    if recall_intent_hint == "relationship_recall":
        return "relationship"

    q = query.lower()
    if any(token in q for token in (
        "喜欢", "讨厌", "不喜欢", "偏好", "爱吃", "常喝", "反感", "最烦", "最爱",
        "like", "likes", "dislike", "dislikes", "enjoy", "hate", "love", "favorite", "prefer",
    )):
        return "preference"
    if any(token in q for token in (
        "关系", "认识", "谁", "他是谁", "怎么认识",
        "relationship", "know", "knows", "friend",
    )):
        return "relationship"
    if any(token in q for token in (
        "设置", "默认", "资料", "事实",
        "setting", "settings", "profile",
    )):
        return "profile_fact"
    if any(token in q for token in (
        "访问", "浏览", "去过", "看过",
        "visit", "visited", "browse", "browsed",
    )):
        return "activity"
    return "unknown"


def _infer_semantic_frame(
    *,
    query: str,
    subject_hint: str,
    predicate_family: str,
) -> L2SemanticFrame | None:
    """Infer a semantic frame for L2 graph search from query text."""
    query_lower = query.lower()
    query_family = _infer_query_family(predicate_family)
    answer_kind = infer_answer_kind(query_lower)
    if query_family == "lookup" and answer_kind == "unknown":
        return None

    constraints = infer_semantic_constraints(query, answer_kind=answer_kind)
    return L2SemanticFrame(
        query_family=query_family,
        subject_scope=subject_hint if subject_hint in _VALID_SUBJECT_HINTS else "none",
        answer_kind=answer_kind,
        answer_unit=_infer_answer_unit(answer_kind),
        answer_shape=infer_answer_shape(query_lower),
        polarity=infer_polarity(query_lower),
        entity_mentions=extract_entities(query),
        constraints=constraints,
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


def _infer_answer_unit(answer_kind: str) -> str:
    if answer_kind == "creator":
        return "identity"
    if answer_kind == "place":
        return "place"
    if answer_kind == "topic":
        return "topic"
    return "mixed"


# ---------------------------------------------------------------------------
# LLMIntentDecider
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are a fast memory-retrieval planning agent.

Analyze the user's query, decide which memory layers to query, and produce a concise retrieval phrase for each layer.

Memory layers:
- L1 (Event Stream): specific past events, chat logs, browser history, activities.
- L2 (Knowledge Graph): entity attributes, relationships, user profile facts, personal preferences.
- L3 (Reflection Summaries): period summaries, topic reviews, high-level insights.
- L4 (Procedural Memory): tool usage experience, workflows, strategies, best practices.

Rules:
- content_query language must match the user's query language.
- Do not hallucinate or expand the query with invented details.
- Keep content_query tight and answer-oriented.
- Time range parsing is handled elsewhere. Do not output time ranges.
- You may return multiple layer plans. Plans with is_fallback=true run only when primary retrieval is insufficient.
- Keep quoted titles verbatim. Do not replace a named item with a broad topic.

Routing guidance:
- Questions about preferences, profile facts, relationships, or long-lived personal attributes should prefer L2.
- Questions about specific events, order, attendance, browsing, or chat history should prefer L1.
- Questions asking for summaries, recaps, or reflections should prefer L3.
- Questions asking how something was done before should prefer L4.
- For comparison questions, produce separate plans with each candidate as content_query.
- For temporal-distance questions, produce anchor-specific content_query text for each event anchor.
- If the user asks about event order, duration, or "how many days/weeks before/after", prefer L1.

Examples:
- Query: Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?
  Good plans: L1 content_query="Effective Time Management workshop", L1 content_query="Data Analysis using Python webinar"
- Query: How many days before the team meeting did I attend the 'Effective Communication' workshop?
  Good plans: L1 content_query="Effective Communication workshop", L1 content_query="team meeting"

Return JSON only:
{
  "layers": [
    {
      "layer": "L1" | "L2" | "L3" | "L4",
      "is_fallback": false | true,
      "content_query": "string"
    }
  ],
  "reasoning": "brief explanation"
}"""

_VALID_LAYERS = {"L1", "L2", "L3", "L4"}


class LLMIntentDecider:
    """LLM-based intent decider using CONTEXT_DECIDER scenario."""

    def __init__(self, provider_bridge: Any, *, timeout_seconds: float = 3.0):
        self._bridge = provider_bridge
        self._timeout = timeout_seconds

    async def evaluate(self, inp: IntentDeciderInput) -> IntentDecision | None:
        """Call LLM for intent analysis. Returns None on any failure."""
        prompt_lines = [f"user query: {inp.query}"]
        if inp.recall_intent_hint:
            prompt_lines.append(f"recall_intent_hint: {inp.recall_intent_hint}")
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
            decision = self._parse_response(raw)
            if decision is None:
                return None
            return self._validate_decision(inp.query, decision, recall_intent_hint=inp.recall_intent_hint)
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

    def _parse_response(self, raw: str) -> IntentDecision | None:
        """Parse LLM JSON response into IntentDecision."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM intent decider returned invalid JSON")
            return None

        layers_data = data.get("layers")
        if not isinstance(layers_data, list) or not layers_data:
            return None

        plans: list[LayerQueryPlan] = []
        for item in layers_data:
            layer = item.get("layer", "")
            if layer not in _VALID_LAYERS:
                continue

            content_query = item.get("content_query", "")
            is_fallback = bool(item.get("is_fallback", False))

            if layer == "L1":
                conditions = L1Conditions(
                    content_query=content_query,
                )
            elif layer == "L2":
                conditions = L2Conditions(
                    content_query=content_query,
                    include_tom_snapshot=True,
                    include_relationships=True,
                    include_assertions=True,
                )
            elif layer == "L3":
                conditions = L3Conditions(content_query=content_query)
            elif layer == "L4":
                conditions = L4Conditions(content_query=content_query)
            else:
                continue

            plans.append(LayerQueryPlan(layer=layer, conditions=conditions, is_fallback=is_fallback))

        if not plans:
            return None

        reasoning = data.get("reasoning", "")
        return IntentDecision(plans=plans, reasoning=reasoning, source="llm")

    def _validate_decision(
        self,
        original_query: str,
        decision: IntentDecision,
        *,
        recall_intent_hint: str | None = None,
    ) -> IntentDecision:
        """Post-process LLM decision: validate L1 queries and enrich L2 conditions."""
        for plan in decision.plans:
            if plan.layer == "L1" and isinstance(plan.conditions, L1Conditions):
                plan.conditions.content_query = self._validate_l1_content_query(
                    original_query=original_query,
                    content_query=plan.conditions.content_query,
                )
            elif plan.layer == "L2" and isinstance(plan.conditions, L2Conditions):
                enrich_l2_conditions(
                    plan.conditions, original_query,
                    recall_intent_hint=recall_intent_hint,
                )
        return decision

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

        temporal_distance_queries = extract_temporal_distance_queries(normalized_query)
        if temporal_distance_queries:
            has_anchor_overlap = any(
                set(extract_query_tokens(anchor_query)) & content_tokens
                for anchor_query in temporal_distance_queries
                if anchor_query
            )
            if not has_anchor_overlap:
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
    llm_decision: Optional[IntentDecision]
    final_decision: IntentDecision
    decision_source: str
    llm_latency_ms: Optional[float]
    llm_error: Optional[str]
    layers_match: bool
    diff_summary: str


def compute_diff(
    rule_decision: IntentDecision,
    llm_decision: Optional[IntentDecision],
) -> tuple[bool, str]:
    """Compare rule and LLM decisions. Returns (match, diff_summary)."""
    if llm_decision is None:
        return False, "llm_failed"

    rule_layers = sorted({p.layer for p in rule_decision.plans if not p.is_fallback})
    llm_layers = sorted({p.layer for p in llm_decision.plans if not p.is_fallback})

    if rule_layers == llm_layers:
        return True, "match"

    return False, f"rule={'+'.join(rule_layers)}, llm={'+'.join(llm_layers)}"


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

    async def decide(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce final intent decision using LLM primary + rule shadow."""
        # 1. Rule layer always runs (sync) — time parsing + shadow baseline
        rule_decision = self._rule_engine.evaluate(inp)
        time_range = rule_decision.time_range

        # 2. LLM decision (primary path)
        llm_decision: Optional[IntentDecision] = None
        llm_latency_ms: Optional[float] = None
        llm_error: Optional[str] = None

        if self._llm_enabled and self._llm_decider is not None:
            t0 = time.monotonic()
            try:
                llm_decision = await self._llm_decider.evaluate(inp)
            except Exception as exc:
                llm_error = str(exc)
                logger.warning("LLM intent decider error: %s", exc)
            llm_latency_ms = (time.monotonic() - t0) * 1000

        # 3. Determine final decision
        if llm_decision is not None:
            # LLM succeeded: use LLM routing + rule time range
            final_decision = self._merge_decisions(llm_decision, time_range)
            decision_source = "llm"
        else:
            final_decision = rule_decision
            decision_source = "rule_fallback"

        final_decision.source = decision_source

        # 4. Shadow evaluation (async, non-blocking)
        if self._shadow_eval_enabled and self._eval_callback is not None:
            layers_match, diff_summary = compute_diff(rule_decision, llm_decision)
            record = EvaluationRecord(
                query=inp.query,
                user_id=inp.user_id,
                session_id=inp.session_id,
                rule_decision=rule_decision,
                llm_decision=llm_decision,
                final_decision=final_decision,
                decision_source=decision_source,
                llm_latency_ms=llm_latency_ms,
                llm_error=llm_error,
                layers_match=layers_match,
                diff_summary=diff_summary,
            )
            asyncio.create_task(self._safe_log(record))

        return final_decision

    def _merge_decisions(
        self,
        llm_routing: IntentDecision,
        rule_time_range: Optional[TimeRange],
    ) -> IntentDecision:
        """Merge LLM routing with rule-derived time range."""
        for plan in llm_routing.plans:
            plan.time_range = rule_time_range
        llm_routing.time_range = rule_time_range
        return llm_routing

    async def _safe_log(self, record: EvaluationRecord) -> None:
        """Log evaluation, swallowing errors."""
        try:
            await self._eval_callback(record)
        except Exception:
            logger.debug("Shadow eval logging error", exc_info=True)
