"""Interpret natural-language timeline queries with CN/EN relative time and CJK segmentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable

SECONDS_PER_DAY = 24 * 60 * 60.0

_CN_NUMERALS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "两": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}

_EN_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "with",
        "about",
        "that",
        "this",
        "these",
        "those",
        "my",
        "your",
        "did",
        "was",
        "were",
        "is",
        "are",
        "be",
        "been",
        "ago",
        "last",
        "recent",
        "days",
        "day",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "today",
        "yesterday",
    }
)

_CN_FILLER_TOKENS = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "我",
        "你",
        "他",
        "她",
        "它",
        "和",
        "与",
        "这",
        "那",
        "个",
        "里",
        "中",
        "过",
        "都",
        "很",
        "就",
        "去",
        "来",
        "有",
        "做",
        "什么",
        "哪",
        "哪个",
        "哪些",
        "一下",
        "听",
        "看",
        "听过",
        "看过",
    }
)


def _parse_quantity(token: str) -> int | None:
    cleaned = token.strip()
    if cleaned.isdigit():
        return int(cleaned)
    return _CN_NUMERALS.get(cleaned)


@dataclass(frozen=True)
class TimelineQueryInterpretation:
    """Normalized timeline query constraints."""

    raw_query: str
    start: float
    end: float
    residual_terms: list[str]
    mood_hints: list[str]
    activity_hints: list[str]
    time_override: bool = False
    search_query: str = ""

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
    """Extract time windows, mood/activity hints, and tokenized search terms."""

    _MOOD_HINT_ALIASES: dict[str, list[str]] = {
        "low": ["low", "down", "sad", "低落", "疲惫", "沮丧", "难过"],
        "tense": ["tense", "anxious", "stressed", "焦虑", "紧绷", "压力"],
        "warm": ["warm", "positive", "happy", "开心", "高兴", "放松"],
    }

    _ACTIVITY_HINT_ALIASES: dict[str, list[str]] = {
        "game": ["game", "gaming", "游戏", "steam"],
        "coding": ["code", "coding", "开发", "编码", "编程"],
        "chat": ["chat", "聊天", "对话"],
        "music": ["music", "song", "songs", "听歌", "歌曲", "音乐", "歌", "网易云", "netease", "spotify"],
    }

    # Regex patterns checked in priority order; matched text is stripped from lexical search terms.
    _ISO_DATE_RE = re.compile(r"\b(?P<y>20\d{2})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})\b")
    _CN_YMD_RE = re.compile(r"(?P<y>20\d{2})\s*年\s*(?P<m>\d{1,2})\s*月(?:\s*(?P<d>\d{1,2})\s*[日号])?")
    _CN_REL_MONTHS_RE = re.compile(r"(?P<n>\d+|[一二两兩三四五六七八九十]{1,2})\s*个?月前")
    _CN_REL_WEEKS_RE = re.compile(r"(?P<n>\d+|[一二两兩三四五六七八九十]{1,2})\s*(?:周|星期|礼拜)前")
    _CN_REL_DAYS_RE = re.compile(r"(?P<n>\d+|[一二两兩三四五六七八九十]{1,2})\s*天前")
    _EN_REL_MONTHS_RE = re.compile(r"\b(?P<n>\d+)\s+months?\s+ago\b")
    _EN_REL_WEEKS_RE = re.compile(r"\b(?P<n>\d+)\s+weeks?\s+ago\b")
    _EN_REL_DAYS_RE = re.compile(r"\b(?P<n>\d+)\s+days?\s+ago\b")

    def interpret(
        self,
        *,
        query: str | None,
        start: float,
        end: float,
    ) -> TimelineQueryInterpretation:
        normalized = str(query or "").strip().lower()
        effective_start = float(start)
        effective_end = float(end)
        time_override = False
        cleaned = normalized

        if normalized:
            resolved_window, cleaned = self._extract_time_window(
                normalized,
                viewport_start=effective_start,
                viewport_end=effective_end,
            )
            if resolved_window is not None:
                effective_start, effective_end = resolved_window
                time_override = True

        mood_hints = self._extract_hints(cleaned, self._MOOD_HINT_ALIASES)
        activity_hints = self._extract_hints(cleaned, self._ACTIVITY_HINT_ALIASES)

        # Strip matched mood/activity alias phrases from residual terms so they do not
        # double-constrain raw text with a literal keyword mismatch.
        residual_source = cleaned
        for hint in mood_hints:
            residual_source = self._strip_aliases(residual_source, self._MOOD_HINT_ALIASES[hint])
        for hint in activity_hints:
            residual_source = self._strip_aliases(residual_source, self._ACTIVITY_HINT_ALIASES[hint])

        residual_terms = self._tokenize_residual(residual_source, exclude={*mood_hints, *activity_hints})

        search_tokens = list(residual_terms)
        if not search_tokens and activity_hints:
            for hint in activity_hints:
                search_tokens.extend(self._ACTIVITY_HINT_ALIASES[hint][:3])
        search_query = " ".join(dict.fromkeys(search_tokens)).strip()

        return TimelineQueryInterpretation(
            raw_query=normalized,
            start=effective_start,
            end=effective_end,
            residual_terms=residual_terms,
            mood_hints=mood_hints,
            activity_hints=activity_hints,
            time_override=time_override,
            search_query=search_query,
        )

    def expand_hint(self, hint: str) -> list[str]:
        if hint in self._MOOD_HINT_ALIASES:
            return self._MOOD_HINT_ALIASES[hint]
        if hint in self._ACTIVITY_HINT_ALIASES:
            return self._ACTIVITY_HINT_ALIASES[hint]
        return [hint]

    def _extract_time_window(
        self,
        text: str,
        *,
        viewport_start: float,
        viewport_end: float,
    ) -> tuple[tuple[float, float] | None, str]:
        ref = float(viewport_end)

        # 1. Explicit ISO date (YYYY-MM-DD)
        match = self._ISO_DATE_RE.search(text)
        if match:
            try:
                dt = datetime(int(match.group("y")), int(match.group("m")), int(match.group("d")), tzinfo=timezone.utc)
                day_start = dt.timestamp()
                return (day_start, day_start + SECONDS_PER_DAY), self._remove_span(text, match.span())
            except ValueError:
                pass

        # 2. Explicit Chinese YYYY年M月[D日]
        match = self._CN_YMD_RE.search(text)
        if match:
            try:
                year, month = int(match.group("y")), int(match.group("m"))
                if match.group("d"):
                    dt = datetime(year, month, int(match.group("d")), tzinfo=timezone.utc)
                    day_start = dt.timestamp()
                    return (day_start, day_start + SECONDS_PER_DAY), self._remove_span(text, match.span())
                month_start = datetime(year, month, 1, tzinfo=timezone.utc).timestamp()
                next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
                month_end = datetime(next_year, next_month, 1, tzinfo=timezone.utc).timestamp()
                return (month_start, month_end), self._remove_span(text, match.span())
            except ValueError:
                pass

        # 3. Relative N months / weeks / days ago (CN + EN)
        for pattern, unit_days, pad_days in (
            (self._CN_REL_MONTHS_RE, 30.0, 20.0),
            (self._EN_REL_MONTHS_RE, 30.0, 20.0),
            (self._CN_REL_WEEKS_RE, 7.0, 4.0),
            (self._EN_REL_WEEKS_RE, 7.0, 4.0),
            (self._CN_REL_DAYS_RE, 1.0, 1.5),
            (self._EN_REL_DAYS_RE, 1.0, 1.5),
        ):
            match = pattern.search(text)
            if match:
                qty = _parse_quantity(match.group("n"))
                if qty is not None and qty > 0:
                    center = ref - (qty * unit_days * SECONDS_PER_DAY)
                    half = pad_days * SECONDS_PER_DAY
                    return (
                        max(0.0, center - half),
                        min(ref, center + half),
                    ), self._remove_span(text, match.span())

        # 4. Fixed relative CN/EN phrases (cross-viewport expansion, never clamped by max())
        fixed_phrases: tuple[tuple[str, float, float], ...] = (
            ("day before yesterday", 3.0, 1.0),
            ("前天", 3.0, 1.0),
            ("yesterday", 2.0, 0.5),
            ("昨天", 2.0, 0.5),
            ("last week", 7.0, 0.0),
            ("上周", 7.0, 0.0),
            ("recent days", 3.0, 0.0),
            ("最近几天", 3.0, 0.0),
            ("last month", 62.0, 20.0),
            ("上个月", 62.0, 20.0),
            ("上月", 62.0, 20.0),
            ("last year", 400.0, 250.0),
            ("去年", 400.0, 250.0),
            ("today", 1.0, 0.0),
            ("今天", 1.0, 0.0),
        )
        for phrase, back_start_days, back_end_days in fixed_phrases:
            idx = text.find(phrase)
            if idx >= 0:
                win_start = max(0.0, ref - (back_start_days * SECONDS_PER_DAY))
                win_end = max(win_start + 60.0, ref - (back_end_days * SECONDS_PER_DAY))
                return (win_start, win_end), self._remove_span(text, (idx, idx + len(phrase)))

        # 5. Optional dateparser fallback for other explicit calendar expressions
        try:
            from dateparser.search import search_dates

            ref_dt = datetime.fromtimestamp(ref, tz=timezone.utc)
            found = search_dates(
                text,
                languages=["zh", "en"],
                settings={
                    "RELATIVE_BASE": ref_dt.replace(tzinfo=None),
                    "PREFER_DATES_FROM": "past",
                    "STRICT_PARSING": True,
                },
            )
            if found:
                matched_text, parsed_dt = found[0]
                if len(matched_text.strip()) >= 3:
                    ts = parsed_dt.replace(tzinfo=timezone.utc).timestamp()
                    start_ts = max(0.0, ts - SECONDS_PER_DAY)
                    end_ts = ts + SECONDS_PER_DAY
                    pos = text.find(matched_text.lower())
                    stripped = self._remove_span(text, (pos, pos + len(matched_text))) if pos >= 0 else text
                    return (start_ts, end_ts), stripped
        except Exception:
            pass

        return None, text

    @staticmethod
    def _remove_span(text: str, span: tuple[int, int]) -> str:
        start_idx, end_idx = span
        return f"{text[:start_idx]} {text[end_idx:]}".strip()

    @staticmethod
    def _strip_aliases(text: str, aliases: Iterable[str]) -> str:
        updated = text
        for alias in sorted(aliases, key=len, reverse=True):
            if re.fullmatch(r"[a-z0-9]+", alias):
                updated = re.sub(rf"\b{re.escape(alias)}\b", " ", updated)
            else:
                updated = updated.replace(alias, " ")
        return updated

    @staticmethod
    def _tokenize_residual(text: str, *, exclude: set[str]) -> list[str]:
        tokens: list[str] = []
        for match in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text):
            if re.fullmatch(r"[\u4e00-\u9fff]+", match):
                if len(match) <= 2:
                    cleaned_short = "".join(ch for ch in match if ch not in _CN_FILLER_TOKENS)
                    if cleaned_short and cleaned_short not in _CN_FILLER_TOKENS and cleaned_short not in exclude:
                        tokens.append(cleaned_short)
                    continue
                try:
                    import jieba

                    segmented = [tok.strip() for tok in jieba.cut_for_search(match) if tok.strip()]
                except Exception:
                    segmented = [match]
                kept = [
                    tok
                    for tok in segmented
                    if tok not in _CN_FILLER_TOKENS
                    and tok not in exclude
                    and (len(tok) >= 2 or tok not in _CN_FILLER_TOKENS)
                ]
                # Prefer multi-character terms when jieba produced them so single-char sub-tokens
                # do not create noisy over-filtering.
                multi = [tok for tok in kept if len(tok) >= 2]
                tokens.extend(multi if multi else kept)
            else:
                if len(match) >= 2 and match not in _EN_STOPWORDS and match not in exclude:
                    tokens.append(match)
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _extract_hints(normalized_query: str, alias_map: dict[str, list[str]]) -> list[str]:
        hints: list[str] = []
        for canonical, aliases in alias_map.items():
            for alias in aliases:
                if re.fullmatch(r"[a-z0-9]+", alias):
                    if re.search(rf"\b{re.escape(alias)}\b", normalized_query):
                        hints.append(canonical)
                        break
                elif alias in normalized_query:
                    hints.append(canonical)
                    break
        return hints


__all__ = ["TimelineQueryInterpretation", "TimelineQueryInterpreter"]
