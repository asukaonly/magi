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
from .mode_registry import MODE_REGISTRY, VALID_MODES


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Time keyword patterns
# ---------------------------------------------------------------------------

# Keywords that imply a recent window; dateparser cannot resolve these.
_RECENTLY_KEYWORDS: list[str] = ["最近", "recently", "近期"]

# Chinese temporal extraction — search_dates has poor support for these.
_ZH_RELATIVE_RE = re.compile(r"\d+\s*(?:天|小时|周|个?月)前")
_ZH_DATE_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]")
_ZH_LAST_WEEKDAY_RE = re.compile(r"上(?:周|星期)([一二三四五六日天])")
_ZH_THIS_WEEK_RE = re.compile(r"(?:这|本)(?:周|星期)")
_ZH_DAY_MAP: dict[str, int] = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}

# Heuristics for inferring range width from dateparser matched text.
_HOUR_HINT_RE = re.compile(r"hour|小时", re.IGNORECASE)
_WEEK_HINT_RE = re.compile(r"week|周|星期", re.IGNORECASE)
_WEEKDAY_SPECIFIC_RE = re.compile(
    r"周[一二三四五六日天]"
    r"|星期[一二三四五六日天]"
    r"|(?:mon|tues|wednes|thurs|fri|satur|sun)day",
    re.IGNORECASE,
)
_MONTH_HINT_RE = re.compile(r"month|月", re.IGNORECASE)
_DAY_NUMBER_SUFFIX_RE = re.compile(r"\d+\s*[号日]|\d+(?:st|nd|rd|th)\b", re.IGNORECASE)

# Regex to strip a leading preposition that search_dates may have greedily
# absorbed into the matched span (e.g. "in a week ago" instead of "a week ago").
_LEADING_PREP_RE = re.compile(r"^(?:in|at|on|for|from)\s+", re.IGNORECASE)




