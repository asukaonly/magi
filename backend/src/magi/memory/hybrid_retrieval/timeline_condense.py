"""Deterministic timeline condensation for grouped L1 evidence."""

from __future__ import annotations

import re
from typing import Any

from .answerability import (
    extract_event_dates,
    extract_query_phrases,
    extract_query_tokens,
    extract_quoted_spans,
    has_temporal_anchor,
)

# First-person completed-action patterns: the user describing a personal
# experience rather than discussing a topic.  Used as a scoring signal to
# prefer "I took a train" over "I have been tracking travel expenses".
_FIRST_PERSON_ACTION_RE = re.compile(
    r"\bI\s+(?:(?:just|also|recently|actually|finally)\s+)?"
    r"(?:took|rode|drove|flew|walked|ran|went|visited|attended|"
    r"bought|ordered|booked|used|tried|started|finished|completed|"
    r"saw|watched|played|ate|drank|moved|switched|picked|got)\b",
    re.IGNORECASE,
)


def build_timeline_summary(
    *,
    question: str,
    evidence_bundles: list[dict[str, Any]],
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Condense grouped evidence into time-ordered event summary lines."""
    if not evidence_bundles or max_items <= 0:
        return []

    query_tokens = extract_query_tokens(question)
    query_phrases = extract_query_phrases(query_tokens)
    quoted_spans = extract_quoted_spans(question)

    selected: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    represented_sessions: set[str] = set()

    # Preserve one best event per quoted span first so comparison questions keep both sides.
    for quoted_span in quoted_spans:
        best_match = None
        best_score = float("-inf")
        for bundle in evidence_bundles:
            for event in bundle.get("events") or []:
                event_id = str(event.get("event_id") or "")
                if not event_id or event_id in seen_event_ids:
                    continue
                content = str(event.get("content") or "")
                normalized_content = " ".join(extract_query_tokens(content))
                if quoted_span not in normalized_content:
                    continue
                score = _score_event(event, query_tokens=query_tokens, query_phrases=query_phrases, quoted_spans=[quoted_span])
                if score > best_score:
                    best_score = score
                    best_match = event
        if best_match is not None:
            selected.append(best_match)
            seen_event_ids.add(str(best_match.get("event_id") or ""))
            represented_sessions.add(str(best_match.get("session_id") or "").strip())

    # Fill the rest with the best remaining event per bundle.
    candidates: list[tuple[float, dict[str, Any]]] = []
    for bundle in evidence_bundles:
        best_event = None
        best_score = float("-inf")
        for event in bundle.get("events") or []:
            event_id = str(event.get("event_id") or "")
            if not event_id or event_id in seen_event_ids:
                continue
            score = _score_event(event, query_tokens=query_tokens, query_phrases=query_phrases, quoted_spans=quoted_spans)
            if score > best_score:
                best_score = score
                best_event = event
        if best_event is not None:
            candidates.append((best_score, best_event))

    candidates.sort(key=lambda item: (item[0], float(item[1].get("timestamp") or 0.0)), reverse=True)
    for _, event in candidates:
        event_id = str(event.get("event_id") or "")
        session_id = str(event.get("session_id") or "").strip()
        if event_id in seen_event_ids:
            continue
        if session_id and session_id in represented_sessions:
            continue
        selected.append(event)
        seen_event_ids.add(event_id)
        if session_id:
            represented_sessions.add(session_id)
        if len(selected) >= max_items:
            break

    selected.sort(key=lambda event: float(event.get("timestamp") or 0.0))
    return [_summarize_event(event, query_tokens=query_tokens, query_phrases=query_phrases, quoted_spans=quoted_spans) for event in selected[:max_items]]


def _score_event(
    event: dict[str, Any],
    *,
    query_tokens: list[str],
    query_phrases: list[str],
    quoted_spans: list[str],
) -> float:
    content = str(event.get("content") or "")
    author_type = str(event.get("author_type") or "").strip().lower()
    lowered = content.lower()
    content_token_list = extract_query_tokens(content)
    content_tokens = set(content_token_list)
    matched_tokens = [token for token in query_tokens if token in content_tokens]
    phrase_hits = [phrase for phrase in query_phrases if phrase and phrase in lowered]
    normalized_content = " ".join(content_token_list)
    quoted_hits = [phrase for phrase in quoted_spans if phrase and phrase in normalized_content]

    experiential = author_type == "user" and _FIRST_PERSON_ACTION_RE.search(content) is not None

    token_ratio = len(matched_tokens) / len(query_tokens) if query_tokens else 0.0
    # Assistant messages tend to be longer and discuss the topic extensively,
    # inflating token overlap.  Dampen their contribution so that shorter user
    # statements describing actual events are preferred in the timeline.
    if author_type != "user":
        token_ratio *= 0.5

    return (
        (0.35 if author_type == "user" else 0.0)
        + token_ratio
        + min(len(phrase_hits), 4) * 0.15
        + min(len(quoted_hits), 2) * (0.45 if author_type == "user" else 0.1)
        + (0.20 if experiential else 0.0)
    )


def _summarize_event(
    event: dict[str, Any],
    *,
    query_tokens: list[str],
    query_phrases: list[str],
    quoted_spans: list[str],
) -> dict[str, Any]:
    content = " ".join(str(event.get("content") or "").split())
    author_type = str(event.get("author_type") or "").strip().lower()
    truncated = _select_summary_text(
        content,
        author_type=author_type,
        query_phrases=query_phrases,
        quoted_spans=quoted_spans,
        max_chars=220,
    )

    reason_codes: list[str] = []
    normalized = " ".join(extract_query_tokens(content))
    if any(phrase and phrase in normalized for phrase in quoted_spans):
        reason_codes.append("quoted_span_match")
    if any(phrase and phrase in content.lower() for phrase in query_phrases):
        reason_codes.append("phrase_match")
    if author_type == "user":
        reason_codes.append("user_message")
    if has_temporal_anchor(content):
        reason_codes.append("temporal_anchor")

    event_dates = extract_event_dates(content)

    return {
        "timestamp": float(event.get("timestamp") or 0.0),
        "session_id": str(event.get("session_id") or "").strip(),
        "turn_id": str(event.get("turn_id") or "").strip(),
        "author_type": str(event.get("author_type") or "").strip() or "unknown",
        "summary": truncated,
        "event_date": event_dates[0] if event_dates else None,
        "supporting_event_ids": [str(event.get("event_id") or "")],
        "reason_codes": reason_codes,
    }


def _select_summary_text(
    content: str,
    *,
    author_type: str,
    query_phrases: list[str],
    quoted_spans: list[str],
    max_chars: int,
) -> str:
    segments = [segment.strip() for segment in re.split(r"(?<=[.!?。！？])\s+", content) if segment.strip()]
    best_segment = content
    best_score = float("-inf")

    for segment in segments or [content]:
        lowered = segment.lower()
        normalized = " ".join(extract_query_tokens(segment))
        score = (
            min(sum(1 for phrase in query_phrases if phrase and phrase in lowered), 4) * 0.15
            + min(sum(1 for phrase in quoted_spans if phrase and phrase in normalized), 2) * 0.45
            + (0.10 if has_temporal_anchor(segment) else 0.0)
        )
        if score > best_score:
            best_score = score
            best_segment = segment

    if len(best_segment) <= max_chars:
        return best_segment

    return _truncate_around_salient_anchor(best_segment, quoted_spans=quoted_spans, max_chars=max_chars)


def _truncate_around_salient_anchor(content: str, *, quoted_spans: list[str], max_chars: int) -> str:
    anchor_index = _find_salient_anchor_index(content, quoted_spans=quoted_spans)
    if anchor_index is None:
        truncated = content[:max_chars].rstrip()
        return f"{truncated}..." if len(content) > max_chars else truncated

    half_window = max(max_chars // 2, 40)
    start = max(anchor_index - half_window, 0)
    end = min(start + max_chars, len(content))
    start = max(end - max_chars, 0)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = f"...{snippet.lstrip()}"
    if end < len(content):
        snippet = f"{snippet.rstrip()}..."
    return snippet


def _find_salient_anchor_index(content: str, *, quoted_spans: list[str]) -> int | None:
    normalized = " ".join(extract_query_tokens(content))
    for phrase in quoted_spans:
        if not phrase:
            continue
        collapsed = phrase.replace(" ", r"\s+")
        match = re.search(collapsed, content, flags=re.IGNORECASE)
        if match:
            return match.start()
        if phrase in normalized:
            raw_tokens = extract_query_tokens(content)
            prefix = " ".join(raw_tokens)
            raw_index = prefix.find(phrase)
            if raw_index >= 0:
                return min(raw_index, len(content) - 1)

    temporal_match = re.search(
        r"\b(last|yesterday|today|tomorrow|ago|week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        content,
        flags=re.IGNORECASE,
    )
    if temporal_match:
        return temporal_match.start()
    return None
