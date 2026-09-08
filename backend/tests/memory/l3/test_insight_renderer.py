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


def test_complete_host_sentences_keep_negation_and_source_time():
    content = render_insight_content(
        insight_kind="state_change", user_lang_zh=True,
        outcomes=[_outcome(natural_summary="用户不喜欢苹果。 原文时间: 上周"),
                  _outcome(natural_summary="用户报告睡眠质量不佳。")],
    )
    assert content == "用户不喜欢苹果。 原文时间: 上周；用户报告睡眠质量不佳。"
    assert "state.sleep_quality" not in content


@pytest.mark.parametrize("completeness", ["partial", "unavailable"])
@pytest.mark.parametrize("kind", ["state_change", "trend_shift", "conflict_resolution"])
def test_incomplete_host_description_never_uses_family_or_storage_value(completeness, kind):
    assert render_insight_content(
        insight_kind=kind, user_lang_zh=True,
        outcomes=[_outcome(fact_completeness=completeness, natural_summary="用户喜欢尚未解析的对象。",
                           trait_family="preference_profile", winning_value="like")],
    ) is None


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


@pytest.mark.parametrize("kind", ["state_change", "trend_shift", "conflict_resolution"])
def test_complete_host_wording_is_preserved_for_every_insight_kind(kind):
    assert render_insight_content(
        insight_kind=kind, user_lang_zh=False,
        outcomes=[_outcome(natural_summary="The user dislikes Apple.")],
    ) == "The user dislikes Apple."


def test_empty_outcomes_returns_none():
    assert render_insight_content(
        insight_kind="state_change", outcomes=[], user_lang_zh=True,
    ) is None


def test_fact_completeness_is_required_in_reconcile_contract():
    values = _outcome().to_dict()
    values.pop("fact_completeness")
    with pytest.raises(TypeError, match="fact_completeness"):
        ReconciledTraitOutcome(**values)
