"""Deterministic reducers for memory answering."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any

from ..hybrid_retrieval.answerability import extract_query_tokens, extract_temporal_distance_queries

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _parse_relative_number(token: str) -> int | None:
    normalized = str(token or "").strip().lower()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    return _NUMBER_WORDS.get(normalized)


def _score_anchor_overlap(anchor_tokens: set[str], text: str) -> float:
    if not anchor_tokens:
        return 0.0
    normalized_tokens = set(extract_query_tokens(text))
    score = float(len(anchor_tokens & normalized_tokens))
    surface_tokens = set(re.findall(r"[a-z0-9]+", str(text or "").lower()))
    remaining = anchor_tokens - normalized_tokens
    for anchor_token in remaining:
        if any(
            surface.startswith(anchor_token) or anchor_token.startswith(surface)
            for surface in surface_tokens
        ):
            score += 0.5
    return score


def _extract_explicit_calendar_date_candidates(text: str) -> list[tuple[date, tuple[int, int]]]:
    content = str(text or "").strip()
    if not content:
        return []

    candidates: list[tuple[date, tuple[int, int]]] = []

    for month_name_match in re.finditer(
        r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)\s+"
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{4}))?\b",
        content,
        flags=re.IGNORECASE,
    ):
        month = _MONTH_NAMES[str(month_name_match.group("month") or "").lower()]
        day = int(month_name_match.group("day"))
        year_str = month_name_match.group("year")
        year = int(year_str) if year_str else 2000
        candidates.append((date(year, month, day), month_name_match.span()))

    for numeric_match in re.finditer(
        r"\b(?P<month>\d{1,2})[/-](?P<day>\d{1,2})(?:[/-](?P<year>\d{4}))?\b", content
    ):
        year_str = numeric_match.group("year")
        year = int(year_str) if year_str else 2000
        candidates.append(
            (
                date(year, int(numeric_match.group("month")), int(numeric_match.group("day"))),
                numeric_match.span(),
            )
        )
    return candidates


def _extract_relative_week_date_candidates(
    text: str,
    *,
    reference_date: date | None,
) -> list[tuple[date, tuple[int, int]]]:
    if reference_date is None:
        return []
    content = str(text or "")
    candidates: list[tuple[date, tuple[int, int]]] = []
    for match in re.finditer(r"\blast week\b", content, flags=re.IGNORECASE):
        candidates.append((reference_date - timedelta(days=7), match.span()))
    for match in re.finditer(
        r"\b(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+weeks?\s+ago\b",
        content,
        flags=re.IGNORECASE,
    ):
        count = _parse_relative_number(match.group("count"))
        if count is None:
            continue
        candidates.append((reference_date - timedelta(days=7 * count), match.span()))
    for match in re.finditer(
        r"\bfor\s+(?:about\s+)?(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+weeks?\s+now\b",
        content,
        flags=re.IGNORECASE,
    ):
        count = _parse_relative_number(match.group("count"))
        if count is None:
            continue
        candidates.append((reference_date - timedelta(days=7 * count), match.span()))
    return candidates


def _extract_relative_month_date_candidates(
    text: str,
    *,
    reference_date: date | None,
) -> list[tuple[date, tuple[int, int]]]:
    if reference_date is None:
        return []
    content = str(text or "")
    candidates: list[tuple[date, tuple[int, int]]] = []
    for match in re.finditer(r"\blast month\b", content, flags=re.IGNORECASE):
        month = reference_date.month - 1 or 12
        year = reference_date.year if reference_date.month > 1 else reference_date.year - 1
        candidates.append((date(year, month, reference_date.day), match.span()))
    for match in re.finditer(
        r"\b(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+months?\s+ago\b",
        content,
        flags=re.IGNORECASE,
    ):
        count = _parse_relative_number(match.group("count"))
        if count is None:
            continue
        month = reference_date.month - count
        year = reference_date.year
        while month < 1:
            month += 12
            year -= 1
        day = min(reference_date.day, 28)
        candidates.append((date(year, month, day), match.span()))
    return candidates


def _extract_anchor_calendar_date(
    text: str,
    anchor_tokens: set[str],
    *,
    anchor_query: str | None = None,
    reference_date: date | None = None,
) -> date | None:
    candidates = _extract_explicit_calendar_date_candidates(text)
    candidates.extend(_extract_relative_week_date_candidates(text, reference_date=reference_date))
    candidates.extend(_extract_relative_month_date_candidates(text, reference_date=reference_date))
    if not candidates:
        return None
    if len(candidates) == 1 or not anchor_tokens:
        return candidates[0][0]

    content = str(text or "")
    lead_tokens = extract_query_tokens(anchor_query or "")[:2]
    best_date: date | None = None
    best_score = -1.0
    for candidate_date, (start, end) in candidates:
        local_context_start = max(0, start - 32)
        local_context_end = min(len(content), end + 8)
        local_context = content[local_context_start:local_context_end]
        context_start = max(0, start - 80)
        context_end = min(len(content), end + 24)
        context = content[context_start:context_end]
        score = (2.0 * _score_anchor_overlap(anchor_tokens, local_context)) + (
            0.5 * _score_anchor_overlap(anchor_tokens, context)
        )
        if lead_tokens:
            score += 2.5 * _score_anchor_overlap(set(lead_tokens), local_context)
        if start > 0:
            prior_sentence = content[max(0, start - 120):start]
            score += 0.25 * _score_anchor_overlap(anchor_tokens, prior_sentence)
        if score > best_score:
            best_score = score
            best_date = candidate_date
    return best_date


def resolve_temporal_distance_answer(
    *,
    question: str,
    timeline_summary: list[dict[str, Any]] | None,
    query_timestamp: float | None = None,
) -> str | None:
    lowered = str(question or "").lower()
    unit: str | None = None
    if re.search(r"\bhow many days?\b", lowered):
        unit = "day"
    elif re.search(r"\bhow many weeks?\b", lowered):
        unit = "week"
    elif re.search(r"\bhow many months?\b", lowered):
        unit = "month"
    elif "how long had i been" in lowered:
        unit = "duration_auto"

    if unit is None:
        return None
    anchor_queries = extract_temporal_distance_queries(question)
    if not timeline_summary:
        return None

    is_ago_question = bool(re.search(r"\bhow many\s+\w+\s+ago\b", lowered))
    reference_date = datetime.fromtimestamp(query_timestamp).date() if query_timestamp is not None else None

    # "X ago" questions: single anchor + reference_date as second point
    if is_ago_question and len(anchor_queries) == 1 and reference_date is not None:
        anchor_queries_to_use = anchor_queries[:1]
    elif len(anchor_queries) >= 2:
        anchor_queries_to_use = anchor_queries[:2]
    else:
        return None

    chosen_dates: list[date] = []
    used_turn_ids: set[str] = set()
    for anchor_query in anchor_queries_to_use:
        anchor_tokens = set(extract_query_tokens(anchor_query))
        if not anchor_tokens:
            return None
        best_item: dict[str, Any] | None = None
        best_score = 0.0
        for item in timeline_summary:
            turn_id = str(item.get("turn_id") or "")
            if turn_id in used_turn_ids:
                continue
            summary = str(item.get("summary") or "").strip()
            parsed_date = _extract_anchor_calendar_date(
                summary,
                anchor_tokens,
                anchor_query=anchor_query,
                reference_date=reference_date,
            )
            if parsed_date is None:
                continue
            overlap = _score_anchor_overlap(anchor_tokens, summary)
            if overlap <= 0:
                continue
            score = overlap / max(len(anchor_tokens), 1)
            if score > best_score:
                best_score = score
                best_item = item
        if best_item is None:
            return None
        used_turn_ids.add(str(best_item.get("turn_id") or ""))
        chosen_date = _extract_anchor_calendar_date(
            str(best_item.get("summary") or ""),
            anchor_tokens,
            anchor_query=anchor_query,
            reference_date=reference_date,
        )
        if chosen_date is None:
            return None
        chosen_dates.append(chosen_date)

    if len(chosen_dates) == 1 and is_ago_question and reference_date is not None:
        chosen_dates.append(reference_date)

    if len(chosen_dates) != 2:
        return None
    delta_days = abs((chosen_dates[1] - chosen_dates[0]).days)
    if unit == "day":
        return f"{delta_days} day" if delta_days == 1 else f"{delta_days} days"
    if unit in {"week", "duration_auto"}:
        if delta_days % 7 != 0:
            return None
        delta_weeks = delta_days // 7
        return f"{delta_weeks} week" if delta_weeks == 1 else f"{delta_weeks} weeks"
    if unit == "month":
        earlier, later = sorted(chosen_dates)
        delta_months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
        if delta_months < 1:
            return None
        return f"{delta_months} month" if delta_months == 1 else f"{delta_months} months"
    return None
