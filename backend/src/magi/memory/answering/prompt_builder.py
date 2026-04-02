"""Shared prompt-building helpers for memory answering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_ASSISTANT_CONTENT_MAX_CHARS = 300


@dataclass(frozen=True)
class AnswerPromptPayload:
    """Formatted evidence payload for narrow memory answer synthesis."""

    evidence_text: str
    timeline_text: str
    bundle_text: str
    prioritize_timeline: bool
    short_answer_instruction: str
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


def should_request_short_issue_answer(question: str) -> bool:
    lowered = str(question or "").lower()
    return any(marker in lowered for marker in (" issue", " problem", " wrong with"))


def build_answer_prompt_payload(
    *,
    question: str,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None = None,
    timeline_summary: list[dict[str, Any]] | None = None,
) -> AnswerPromptPayload:
    prioritize_timeline = should_prioritize_timeline(question, timeline_summary)

    evidence_blocks: list[str] = []
    for index, hit in enumerate(hits, start=1):
        content = str(hit.get("content") or "").strip()
        if not content:
            continue
        if prioritize_timeline:
            content = _maybe_truncate_assistant_content(content, hit)
        session_id = str(hit.get("session_id") or "").strip() or "unknown-session"
        turn_id = str(hit.get("turn_id") or "").strip() or "unknown-turn"
        evidence_blocks.append(f"[{index}] session={session_id} turn={turn_id}\n{content}")
    evidence_text = "\n\n".join(evidence_blocks) if evidence_blocks else "(no evidence retrieved)"
    timeline_blocks: list[str] = []
    for index, item in enumerate(timeline_summary or [], start=1):
        timestamp = item.get("timestamp")
        session_id = str(item.get("session_id") or "").strip() or "unknown-session"
        turn_id = str(item.get("turn_id") or "").strip() or "unknown-turn"
        author_type = str(item.get("author_type") or "unknown").strip() or "unknown"
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        timeline_blocks.append(
            f"[{index}] t={timestamp} session={session_id} role={author_type} turn={turn_id}\n{summary}"
        )
    timeline_text = "\n\n".join(timeline_blocks) if timeline_blocks else "(no timeline summary available)"

    bundle_blocks: list[str] = []
    for bundle_index, bundle in enumerate(evidence_bundles or [], start=1):
        session_id = str(bundle.get("session_id") or "").strip() or "unknown-session"
        events = list(bundle.get("events") or [])
        lines: list[str] = [f"[bundle {bundle_index}] session={session_id}"]
        for event in events:
            turn_id = str(event.get("turn_id") or "").strip() or "unknown-turn"
            timestamp = event.get("timestamp")
            author_type = str(event.get("author_type") or "unknown").strip() or "unknown"
            content = str(event.get("content") or "").strip()
            if not content:
                continue
            if prioritize_timeline and author_type == "assistant" and len(content) > _ASSISTANT_CONTENT_MAX_CHARS:
                content = content[:_ASSISTANT_CONTENT_MAX_CHARS] + "..."
            lines.append(f"- t={timestamp} role={author_type} turn={turn_id}: {content}")
        bundle_blocks.append("\n".join(lines))
    bundle_text = "\n\n".join(bundle_blocks) if bundle_blocks else "(no grouped evidence bundles)"

    timeline_instruction = ""
    if prioritize_timeline:
        timeline_instruction = (
            "Answer from the Timeline Summary first for temporal or comparison questions.\n"
            "Use Session Evidence Bundles or Retrieved Evidence only if the timeline summary is ambiguous.\n\n"
        )

    short_answer_instruction = ""
    if should_request_short_issue_answer(question):
        short_answer_instruction = (
            "For issue or event questions, answer with the short issue name or event phrase only.\n"
            "Do not include dates, justification, or extra explanation.\n\n"
        )

    return AnswerPromptPayload(
        evidence_text=evidence_text,
        timeline_text=timeline_text,
        bundle_text=bundle_text,
        prioritize_timeline=prioritize_timeline,
        short_answer_instruction=short_answer_instruction,
        timeline_instruction=timeline_instruction,
    )


def _maybe_truncate_assistant_content(content: str, hit: dict[str, Any]) -> str:
    """Truncate assistant-authored evidence to reduce noise."""
    metadata = hit.get("metadata") or {}
    author_type = str(metadata.get("author_type") or hit.get("author_type") or "").strip()
    if author_type == "assistant" and len(content) > _ASSISTANT_CONTENT_MAX_CHARS:
        return content[:_ASSISTANT_CONTENT_MAX_CHARS] + "..."
    return content
