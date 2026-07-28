"""Controlled metadata contract for the first-context story interaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


FIRST_CONTEXT_STORY_INTERACTION_KIND = "first_context_story"
FIRST_CONTEXT_METADATA_KEY = "first_context"
FIRST_CONTEXT_QUESTIONS: dict[str, frozenset[str]] = {
    "preferred_name": frozenset(
        {
            "希望 Magi 平时怎么称呼你？昵称就可以。",
            "What would you like Magi to call you? A nickname is perfectly fine.",
        }
    ),
    "easy_topic": frozenset(
        {
            "如果现在可以随便聊点什么，什么话题最容易让你有话说？",
            "If we could chat about anything right now, what topic would you have the most to say about?",
        }
    ),
    "current_interest": frozenset(
        {
            "最近有什么东西，是你愿意主动花时间了解的？",
            "What have you been choosing to spend time learning more about lately?",
        }
    ),
    "repeating_content": frozenset(
        {
            "最近有什么内容，是你会忍不住反复看或听的？",
            "What have you found yourself watching or listening to again and again lately?",
        }
    ),
    "recent_feeling": frozenset(
        {
            "最近有哪件小事，让你心情有一点变化？",
            "What small thing recently changed your mood, even a little?",
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
            "The current message was submitted while this optional question was shown. It may or may not answer the question:",
            f"- question_id: {context['question_id']}",
            f"- question: {context['question_text']}",
            "Choose exactly one response path before writing:",
            "- Relevant answer: the message answers the question, or is short or elliptical but clearly relevant. Use the question only as interpretation context while keeping the user's raw message unchanged, then follow the reply behavior below.",
            "- Refusal: accept it briefly without mirroring it as Magi's own preference. Do not ask the question again.",
            "- Question directed at Magi: ignore the displayed question and answer the user's actual question.",
            "- Unrelated message or topic change: ignore the displayed question and respond to the actual message normally.",
            "- Meaningless or incomprehensible input: briefly say it was not understood. Do not guess a name, answer, preference, or intent.",
            "Only the Relevant answer path may use the First Conversation Reply Behavior section below.",
            "Do not redirect the user back to the displayed question or pressure them to answer it.",
            "Treat the question as conversation context, not as a claim made by the user.",
            "# First Conversation Reply Behavior (only when the message answers the question)",
            "Let the reply itself demonstrate attention; do not explain or summarize what was learned.",
            "Stay fully in the active persona's voice and preserve the current relationship distance.",
            'The "preferred_name" question asks what Magi should call the user; it never asks for Magi\'s own name.',
            "If question_id is \"preferred_name\", acknowledge and use the user's name naturally and briefly. Do not answer with Magi's name, analyze the user's name, praise it, or make associations about it.",
            "For other questions, respond to one concrete detail from the user's answer. You may notice at most one relationship between details the user stated, but do not add outside facts.",
            "Use only facts stated by the user or already supplied in trusted conversation context. Do not introduce factual claims about named people, works, places, brands, or products.",
            'Do not merely paraphrase or summarize the user\'s message. Avoid survey-like acknowledgements such as "Thanks for sharing" or "I understand you better now."',
            "Do not infer stable personality traits, motives, emotions, or life circumstances beyond what the user explicitly said.",
            "Keep the reply brief and conversational, usually 1 to 3 sentences.",
            "Do not ask another onboarding-style question in the reply. The product UI owns whether to offer another onboarding prompt.",
            "Do not claim that a memory, profile, or long-term record was successfully saved.",
            "# Decision Examples",
            '- preferred_name + "明日香" is a Relevant answer. Address the user as 明日香; do not reply with Magi\'s own name.',
            '- preferred_name + "你叫什么？" is a Question directed at Magi. Answer that question and do not treat it as the user\'s preferred name.',
            '- preferred_name + "不想说" is a Refusal. Accept it without asking again or saying Magi also does not want to say.',
            '- preferred_name + "asdf123" is Meaningless or incomprehensible. Say it was not understood; do not introduce yourself or ask for a name.',
            '- repeating_content + "I keep listening to X; I really like it" is a Relevant answer.',
            '  Safe meaning: "It sounds like you genuinely like X."',
            '  Unsafe meaning: "X is a great album; it also makes me feel warm." The unsafe reply evaluates and classifies X and invents Magi\'s reaction.',
            "For named content, stay within the safe meaning. Do not describe the work's qualities, claim how it makes Magi feel, or add any fact about it.",
            "These examples define the decision and factual boundary, not the exact wording. Express the reply in the active persona's own voice.",
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
