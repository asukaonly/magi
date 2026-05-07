"""Shared prompt-building helpers for memory answering."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# Sentence-based truncation parameters for assistant replies. Replies feed
# back into memory-answering prompts as context, so we cap them aggressively:
# 60 sentences covers a thorough multi-paragraph answer, and the 4k-character
# hard ceiling protects against pathologically long single sentences (e.g.
# code blocks or tables emitted as one "sentence") blowing past the prompt
# budget.
_ASSISTANT_MAX_SENTENCES = 60
_ASSISTANT_HARD_MAX = 4000

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _format_ts(ts: float | None) -> str:
    """Return a human-readable timestamp string for LLM context."""
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %a %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _format_date(ts: float | None) -> str:
    """Return a date-only string (no time) to avoid replay-timestamp pollution."""
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %a")
    except (OSError, OverflowError, ValueError):
        return ""


def _truncate_assistant_content(
    content: str,
    max_sentences: int = _ASSISTANT_MAX_SENTENCES,
    hard_max: int = _ASSISTANT_HARD_MAX,
) -> str:
    """Truncate assistant replies by keeping the first N complete sentences.

    Sentence-level truncation preserves semantic units (facts, acknowledgments)
    that character-level head+tail splitting would break mid-sentence.
    """
    stripped = content.strip()
    if len(stripped) <= hard_max:
        return stripped
    sentences = _SENTENCE_BOUNDARY.split(stripped)
    if not sentences:
        return stripped[:hard_max]
    kept: list[str] = []
    total = 0
    for sent in sentences[:max_sentences]:
        if total + len(sent) > hard_max and kept:
            break
        kept.append(sent)
        total += len(sent) + 1
    result = " ".join(kept)
    if len(result) > hard_max:
        result = result[:hard_max].rsplit(" ", 1)[0] + " ..."
    return result


def is_preference_question(question: str) -> bool:
    """Detect recommendation / suggestion / advice questions."""
    lowered = str(question or "").lower()
    preference_markers = (
        "recommend",
        "suggest",
        "any tips",
        "any advice",
        "any ideas",
        "what do you think",
        "do you think it would be",
        "do you think it might",
        "do you think i should",
        "what should i",
        "any suggestions",
        "documentary recommendations",
        "any recommendations",
    )
    return any(marker in lowered for marker in preference_markers)


@dataclass(frozen=True)
class AnswerPromptPayload:
    """Formatted evidence payload for narrow memory answer synthesis."""

    evidence_text: str
    timeline_text: str
    bundle_text: str
    episode_text: str
    prioritize_timeline: bool
    timeline_instruction: str
    preference_instruction: str


_TIMELINE_PRIORITY_RE = re.compile(
    r"\b(?:"
    r"(?:happened|occurred|came)\s+first"
    r"|did\b(?:\s+\w+){0,3}\s+first"
    r"|first\s+(?:time|happened|occurred)"
    r"|before\s+(?:or\s+after|that|this|then)"
    r"|after\s+(?:or\s+before|that|this|then)"
    r"|(?:earlier|later)\s+than"
    r"|most\s+recent"
    r"|chronolog"
    r"|in\s+(?:what\s+)?order"
    r"|(?:happened|occurred|started)\s+(?:before|after|earlier|later)"
    r")\b",
    re.IGNORECASE,
)


def should_prioritize_timeline(question: str, timeline_summary: list[dict[str, Any]] | None) -> bool:
    if not timeline_summary:
        return False
    return bool(_TIMELINE_PRIORITY_RE.search(question or ""))


def build_answer_prompt_payload(
    *,
    question: str,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None = None,
    timeline_summary: list[dict[str, Any]] | None = None,
    l2_episodes: list[dict[str, Any]] | None = None,
) -> AnswerPromptPayload:
    evidence_blocks: list[tuple[str, dict[str, Any]]] = []
    for index, hit in enumerate(hits, start=1):
        content = str(hit.get("content") or "").strip()
        if not content:
            continue
        session_id = str(hit.get("session_id") or "").strip() or "unknown-session"
        turn_id = str(hit.get("turn_id") or "").strip() or "unknown-turn"
        evidence_blocks.append((f"[{index}] session={session_id} turn={turn_id}\n{content}", hit))

    prioritize_timeline = should_prioritize_timeline(question, timeline_summary)
    timeline_blocks: list[str] = []
    for index, item in enumerate(timeline_summary or [], start=1):
        timestamp = item.get("timestamp")
        session_id = str(item.get("session_id") or "").strip() or "unknown-session"
        turn_id = str(item.get("turn_id") or "").strip() or "unknown-turn"
        author_type = str(item.get("author_type") or "unknown").strip() or "unknown"
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        date_prefix = f"{_format_date(timestamp)} " if timestamp else ""
        event_date = item.get("event_date")
        event_date_note = f" (event date: {event_date})" if event_date else ""
        timeline_blocks.append(
            f"[{index}] {date_prefix}session={session_id} role={author_type} turn={turn_id}{event_date_note}\n{summary}"
        )
    timeline_text = "\n\n".join(timeline_blocks) if timeline_blocks else "(no timeline summary available)"

    bundle_blocks: list[str] = []
    bundle_turn_ids: dict[str, int] = {}  # turn_id → bundle index
    for bundle_index, bundle in enumerate(evidence_bundles or [], start=1):
        session_id = str(bundle.get("session_id") or "").strip() or "unknown-session"
        events = list(bundle.get("events") or [])
        lines: list[str] = [f"[bundle {bundle_index}] session={session_id}"]
        seen_turn_ids: set[str] = set()
        for event in events:
            turn_id = str(event.get("turn_id") or "").strip() or "unknown-turn"
            if turn_id in seen_turn_ids:
                continue
            seen_turn_ids.add(turn_id)
            author_type = str(event.get("author_type") or "unknown").strip() or "unknown"
            content = str(event.get("content") or "").strip()
            if not content:
                continue
            if author_type == "assistant":
                content = _truncate_assistant_content(content)
            lines.append(f"- role={author_type} turn={turn_id}: {content}")
            bundle_turn_ids[turn_id] = bundle_index
        bundle_blocks.append("\n".join(lines))
    bundle_text = "\n\n".join(bundle_blocks) if bundle_blocks else "(no grouped evidence bundles)"

    # Deduplicate: skip hits already present in evidence bundles.
    # When all hits are deduped, generate a focus hint pointing to the
    # most relevant bundles so the LLM knows where to look.
    deduped_evidence_blocks: list[str] = []
    deduped_bundle_refs: Counter[int] = Counter()
    for block_text, hit in evidence_blocks:
        hit_turn = str(hit.get("turn_id") or "").strip()
        if hit_turn and hit_turn in bundle_turn_ids:
            deduped_bundle_refs[bundle_turn_ids[hit_turn]] += 1
            continue
        deduped_evidence_blocks.append(block_text)

    if deduped_evidence_blocks:
        evidence_text = "\n\n".join(deduped_evidence_blocks)
    elif deduped_bundle_refs:
        total = sum(deduped_bundle_refs.values())
        focus = ", ".join(
            f"bundle {b}" for b, _ in deduped_bundle_refs.most_common()
        )
        evidence_text = f"({total} hits, all covered in session bundles above — focus: {focus})"
    else:
        evidence_text = "(no additional evidence)"

    timeline_instruction = ""
    if prioritize_timeline:
        timeline_instruction = (
            "TIMELINE PRIORITY — Timeline Summary entries are sorted chronologically (oldest first).\n"
            "For 'most recently' / 'last time' questions, the LAST entry mentioning the relevant topic is the answer.\n"
            "For 'first time' questions, the FIRST entry mentioning the relevant topic is the answer.\n"
            "Do NOT let the volume or frequency of a topic in Session Evidence Bundles override the timeline ordering.\n"
            "Use Session Evidence Bundles or Retrieved Evidence only to clarify details when the timeline summary is ambiguous.\n"
            "IMPORTANT: Timeline dates are *conversation* dates, not necessarily *event* dates. "
            "If bundle content mentions a specific event date (e.g. 'on February 20th', "
            "'last Tuesday', 'on Black Friday'), use that date instead of the session's timeline date.\n\n"
        )

    preference_instruction = ""
    if is_preference_question(question):
        preference_instruction = (
            "This question asks for recommendations or suggestions. "
            "Ground your answer in the user's specific context from the evidence: "
            "mention their actual interests, past experiences, owned items, stated preferences, "
            "and constraints (budget, time, skill level, etc.). "
            "Do not give generic advice that ignores the user's personal context.\n\n"
        )

    episode_blocks: list[str] = []
    for ep in l2_episodes or []:
        label = str(ep.get("label") or "").strip()
        summary = str(ep.get("summary") or "").strip()
        if not summary:
            continue
        time_start = _format_date(ep.get("time_start"))
        time_end = _format_date(ep.get("time_end"))
        time_range = f"{time_start} ~ {time_end}" if time_start and time_end else (time_start or time_end or "")
        header = f"[{label}]" if label else "[episode]"
        if time_range:
            header += f" ({time_range})"
        episode_blocks.append(f"{header}\n{summary}")
    episode_text = "\n\n".join(episode_blocks) if episode_blocks else ""

    return AnswerPromptPayload(
        evidence_text=evidence_text,
        timeline_text=timeline_text,
        bundle_text=bundle_text,
        episode_text=episode_text,
        prioritize_timeline=prioritize_timeline,
        timeline_instruction=timeline_instruction,
        preference_instruction=preference_instruction,
    )
