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


@pytest.mark.parametrize("question_id", ["recent_feeling", "preferred_name"])
def test_runtime_guidance_only_renders_registered_question_context(question_id):
    question_text = sorted(FIRST_CONTEXT_QUESTIONS[question_id])[0]
    first_context = {"question_id": question_id, "question_text": question_text}
    metadata = {"interaction_kind": "first_context_story", "first_context": first_context}
    guidance = build_first_context_runtime_guidance(metadata)
    assert f"- question_id: {question_id}" in guidance
    assert f"- question: {question_text}" in guidance
    for instruction in [
        "may or may not answer the question",
        "- Refusal:",
        "- Question directed at Magi:",
        "- Unrelated message or topic change:",
        "- Meaningless or incomprehensible input:",
        "Only the Relevant answer path",
        "Do not redirect the user back",
        "active persona's voice",
        "Do not infer stable personality traits",
        "Do not introduce factual claims about named people",
        "Do not claim that a memory",
    ]:
        assert instruction in guidance
    assert build_first_context_runtime_guidance({**metadata, "interaction_kind": "chat"}) == ""
    assert (
        build_first_context_runtime_guidance(
            {**metadata, "first_context": {**first_context, "question_text": "unregistered text"}}
        )
        == ""
    )
    assert build_first_context_runtime_guidance({}) == ""
