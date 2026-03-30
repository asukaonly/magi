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

# ---------------------------------------------------------------------------
# Layer routing signal keywords
# ---------------------------------------------------------------------------

_L2_SIGNALS = [
    "关系", "认识", "谁是", "谁", "人物", "联系人",
    "偏好", "喜好", "喜欢", "讨厌", "不喜欢", "画像", "倾向",
    "relationship", "who is", "who", "person", "contact",
    "preference", "preferences", "profile", "tendency",
    "like", "likes", "dislike", "dislikes",
]
_L3_SIGNALS = [
    "总结", "回顾", "小结", "概要", "复盘",
    "summary", "review", "recap", "overview",
]
_L4_SIGNALS = [
    "怎么做", "上次怎么", "经验", "技巧", "最佳实践", "方法", "策略",
    "how to", "best practice", "experience", "strategy", "technique",
]
_L1_SIGNALS = [
    "浏览", "看了", "聊了", "发了", "搜了", "打开了", "访问了",
    "browsed", "viewed", "chatted", "searched", "opened", "visited",
]

# Source / domain signal keywords
_SOURCE_DOMAIN_SIGNALS: list[tuple[list[str], list[str], list[str]]] = [
    # (keywords, source_filters, domain_filters)
    (["浏览", "browsing", "网页", "webpage", "browser"], ["chrome_history"], ["external_activity"]),
    (["聊天", "对话", "chat", "conversation"], ["chat"], ["user_authored"]),
    (["终端", "terminal", "git", "命令行", "command"], ["terminal", "git"], ["external_activity"]),
    (["日记", "笔记", "journal", "note", "diary"], ["journal", "note"], ["user_authored"]),
    (["日历", "开会", "会议", "calendar", "meeting"], ["calendar"], ["external_activity"]),
    (["音乐", "听了", "music", "listened"], ["music"], ["external_activity"]),
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
        """Determine which layers to query based on keyword signals."""
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

        query_lower = inp.query.lower()
        source_filters, domain_filters = self._infer_source_domain(query_lower, inp)

        # 3. Check keyword signals
        if any(kw in query_lower for kw in _L2_SIGNALS):
            return [
                self._make_plan("L2", inp, is_fallback=False, source_filters=source_filters, domain_filters=domain_filters),
                self._make_plan("L1", inp, is_fallback=True, source_filters=source_filters, domain_filters=domain_filters),
            ]

        if any(kw in query_lower for kw in _L3_SIGNALS):
            return [
                self._make_plan("L3", inp, is_fallback=False, source_filters=source_filters, domain_filters=domain_filters),
                self._make_plan("L1", inp, is_fallback=True, source_filters=source_filters, domain_filters=domain_filters),
            ]

        if any(kw in query_lower for kw in _L4_SIGNALS):
            return [
                self._make_plan("L4", inp, is_fallback=False, source_filters=source_filters, domain_filters=domain_filters),
                self._make_plan("L1", inp, is_fallback=True, source_filters=source_filters, domain_filters=domain_filters),
            ]

        if any(kw in query_lower for kw in _L1_SIGNALS):
            return [
                self._make_plan("L1", inp, is_fallback=False, source_filters=source_filters, domain_filters=domain_filters),
                self._make_plan("L3", inp, is_fallback=True, source_filters=source_filters, domain_filters=domain_filters),
            ]

        # 4. Default: L1 primary + L3 fallback
        return [
            self._make_plan("L1", inp, is_fallback=False, source_filters=source_filters, domain_filters=domain_filters),
            self._make_plan("L3", inp, is_fallback=True, source_filters=source_filters, domain_filters=domain_filters),
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
            entities = self._extract_entities(inp.query)
            subject_hint = self._infer_subject_hint(inp)
            predicate_family = self._infer_predicate_family(inp)
            conditions = L2Conditions(
                content_query=inp.query,
                entities=entities if entities else None,
                subject_hint=subject_hint,
                predicate_family=predicate_family,
                semantic_frame=self._infer_semantic_frame(
                    query=inp.query,
                    subject_hint=subject_hint,
                    predicate_family=predicate_family,
                ),
                include_tom_snapshot=True,
                include_relationships=True,
                include_assertions=True,
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

        for keywords, sources, domains in _SOURCE_DOMAIN_SIGNALS:
            if any(kw in query_lower for kw in keywords):
                return sources, domains

        return None, None

    def _extract_entities(self, query: str) -> list[str]:
        """Extract high-confidence entity surface forms for common software/platform names."""
        entities: list[str] = []
        if "B站" in query or "b站" in query.lower() or "bilibili" in query.lower():
            entities.append("B站")
        if "youtube" in query.lower() or "油管" in query:
            entities.append("YouTube")
        return entities

    def _infer_subject_hint(self, inp: IntentDeciderInput) -> str:
        """Infer whether the query subject is the current user or an explicit entity.

        The rule-based path cannot reliably distinguish "我喜欢什么" (self) from
        "我妈喜欢什么" (explicit).  Accurate subject detection is delegated to
        the LLM intent decider.  Here we apply a safe default: preference and
        profile queries in a personal-AI context are overwhelmingly about the
        user, so we return "self" for those families.
        """
        family = self._infer_predicate_family(inp)
        if family in {"preference", "profile_fact"}:
            return "self"
        if inp.recall_intent_hint == "relationship_recall":
            return "self"
        return "none"

    def _infer_predicate_family(self, inp: IntentDeciderInput) -> str:
        """Infer the broad predicate family for L2 graph planning."""
        if inp.recall_intent_hint == "preference_recall":
            return "preference"
        if inp.recall_intent_hint == "profile_fact_recall":
            return "profile_fact"
        if inp.recall_intent_hint == "relationship_recall":
            return "relationship"

        query = inp.query.lower()
        if any(token in query for token in (
            "喜欢", "讨厌", "不喜欢", "偏好", "爱吃", "常喝", "反感", "最烦", "最爱",
            "like", "likes", "dislike", "dislikes", "enjoy", "hate", "love", "favorite", "prefer",
        )):
            return "preference"
        if any(token in query for token in (
            "关系", "认识", "谁", "他是谁", "怎么认识",
            "relationship", "know", "knows", "friend",
        )):
            return "relationship"
        if any(token in query for token in (
            "设置", "默认", "资料", "事实",
            "setting", "settings", "profile",
        )):
            return "profile_fact"
        if any(token in query for token in (
            "访问", "浏览", "去过", "看过",
            "visit", "visited", "browse", "browsed",
        )):
            return "activity"
        return "unknown"

    def _infer_semantic_frame(
        self,
        *,
        query: str,
        subject_hint: str,
        predicate_family: str,
    ) -> L2SemanticFrame | None:
        query_lower = query.lower()
        query_family = self._infer_query_family(predicate_family=predicate_family)
        answer_kind = self._infer_answer_kind(query_lower)
        if query_family == "lookup" and answer_kind == "unknown":
            return None

        constraints = self._infer_semantic_constraints(query, answer_kind=answer_kind)
        return L2SemanticFrame(
            query_family=query_family,
            subject_scope=subject_hint if subject_hint in _VALID_SUBJECT_HINTS else "none",
            answer_kind=answer_kind,
            answer_unit=self._infer_answer_unit(answer_kind),
            answer_shape=self._infer_answer_shape(query_lower),
            polarity=self._infer_polarity(query_lower),
            entity_mentions=self._extract_entities(query),
            constraints=constraints,
            ranking_mode="affinity" if query_family == "affinity" else "confidence",
        )

    @staticmethod
    def _infer_query_family(*, predicate_family: str) -> str:
        if predicate_family == "preference":
            return "affinity"
        if predicate_family == "relationship":
            return "relationship"
        if predicate_family == "profile_fact":
            return "profile"
        if predicate_family == "activity":
            return "activity"
        return "lookup"

    @staticmethod
    def _infer_answer_kind(query_lower: str) -> str:
        if any(token in query_lower for token in ("up主", "up", "博主", "youtuber", "主播", "creator", "频道", "channel")):
            return "creator"
        if any(token in query_lower for token in ("咖啡馆", "餐厅", "店", "饭馆", "cafe", "restaurant", "shop")):
            return "place"
        if any(token in query_lower for token in ("题材", "主题", "topic")):
            return "topic"
        if any(token in query_lower for token in ("软件", "网站", "app", "平台", "网站", "b站", "bilibili", "youtube")):
            return "software"
        if any(token in query_lower for token in ("谁", "人", "person")):
            return "person"
        return "unknown"

    @staticmethod
    def _infer_answer_unit(answer_kind: str) -> str:
        if answer_kind == "creator":
            return "identity"
        if answer_kind == "place":
            return "place"
        if answer_kind == "topic":
            return "topic"
        return "mixed"

    @staticmethod
    def _infer_answer_shape(query_lower: str) -> str:
        if "是否" in query_lower or "是不是" in query_lower:
            return "boolean"
        if re.search(r"(吗|么)\s*[?？]?\s*$", query_lower):
            return "boolean"
        if any(token in query_lower for token in ("哪些", "什么", "谁", "哪几个", "which", "what")):
            return "list"
        return "single"

    @staticmethod
    def _infer_polarity(query_lower: str) -> str:
        if any(token in query_lower for token in ("讨厌", "不喜欢", "dislike", "hate")):
            return "negative"
        if any(token in query_lower for token in ("喜欢", "偏好", "关注", "常看", "love", "like", "prefer")):
            return "positive"
        return "any"

    def _infer_semantic_constraints(self, query: str, *, answer_kind: str) -> list[SemanticConstraint]:
        query_lower = query.lower()
        constraints: list[SemanticConstraint] = []
        interaction_platform_value: str | None = None
        if answer_kind != "software":
            if re.search(r"用\s*(B站|b站|bilibili)\s*(?:的时候)?", query, re.IGNORECASE):
                interaction_platform_value = "b站"
            elif re.search(r"在\s*(B站|b站|bilibili)\s*的时候", query, re.IGNORECASE):
                interaction_platform_value = "b站"
            elif re.search(r"用\s*(youtube|油管)\s*(?:的时候)?", query, re.IGNORECASE):
                interaction_platform_value = "youtube"
            elif re.search(r"(?:在|用)\s*(youtube|油管)\s*的时候", query, re.IGNORECASE):
                interaction_platform_value = "youtube"

        if interaction_platform_value is not None:
            constraints.append(
                SemanticConstraint(
                    scope="interaction",
                    facet="platform",
                    raw_value=interaction_platform_value,
                )
            )
        elif answer_kind != "software" and ("b站" in query_lower or "bilibili" in query_lower):
            constraints.append(SemanticConstraint(scope="target", facet="platform", raw_value="b站"))
        elif answer_kind != "software" and ("youtube" in query_lower or "油管" in query_lower):
            constraints.append(SemanticConstraint(scope="target", facet="platform", raw_value="youtube"))
        interaction_location_match = re.search(r"在([\u4e00-\u9fffA-Za-z]{2,12})的时候喜欢去", query)
        if interaction_location_match:
            constraints.append(
                SemanticConstraint(
                    scope="interaction",
                    facet="located_in",
                    raw_value=interaction_location_match.group(1),
                )
            )
        else:
            location_match = re.search(r"在([\u4e00-\u9fffA-Za-z]{2,12})喜欢去", query)
            if location_match:
                constraints.append(
                    SemanticConstraint(
                        scope="target",
                        facet="located_in",
                        raw_value=location_match.group(1),
                    )
                )
        category_map = {
            "咖啡馆": "coffee_shop",
            "咖啡店": "coffee_shop",
            "餐厅": "restaurant",
            "饭馆": "restaurant",
        }
        for label, facet_value in category_map.items():
            if label in query:
                constraints.append(
                    SemanticConstraint(
                        scope="target",
                        facet="category",
                        raw_value=label,
                        resolved_facet_value=facet_value,
                    )
                )
                break
        return constraints

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
# LLMIntentDecider
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are a fast memory-retrieval planning agent.

Your task is to analyze the user's query, decide which memory layers should be queried, and produce layer-specific retrieval plans.

Memory layers:
- L1 (Event Stream): specific past events, chat logs, browser history, activities.
- L2 (Knowledge Graph): entity attributes, relationships, user profile facts, personal preferences.
- L3 (Reflection Summaries): period summaries, topic reviews, high-level insights.
- L4 (Procedural Memory): tool usage experience, workflows, strategies, best practices.

General rules:
- Output language for all free-text fields must match the user's query language.
- Do not hallucinate examples or expand the query with invented details.
- Keep retrieval text tight and answer-oriented.
- Time range parsing is handled elsewhere. Do not output time ranges.
- You may return multiple layer plans.
- Plans with is_fallback=true run only when primary retrieval is insufficient.

Layer-specific rules:
- For L1, L3, and L4:
  - Use content_query as a concise retrieval phrase for vector/text search.
  - Keep quoted titles verbatim.
  - Do not replace a quoted title with a broad topic.
  - Do not replace a named item with a broad topic.
- For L2:
  - Use content_query as a compact graph-oriented retrieval phrase.
  - Extract entities as surface-form entity mentions from the query when possible.
  - Entities are mention hints, not canonical database IDs.
  - Do not put generic self references like "I", "me", "user", or "我" into entities.
  - When the grammatical subject is the current user, set subject_hint to "self".
  - When another explicit person or entity is the subject, set subject_hint to "explicit".
  - Otherwise set subject_hint to "none".
  - Use predicate_family instead of guessing one exact graph edge when the intent is broad.
  - Allowed predicate_family values: "preference", "relationship", "profile_fact", "activity", "unknown".
  - When the query semantics are clearer than predicate_family alone, populate semantic_frame.
  - semantic_frame should describe query_family, subject_scope, answer_kind, answer_unit, answer_shape, polarity, and constraints.
  - Use target platform constraints for phrases like "B站上的 up 主" instead of turning the platform into an exact relationship object_id.

Routing guidance:
- Questions about preferences, profile facts, relationships, or long-lived personal attributes should prefer L2.
- Questions about specific events, order, attendance, browsing, or chat history should prefer L1.
- Questions asking for summaries, recaps, or reflections should prefer L3.
- Questions asking how something was done before should prefer L4.
- For comparison questions, keep both candidate events explicit in the plan.
- For temporal-distance questions, produce anchor-specific content_query text for each event anchor.
- Do not collapse both anchors into one generic topic query.
- If the user asks about event order, duration, or "how many days/weeks before/after", prefer L1 as the primary layer unless the query is clearly asking for a summary or procedure.

Examples:
- Query: Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?
  Good L1 content_query values: "Effective Time Management workshop", "Data Analysis using Python webinar"
- Query: How many days before the team meeting I was preparing for did I attend the workshop on 'Effective Communication in the Workplace'?
  Good L1 content_query values: "Effective Communication in the Workplace workshop", "team meeting preparing for"

Return JSON only:
{
  "layers": [
    {
      "layer": "L1" | "L2" | "L3" | "L4",
      "is_fallback": false | true,
      "content_query": "string",
      "entities": ["string"],
      "subject_hint": "self" | "explicit" | "none",
      "predicate_family": "preference" | "relationship" | "profile_fact" | "activity" | "unknown",
      "semantic_frame": {
        "query_family": "affinity" | "relationship" | "profile" | "activity" | "lookup",
        "subject_scope": "self" | "explicit" | "none",
        "answer_kind": "creator" | "place" | "topic" | "person" | "software" | "unknown",
        "answer_unit": "identity" | "presence" | "place" | "topic" | "mixed",
        "answer_shape": "list" | "single" | "boolean",
        "polarity": "positive" | "negative" | "neutral" | "any",
        "entity_mentions": ["string"],
        "constraints": [
          {
            "scope": "target" | "interaction",
            "facet": "platform" | "located_in" | "category",
            "raw_value": "string",
            "resolved_entity_id": "optional entity id",
            "resolved_facet_value": "optional normalized value"
          }
        ],
        "ranking_mode": "affinity" | "confidence" | "recency"
      },
      "source_filters": ["chat", "chrome_history", "profile", "terminal", "git"],
      "domain_filters": ["user_authored", "external_activity", "system_generated"]
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
            decision = self._parse_response(raw)
            if decision is None:
                return None
            return self._validate_decision(inp.query, decision)
        except Exception:
            logger.warning("LLM intent decider failed", exc_info=True)
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
            entities = item.get("entities") or []
            source_filters = item.get("source_filters") or None
            domain_filters = item.get("domain_filters") or None
            subject_hint = str(item.get("subject_hint") or "none").strip().lower()
            predicate_family = str(item.get("predicate_family") or "unknown").strip().lower()
            if subject_hint not in _VALID_SUBJECT_HINTS:
                subject_hint = "none"
            if predicate_family not in _VALID_PREDICATE_FAMILIES:
                predicate_family = "unknown"
            semantic_frame = self._parse_semantic_frame(item.get("semantic_frame"))

            if layer == "L1":
                conditions = L1Conditions(
                    content_query=content_query,
                    source_filters=source_filters,
                    domain_filters=domain_filters,
                )
            elif layer == "L2":
                conditions = L2Conditions(
                    content_query=content_query,
                    entities=entities if entities else None,
                    subject_hint=subject_hint,
                    predicate_family=predicate_family,
                    semantic_frame=semantic_frame,
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

    def _validate_decision(self, original_query: str, decision: IntentDecision) -> IntentDecision:
        """Lightly narrow over-broad L1 content queries without changing routing."""
        for plan in decision.plans:
            if plan.layer != "L1" or not isinstance(plan.conditions, L1Conditions):
                continue
            plan.conditions.content_query = self._validate_l1_content_query(
                original_query=original_query,
                content_query=plan.conditions.content_query,
            )
        return decision

    def _parse_semantic_frame(self, payload: Any) -> L2SemanticFrame | None:
        if not isinstance(payload, dict):
            return None
        query_family = str(payload.get("query_family") or "lookup").strip().lower()
        subject_scope = str(payload.get("subject_scope") or "none").strip().lower()
        answer_kind = str(payload.get("answer_kind") or "unknown").strip().lower()
        answer_unit = str(payload.get("answer_unit") or "mixed").strip().lower()
        answer_shape = str(payload.get("answer_shape") or "list").strip().lower()
        polarity = str(payload.get("polarity") or "any").strip().lower()
        ranking_mode = str(payload.get("ranking_mode") or "affinity").strip().lower()
        if query_family not in _VALID_QUERY_FAMILIES:
            query_family = "lookup"
        if subject_scope not in _VALID_SUBJECT_HINTS:
            subject_scope = "none"
        if answer_kind not in _VALID_ANSWER_KINDS:
            answer_kind = "unknown"
        if answer_unit not in _VALID_ANSWER_UNITS:
            answer_unit = "mixed"
        if answer_shape not in _VALID_ANSWER_SHAPES:
            answer_shape = "list"
        if polarity not in _VALID_POLARITIES:
            polarity = "any"
        if ranking_mode not in {"affinity", "confidence", "recency"}:
            ranking_mode = "affinity"

        constraints: list[SemanticConstraint] = []
        for item in payload.get("constraints") or []:
            if not isinstance(item, dict):
                continue
            scope = str(item.get("scope") or "target").strip().lower()
            facet = str(item.get("facet") or "").strip().lower()
            raw_value = str(item.get("raw_value") or "").strip()
            if scope not in _VALID_CONSTRAINT_SCOPES or facet not in _VALID_CONSTRAINT_FACETS or not raw_value:
                continue
            constraints.append(
                SemanticConstraint(
                    scope=scope,
                    facet=facet,
                    raw_value=raw_value,
                    resolved_entity_id=str(item.get("resolved_entity_id") or "").strip() or None,
                    resolved_facet_value=str(item.get("resolved_facet_value") or "").strip() or None,
                )
            )

        entity_mentions = [str(item).strip() for item in payload.get("entity_mentions") or [] if str(item).strip()]
        return L2SemanticFrame(
            query_family=query_family,
            subject_scope=subject_scope,
            answer_kind=answer_kind,
            answer_unit=answer_unit,
            answer_shape=answer_shape,
            polarity=polarity,
            entity_mentions=entity_mentions,
            constraints=constraints,
            ranking_mode=ranking_mode,
        )

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