_VALID_SUBJECT_HINTS = {"self", "explicit", "none"}
_VALID_PREDICATE_FAMILIES = {"preference", "relationship", "profile_fact", "activity", "unknown"}
_VALID_QUERY_FAMILIES = {"affinity", "relationship", "profile", "activity", "lookup"}
_VALID_ANSWER_KINDS = {"creator", "place", "topic", "person", "software", "unknown"}
_VALID_ANSWER_UNITS = {"identity", "presence", "place", "topic", "mixed"}
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
        if "start" in raw or "end" in raw:
            start = float(raw["start"]) if "start" in raw else None
            end = float(raw["end"]) if "end" in raw else None
            return TimeRange(start=start, end=end)

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
        """Parse time expressions from natural language query.

        Uses a hybrid strategy:
        1. Chinese-specific regex extraction → ``dateparser.parse()``
        2. ``dateparser.search.search_dates()`` for English (and simple Chinese)
        3. Range-width heuristics via ``_range_from_match``
        """
        query_lower = query.lower()
        now = datetime.now(tz=timezone.utc)

        # "recently" / "最近" → 7-day window (dateparser cannot resolve these)
        if any(kw in query_lower for kw in _RECENTLY_KEYWORDS):
            return TimeRange(
                start=(now - timedelta(days=7)).timestamp(),
                end=now.timestamp(),
            )

        # 1. Chinese-specific patterns (search_dates handles these poorly)
        zh_result = self._try_chinese_temporal(query, now)
        if zh_result is not None:
            return zh_result

        # 2. dateparser.search_dates — good for English expressions
        try:
            from dateparser.search import search_dates
        except ImportError:
            logger.debug("dateparser not available; skipping NL time parsing")
            return None

        settings: dict = {
            "RELATIVE_BASE": now.replace(tzinfo=None),
            "PREFER_DATES_FROM": "past",
        }

        try:
            results = search_dates(
                query, settings=settings, languages=["en", "zh"],
            )
        except Exception:
            logger.debug("dateparser.search_dates failed for query=%r", query)
            return None

        if not results:
            return None

        # Keep only resolved dates that are in the past.
        past: list[tuple[str, datetime]] = []
        for matched_text, resolved_dt in results:
            dt_utc = resolved_dt.replace(tzinfo=timezone.utc)
            if dt_utc <= now:
                past.append((matched_text, dt_utc))

        if not past:
            # Fallback: search_dates may mismatch spans (e.g. "in a week
            # ago" parsed as "in a week" → future).  Re-parse each matched
            # text after stripping a leading preposition.
            past = _reparse_with_stripped_preposition(results, settings, now)

        if not past:
            return None

        if len(past) == 1:
            text, dt = past[0]
            return self._range_from_match(text, dt, now)

        # Multiple results: span from earliest to latest
        all_ranges = [self._range_from_match(t, d, now) for t, d in past]
        return TimeRange(
            start=min(r.start for r in all_ranges if r.start is not None),
            end=max(r.end for r in all_ranges if r.end is not None),
        )

    # -----------------------------------------------------------------------
    # Chinese temporal extraction
    # -----------------------------------------------------------------------

    def _try_chinese_temporal(
        self, query: str, now: datetime,
    ) -> Optional[TimeRange]:
        """Extract and resolve Chinese temporal expressions.

        ``dateparser.search_dates`` misses many Chinese relative patterns
        (e.g. "N天前", "上周三", "3月10号").  This method detects them via
        lightweight regex, then resolves via ``dateparser.parse()`` where
        possible and manual calculation otherwise.
        """
        # 1. Relative N-ago: "3天前", "2小时前", "N周前", "N个月前"
        m = _ZH_RELATIVE_RE.search(query)
        if m:
            phrase = m.group(0)
            try:
                from dateparser import parse as dp_parse
            except ImportError:
                return None
            settings: dict = {
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "PREFER_DATES_FROM": "past",
            }
            dt = dp_parse(phrase, settings=settings, languages=["zh"])
            if dt:
                dt_utc = dt.replace(tzinfo=timezone.utc)
                return self._range_from_match(phrase, dt_utc, now)

        # 2. Specific weekday: "上周三", "上星期五"
        m = _ZH_LAST_WEEKDAY_RE.search(query)
        if m:
            weekday = _ZH_DAY_MAP.get(m.group(1))
            if weekday is not None:
                last_monday = now - timedelta(days=now.weekday() + 7)
                target = last_monday + timedelta(days=weekday)
                return self._day_range(target)

        # 3. Specific date: "3月10号", "12月25日"
        m = _ZH_DATE_RE.search(query)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            try:
                target = datetime(now.year, month, day, tzinfo=timezone.utc)
                return self._day_range(target)
            except ValueError:
                pass

        # 4. This week: "这周", "本周", "这星期"
        if _ZH_THIS_WEEK_RE.search(query):
            monday = now - timedelta(days=now.weekday())
            return TimeRange(
                start=self._start_of_day(monday),
                end=now.timestamp(),
            )

        return None

    # -----------------------------------------------------------------------
    # Range width heuristics
    # -----------------------------------------------------------------------

    def _range_from_match(
        self, matched_text: str, resolved_dt: datetime, now: datetime,
    ) -> TimeRange:
        """Infer an appropriate time range from a dateparser match.

        Uses simple heuristics on *matched_text* to decide whether the
        expression refers to an hour, day, week, or month window.
        """
        text = matched_text.strip()

        # Hour-level: "2 hours ago", "3小时前"
        if _HOUR_HINT_RE.search(text):
            return TimeRange(
                start=resolved_dt.timestamp(),
                end=now.timestamp(),
            )

        # Week-level (NOT a specific weekday): "last week", "2周前"
        if _WEEK_HINT_RE.search(text) and not _WEEKDAY_SPECIFIC_RE.search(text):
            monday = resolved_dt - timedelta(days=resolved_dt.weekday())
            sunday = monday + timedelta(days=6)
            return TimeRange(
                start=self._start_of_day(monday),
                end=min(self._end_of_day(sunday), now.timestamp()),
            )

        # Month-level (NOT a specific date): "last month", "2个月前"
        if _MONTH_HINT_RE.search(text) and not _DAY_NUMBER_SUFFIX_RE.search(text):
            first = resolved_dt.replace(day=1)
            last_day_num = calendar.monthrange(
                resolved_dt.year, resolved_dt.month,
            )[1]
            end_dt = resolved_dt.replace(day=last_day_num)
            return TimeRange(
                start=self._start_of_day(first),
                end=min(self._end_of_day(end_dt), now.timestamp()),
            )

        # Default: single day range
        return self._day_range(resolved_dt)

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
            mode = "exact_fact"

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
# Temporal re-parse fallback
# ---------------------------------------------------------------------------


