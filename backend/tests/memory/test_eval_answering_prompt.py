"""Regression coverage for eval answer synthesis prompt rules."""

from __future__ import annotations

from magi.memory.eval_support.answer_synthesis import _build_eval_answer_system_prompt


def test_eval_answer_prompt_rejects_wrong_speaker_first_person_evidence() -> None:
    prompt = _build_eval_answer_system_prompt()

    assert "If the question asks about a named person" in prompt
    assert "first-person dialogue evidence from another speaker" in prompt
    assert "do not use it" in prompt
    assert "answer 'unknown'" in prompt
