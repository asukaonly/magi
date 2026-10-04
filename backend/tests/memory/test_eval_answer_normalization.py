from __future__ import annotations

import pytest

from magi.memory.eval_support.answer_normalization import (
    normalize_eval_answer,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "unknown"),
        ("  \n\t", "unknown"),
        ("  sushi  ", "sushi"),
        (
            "the bike\n\nBecause it appeared earlier in the evidence.",
            "the bike\n\nBecause it appeared earlier in the evidence.",
        ),
    ],
)
def test_answer_normalization_preserves_multiline_content(raw, expected):
    assert normalize_eval_answer(raw) == expected
