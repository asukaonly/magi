"""Tests for the controlled first-context question contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi.events.first_context import (
    FIRST_CONTEXT_QUESTIONS,
    build_first_context_runtime_guidance,
    normalize_first_context,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("language", ["zh-CN", "en"])
def test_registered_questions_match_onboarding_locale(language: str) -> None:
    locale_path = (
        REPO_ROOT
        / "frontend"
        / "src"
        / "i18n"
        / "locales"
        / language
        / "onboarding.json"
    )
    locale = json.loads(locale_path.read_text(encoding="utf-8"))
    questions = locale["firstContext"]["story"]["questions"]

    assert list(questions) == list(FIRST_CONTEXT_QUESTIONS)
    for question_id, question_text in questions.items():
        assert question_text in FIRST_CONTEXT_QUESTIONS[question_id]
        assert normalize_first_context(
            {
                "question_id": question_id,
                "question_text": question_text,
            }
        ) == {
            "question_id": question_id,
            "question_text": question_text,
        }


def test_runtime_guidance_does_not_assume_the_message_answers_the_question() -> None:
    guidance = build_first_context_runtime_guidance(
        {
            "interaction_kind": "first_context_story",
            "first_context": {
                "question_id": "recent_feeling",
                "question_text": "最近有哪件小事，让你心情有一点变化？",
            },
        }
    )

    assert "may or may not answer the question" in guidance
    assert "Choose exactly one response path" in guidance
    assert "- Refusal:" in guidance
    assert "- Question directed at Magi:" in guidance
    assert "- Unrelated message or topic change:" in guidance
    assert "- Meaningless or incomprehensible input:" in guidance
    assert "Only the Relevant answer path" in guidance
    assert "Do not redirect the user back" in guidance


def test_runtime_guidance_keeps_persona_reply_natural_without_overclaiming() -> None:
    guidance = build_first_context_runtime_guidance(
        {
            "interaction_kind": "first_context_story",
            "first_context": {
                "question_id": "preferred_name",
                "question_text": "希望 Magi 平时怎么称呼你？昵称就可以。",
            },
        }
    )

    assert "# First Conversation Reply Behavior" in guidance
    assert 'question_id is "preferred_name"' in guidance
    assert "it never asks for Magi's own name" in guidance
    assert "active persona's voice" in guidance
    assert "Do not merely paraphrase or summarize" in guidance
    assert "Do not infer stable personality traits" in guidance
    assert "do not add outside facts" in guidance
    assert "Do not introduce factual claims about named people" in guidance
    assert "# Decision Examples" in guidance
    assert 'Safe meaning: "It sounds like you genuinely like X."' in guidance
    assert 'Unsafe meaning: "X is a great album' in guidance
    assert "Do not describe the work's qualities" in guidance
    assert "claim how it makes Magi feel" in guidance
    assert "The product UI owns whether to offer another onboarding prompt" in guidance
    assert "Do not claim that a memory" in guidance
