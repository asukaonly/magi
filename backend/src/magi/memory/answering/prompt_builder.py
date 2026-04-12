"""Shared prompt-building helpers for memory answering."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# Sentence-based truncation parameters for assistant replies.
_ASSISTANT_MAX_SENTENCES = 8
_ASSISTANT_HARD_MAX = 1200

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


@dataclass(frozen=True)
class AnswerPromptPayload:
    """Formatted evidence payload for narrow memory answer synthesis."""

    evidence_text: str
    timeline_text: str
    bundle_text: str
    prioritize_timeline: bool
    timeline_instruction: str


def should_prioritize_timeline(question: str, timeline_summary: list[dict[str, Any]] | None) -> bool:
    if not timeline_summary:
        return False
    lowered = str(question or "").lower()
    temporal_markers = (
        " first",
        " before",
        " after",
        " earlier",
        " later",
        " last ",
        " most recent",
        " happened first",
        " occurred first",
    )
    return any(marker in lowered for marker in temporal_markers)


def build_answer_prompt_payload(
    *,
    question: str,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None = None,
    timeline_summary: list[dict[str, Any]] | None = None,
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
        timeline_blocks.append(
            f"[{index}] {date_prefix}session={session_id} role={author_type} turn={turn_id}\n{summary}"
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
            "Answer from the Timeline Summary first for temporal or comparison questions.\n"
            "Use Session Evidence Bundles or Retrieved Evidence only if the timeline summary is ambiguous.\n"
            "IMPORTANT: Timeline dates are *conversation* dates, not necessarily *event* dates. "
            "If bundle content mentions a specific event date (e.g. 'on February 20th', "
            "'last Tuesday', 'on Black Friday'), use that date instead of the session's timeline date.\n\n"
        )

    return AnswerPromptPayload(
        evidence_text=evidence_text,
        timeline_text=timeline_text,
        bundle_text=bundle_text,
        prioritize_timeline=prioritize_timeline,
        timeline_instruction=timeline_instruction,
    )