def _reparse_with_stripped_preposition(
    results: list[tuple[str, Any]],
    settings: dict,
    now: datetime,
) -> list[tuple[str, datetime]]:
    """Re-parse matched texts after stripping a leading preposition.

    ``dateparser.search.search_dates`` sometimes captures a preceding
    preposition as part of the temporal span (e.g. *"in a week ago"*
    instead of *"a week ago"*), causing a future-directed parse.  This
    helper strips the preposition and retries ``dateparser.parse``.
    """
    import dateparser

    past: list[tuple[str, datetime]] = []
    for matched_text, _ in results:
        stripped = _LEADING_PREP_RE.sub("", matched_text)
        if stripped == matched_text:
            continue
        retry_dt = dateparser.parse(stripped, settings=settings)
        if retry_dt is None:
            continue
        dt_utc = retry_dt.replace(tzinfo=timezone.utc)
        if dt_utc <= now:
            past.append((stripped, dt_utc))
            logger.debug(
                "Temporal reparse succeeded: %r → %r → %s",
                matched_text, stripped, retry_dt,
            )
    return past


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
- Keep quoted titles verbatim. Do not replace a quoted title with a broad topic.
- For comparison questions, keep both candidate events explicit; produce separate L1 plans per candidate.

Routing guidance:
- Questions about preferences, profile facts, relationships, or long-lived personal attributes should prefer L2.
- Questions about specific events, order, attendance, browsing, or chat history should prefer L1.
- Questions asking for summaries, recaps, or reflections should prefer L3.
- Questions asking how something was done before should prefer L4.
- If the user asks about event order, duration, or "how many days/weeks before/after", prefer L1.
- When L2 is the primary layer, ALWAYS include an L1 plan as well (is_fallback=false). Knowledge graph entries may be incomplete; the original conversation in L1 provides essential supporting context for answering.

L2 plan fields:
- For L2 plans about the user's own preferences/facts, set subject_hint to "self".
- Allowed predicate_family values: preference, profile_fact, relationship, unknown.
- Include a "semantic_frame" object with structured query semantics:
  - "query_family": affinity | relationship | profile | activity | lookup
  - "answer_kind": creator | place | topic | person | software | unknown
  - "answer_unit": identity | presence | place | topic | mixed
  - "constraints": array of {scope, facet, raw_value, resolved_entity_id?, resolved_facet_value?}

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

_VALID_CONSTRAINT_SCOPES = {"target", "interaction"}
_VALID_CONSTRAINT_FACETS = {"platform", "located_in", "category"}


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
    """LLM-based intent decider using CONTEXT_DECIDER scenario."""

    def __init__(self, provider_bridge: Any, *, timeout_seconds: float = 3.0):
        self._bridge = provider_bridge
        self._timeout = timeout_seconds

    async def evaluate(self, inp: IntentDeciderInput) -> IntentDecision | None:
        """Call LLM for intent analysis. Returns None on any failure."""
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
            decision = self._parse_response(raw)
            if decision is None:
                return None
            return self._validate_decision(inp.query, decision)
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
                    entities=item.get("entities") or None,
                    subject_hint=item.get("subject_hint") or None,
                    predicate_family=item.get("predicate_family") or None,
                    semantic_frame=_parse_semantic_frame(item.get("semantic_frame")),
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
    ) -> IntentDecision:
        """Post-process LLM decision: validate L1 queries and enrich L2 conditions."""
        for plan in decision.plans:
            if plan.layer == "L1" and isinstance(plan.conditions, L1Conditions):
                plan.conditions.content_query = self._validate_l1_content_query(
                    original_query=original_query,
                    content_query=plan.conditions.content_query,
                )
            elif plan.layer == "L2" and isinstance(plan.conditions, L2Conditions):
                enrich_l2_conditions(plan.conditions, original_query)
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
        self._background_tasks: set[asyncio.Task[None]] = set()

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
            task = asyncio.create_task(self._safe_log(record))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

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
