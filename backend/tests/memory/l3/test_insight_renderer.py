"""L3 consumes complete host descriptions without inventing missing facts."""

from __future__ import annotations

import pytest

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.insight_renderer import render_insight_content


def _outcome(**overrides) -> ReconciledTraitOutcome:
    defaults = dict(
        entity_id="user:u1", entity_type="user", trait_name="state.sleep_quality",
        winning_value="poor", status="corroborated", confidence=0.7,
        evidence_event_ids=["evt-1"], time_span_hours=2.0, stability_kind="state_pattern",
        recommended_snapshot_field="sleep", fact_completeness="complete",
        natural_summary="用户报告睡眠质量不佳。", expires_at=None, trait_family="state_profile",
    )
    defaults.update(overrides)
    return ReconciledTraitOutcome(**defaults)


@pytest.mark.parametrize(
    ("zh", "sentences", "expected"),
    [
        (
            True,
            ["用户不喜欢苹果。 原文时间: 上周", "用户报告睡眠质量不佳。"],
            "用户不喜欢苹果。 原文时间: 上周；用户报告睡眠质量不佳。",
        ),
        (
            False,
            ["The user dislikes Apple. Last week", "The user reports poor sleep."],
            "The user dislikes Apple. Last week; The user reports poor sleep.",
        ),
    ],
)
def test_complete_host_sentences_preserve_negation_time_and_locale_joining(zh, sentences, expected):
    assert (
        render_insight_content(
            insight_kind="state_change",
            user_lang_zh=zh,
            outcomes=[_outcome(natural_summary=text) for text in sentences],
        )
        == expected
    )


@pytest.mark.parametrize("completeness", [None, "partial", "unavailable"])
def test_insight_requires_nonempty_complete_outcomes(completeness):
    outcomes = (
        []
        if completeness is None
        else [
            _outcome(
                fact_completeness=completeness,
                natural_summary="用户喜欢尚未解析的对象。",
                trait_family="preference_profile",
                winning_value="like",
            )
        ]
    )
    assert (
        render_insight_content(insight_kind="state_change", user_lang_zh=True, outcomes=outcomes)
        is None
    )


def test_empty_complete_text_is_not_enough_for_an_insight():
    assert render_insight_content(
        insight_kind="state_change", user_lang_zh=True,
        outcomes=[_outcome(), _outcome(natural_summary="")],
    ) is None


def test_machine_signal_text_is_skipped_without_regenerating_a_family_sentence():
    assert render_insight_content(
        insight_kind="trend_shift", user_lang_zh=True,
        outcomes=[_outcome(natural_summary="Recurring interested_in signal for RAG")],
    ) is None
