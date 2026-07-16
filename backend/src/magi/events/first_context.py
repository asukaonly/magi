"""Controlled metadata contract for the first-context story interaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


FIRST_CONTEXT_STORY_INTERACTION_KIND = "first_context_story"
FIRST_CONTEXT_METADATA_KEY = "first_context"
FIRST_CONTEXT_QUESTIONS: dict[str, frozenset[str]] = {
    "recent_feeling": frozenset(
        {
            "最近有哪件小事，让你心情有一点变化？",
            "What small thing recently changed your mood, even a little?",
        }
    ),
    "repeating_content": frozenset(
        {
            "最近有什么内容，是你会忍不住反复看或听的？",
            "What have you found yourself watching or listening to again and again lately?",
        }
    ),
    "personal_time": frozenset(
        {
            "最近一天里，哪段时间最像是“你自己的时间”？",
            "What part of a recent day felt most like time that was truly yours?",
        }
    ),
    "reluctant_routine": frozenset(
        {
            "最近有什么事，明明不太想做，却还是一直在做？",
            "What have you kept doing lately, even though you did not really feel like doing it?",
        }
    ),
}


def normalize_first_context(value: object) -> dict[str, str] | None:
    """Return a compact, validated first-context question reference."""
    if not isinstance(value, Mapping):
        return None
    question_id = str(value.get("question_id") or "").strip()
    question_text = str(value.get("question_text") or "").strip()
    if question_text not in FIRST_CONTEXT_QUESTIONS.get(question_id, frozenset()):
        return None
    return {
        "question_id": question_id,
        "question_text": question_text,
    }


def first_context_from_metadata(metadata: object) -> dict[str, str] | None:
    """Read first-context data only from a matching controlled interaction."""
    if not isinstance(metadata, Mapping):
        return None
    interaction_kind = str(metadata.get("interaction_kind") or "").strip().lower()
    if interaction_kind != FIRST_CONTEXT_STORY_INTERACTION_KIND:
        return None
    return normalize_first_context(metadata.get(FIRST_CONTEXT_METADATA_KEY))


def build_first_context_runtime_guidance(metadata: object) -> str:
    """Build non-evidence guidance that lets chat understand short answers."""
    context = first_context_from_metadata(metadata)
    if context is None:
        return ""
    return "\n".join(
        [
            "# First Conversation Context",
            "The user's current message answers this earlier question:",
            f"- question_id: {context['question_id']}",
            f"- question: {context['question_text']}",
            "Interpret short or elliptical answers relative to that question while keeping the user's raw message unchanged.",
            "Treat the question as conversation context, not as a claim made by the user.",
            "Respond naturally to what the user shared. Do not claim that a memory, profile, or long-term record was successfully saved.",
        ]
    )


def controlled_first_context_metadata(
    *,
    interaction_kind: str | None,
    first_context: object,
) -> dict[str, Any]:
    """Build the only accepted first-context metadata shape."""
    normalized_kind = str(interaction_kind or "").strip().lower()
    if normalized_kind != FIRST_CONTEXT_STORY_INTERACTION_KIND:
        return {}
    normalized_context = normalize_first_context(first_context)
    if normalized_context is None:
        raise ValueError("first_context_story requires a supported question id and text")
    return {
        "interaction_kind": FIRST_CONTEXT_STORY_INTERACTION_KIND,
        FIRST_CONTEXT_METADATA_KEY: normalized_context,
    }


__all__ = [
    "FIRST_CONTEXT_METADATA_KEY",
    "FIRST_CONTEXT_QUESTIONS",
    "FIRST_CONTEXT_STORY_INTERACTION_KIND",
    "build_first_context_runtime_guidance",
    "controlled_first_context_metadata",
    "first_context_from_metadata",
    "normalize_first_context",
]
