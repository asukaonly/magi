"""Tests for the controlled first-context question contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi.events.first_context import (
    FIRST_CONTEXT_QUESTIONS,
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
