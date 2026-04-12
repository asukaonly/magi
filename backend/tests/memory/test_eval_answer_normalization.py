from __future__ import annotations

from magi.memory.eval_support.answer_normalization import (
    normalize_eval_answer,
)


def test_normalize_eval_answer_passes_through_raw_answer():
    raw = "the bike\n\nBecause it appeared earlier in the evidence."
    assert normalize_eval_answer(raw) == raw


def test_normalize_eval_answer_returns_unknown_for_empty_text():
    assert normalize_eval_answer("") == "unknown"
