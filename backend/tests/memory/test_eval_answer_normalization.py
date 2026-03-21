from __future__ import annotations

from magi.memory.eval_support.answer_normalization import (
    canonicalize_issue_component_answer,
    normalize_eval_answer,
)


def test_normalize_eval_answer_keeps_first_span_and_strips_article():
    normalized = normalize_eval_answer("the bike\n\nBecause it appeared earlier in the evidence.")

    assert normalized == "bike"


def test_normalize_eval_answer_returns_unknown_for_empty_text():
    assert normalize_eval_answer("") == "unknown"


def test_canonicalize_issue_component_answer_rewrites_component_only_answers():
    canonical = canonicalize_issue_component_answer(
        question="What was the first issue I had with my new car after its first service?",
        answer="GPS system",
        timeline_summary=[
            {
                "summary": (
                    "I recently had an issue with my car's GPS system on 3/22, "
                    "and I had to take it back to the dealership to get it fixed."
                )
            }
        ],
        hits=[],
    )

    assert canonical == "GPS system not functioning correctly"
