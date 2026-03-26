"""Interpret lightweight natural-language timeline queries."""

from __future__ import annotations

from dataclasses import dataclass
import re


SECONDS_PER_DAY = 24 * 60 * 60.0


@dataclass(frozen=True)
class TimelineQueryInterpretation:
    """Normalized timeline query constraints."""

    raw_query: str
    start: float
    end: float
    residual_terms: list[str]
    mood_hints: list[str]
    activity_hints: list[str]

    @property
    def search_terms(self) -> list[str]:
        terms = list(self.residual_terms)
        for hint in [*self.mood_hints, *self.activity_hints]:
            if hint not in terms:
                terms.append(hint)
        return terms

    @property
    def has_filters(self) -> bool:
        return bool(self.raw_query.strip())


class TimelineQueryInterpreter:
    """Extract coarse time, mood, and activity hints from a query string."""

    _TIME_HINTS = {
        "上周": 7,
        "last week": 7,
        "最近几天": 3,
        "recent days": 3,
        "today": 1,
        "今天": 1,
    }

    _MOOD_HINT_ALIASES = {
        "low": ["low", "down", "sad", "低落", "疲惫", "沮丧"],
        "tense": ["tense", "anxious", "焦虑", "紧绷"],
        "warm": ["warm", "positive", "开心", "高兴"],
    }

    _ACTIVITY_HINT_ALIASES = {
        "game": ["game", "gaming", "游戏", "steam"],
        "coding": ["code", "coding", "开发", "编码", "编程"],
        "chat": ["chat", "聊天", "对话"],
    }

    _STOP_TERMS = {
        "上周",
        "最近几天",
        "今天",
        "last",
        "week",
        "recent",
        "days",
        "today",
        "低落",
        "焦虑",
        "游戏",
        "coding",
        "game",
        "chat",
        "聊天",
        "开发",
        "编码",
        "编程",
    }

    def interpret(self, *, query: str | None, start: float, end: float) -> TimelineQueryInterpretation:
        normalized = str(query or "").strip().lower()
        effective_start = float(start)
        effective_end = float(end)

        for phrase, days in self._TIME_HINTS.items():
            if phrase in normalized:
                effective_start = max(effective_start, effective_end - (days * SECONDS_PER_DAY))

        mood_hints = self._extract_hints(normalized, self._MOOD_HINT_ALIASES)
        activity_hints = self._extract_hints(normalized, self._ACTIVITY_HINT_ALIASES)

        raw_terms = [term for term in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized) if term]
        residual_terms = [
            term
            for term in raw_terms
            if term not in self._STOP_TERMS and term not in mood_hints and term not in activity_hints
        ]

        return TimelineQueryInterpretation(
            raw_query=normalized,
            start=effective_start,
            end=effective_end,
            residual_terms=residual_terms,
            mood_hints=mood_hints,
            activity_hints=activity_hints,
        )

    def expand_hint(self, hint: str) -> list[str]:
        if hint in self._MOOD_HINT_ALIASES:
            return self._MOOD_HINT_ALIASES[hint]
        if hint in self._ACTIVITY_HINT_ALIASES:
            return self._ACTIVITY_HINT_ALIASES[hint]
        return [hint]

    @staticmethod
    def _extract_hints(normalized_query: str, alias_map: dict[str, list[str]]) -> list[str]:
        hints: list[str] = []
        for canonical, aliases in alias_map.items():
            if any(alias in normalized_query for alias in aliases):
                hints.append(canonical)
        return hints


__all__ = ["TimelineQueryInterpretation", "TimelineQueryInterpreter"]
