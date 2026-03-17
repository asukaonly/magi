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
    "relationship", "who is", "who", "person", "contact",
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
    (["浏览", "browsing", "网页", "webpage", "browser"], ["browser_history"], ["external_activity"]),
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
        # 1. If query_mode hint is set, use it as strong signal
        if inp.query_mode_hint and inp.query_mode_hint in _MODE_LAYER_MAP:
            primary_layer, fallback_layer = _MODE_LAYER_MAP[inp.query_mode_hint]
            return [
                self._make_plan(primary_layer, inp, is_fallback=False),
                self._make_plan(fallback_layer, inp, is_fallback=True),
            ]

        query_lower = inp.query.lower()
        source_filters, domain_filters = self._infer_source_domain(query_lower, inp)

        # 2. Check keyword signals
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

        # 3. Default: L1 primary + L3 fallback
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
            conditions = L2Conditions(
                entities=entities if entities else None,
                include_tom_snapshot=True,
                include_relationships=True,
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
        """Basic entity extraction from query (placeholder)."""
        # This is a simplified implementation. In production, could use NER.
        # For now, we return an empty list -- the L2Handler will do full lookups.
        return []

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
你是一个记忆系统的检索意图分析器。根据用户的查询意图，决定应该查询哪些记忆层，并生成每层的检索条件。

记忆层说明：
- L1（事件流）：具体的历史事件、聊天记录、浏览记录、活动记录
- L2（知识图谱）：人物关系、实体属性、用户画像
- L3（反思摘要）：时期总结、主题回顾、洞察结论
- L4（程序性记忆）：工具使用经验、操作策略、最佳实践

注意：
- 时间范围解析由系统处理，你不需要输出时间信息。
- 可以选择多层查询。
- 标记 is_fallback=true 的层只在主查询无结果时执行。
- 对 L2 查询，请提取相关实体名。
- content_query 是传入该层检索引擎的优化后查询文本，应去除时间词和无关修饰。

请返回 JSON：
{
  "layers": [
    {
      "layer": "L1" | "L2" | "L3" | "L4",
      "is_fallback": false | true,
      "content_query": "用于该层检索的关键文本",
      "entities": ["实体名"],
      "source_filters": ["chat", "browser_history"],
      "domain_filters": ["user_authored", "external_activity"]
    }
  ],
  "reasoning": "简短解释"
}"""

_VALID_LAYERS = {"L1", "L2", "L3", "L4"}


class LLMIntentDecider:
    """LLM-based intent decider using CONTEXT_DECIDER scenario."""

    def __init__(self, provider_bridge: Any, *, timeout_seconds: float = 3.0):
        self._bridge = provider_bridge
        self._timeout = timeout_seconds

    async def evaluate(self, inp: IntentDeciderInput) -> IntentDecision | None:
        """Call LLM for intent analysis. Returns None on any failure."""
        user_prompt = f"用户查询：{inp.query}"
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
            return self._parse_response(raw)
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

            if layer == "L1":
                conditions = L1Conditions(
                    content_query=content_query,
                    source_filters=source_filters,
                    domain_filters=domain_filters,
                )
            elif layer == "L2":
                conditions = L2Conditions(
                    entities=entities if entities else None,
                    include_tom_snapshot=True,
                    include_relationships=True,
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
