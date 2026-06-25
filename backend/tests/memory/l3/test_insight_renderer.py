"""Tests for the shared 3-tier insight renderer."""

from __future__ import annotations

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.insight_renderer import render_insight_content


def _outcome(**overrides) -> ReconciledTraitOutcome:
    defaults = dict(
        entity_id="user:u1",
        entity_type="user",
        trait_name="state.sleep_quality",
        winning_value="poor",
        status="corroborated",
        confidence=0.7,
        evidence_event_ids=["evt-1"],
        time_span_hours=2.0,
        stability_kind="state_pattern",
        recommended_snapshot_field="sleep",
        natural_summary="",
        expires_at=None,
        trait_family="state_profile",
    )
    defaults.update(overrides)
    return ReconciledTraitOutcome(**defaults)


# ─── Tier 1: natural_summary ─────────────────────────────────────────

def test_tier1_natural_summary_used_when_present():
    """All outcomes have natural_summary → join them."""
    content = render_insight_content(
        insight_kind="state_change",
        outcomes=[
            _outcome(natural_summary="用户报告睡眠差因为蚊子"),
            _outcome(natural_summary="用户当前情绪是困倦"),
        ],
        user_lang_zh=True,
    )
    assert content is not None
    assert "用户报告睡眠差因为蚊子" in content
    assert "用户当前情绪是困倦" in content
    # No raw trait_name
    assert "state.sleep_quality" not in content


def test_tier1_partial_natural_summary_falls_through():
    """If only SOME outcomes have natural_summary, tier 1 doesn't apply."""
    content = render_insight_content(
        insight_kind="state_change",
        outcomes=[
            _outcome(natural_summary="有一句"),
            _outcome(natural_summary=""),  # missing
        ],
        user_lang_zh=True,
    )
    # Falls to tier 2 (both have trait_family=state_profile → rendered)
    assert content is not None
    assert "state.sleep_quality" not in content


def test_machine_signal_natural_summary_falls_through_to_readable_renderer():
    content = render_insight_content(
        insight_kind="trend_shift",
        outcomes=[
            _outcome(
                trait_name="interest.software",
                trait_family="interest_profile",
                winning_value="RAG",
                natural_summary="Recurring interested_in signal for RAG",
            ),
        ],
        user_lang_zh=True,
    )

    assert content is not None
    assert "Recurring" not in content
    assert "interested_in" not in content
    assert "RAG" in content


# ─── Tier 2: trait_family ─────────────────────────────────────────────

def test_tier2_trait_family_used_when_natural_summary_missing():
    """All outcomes have trait_family → renderer uses family label."""
    content = render_insight_content(
        insight_kind="state_change",
        outcomes=[
            _outcome(natural_summary="", trait_family="state_profile", winning_value="差"),
        ],
        user_lang_zh=True,
    )
    assert content is not None
    assert "状态" in content  # _TRAIT_FAMILY_LABELS_ZH["state_profile"]
    assert "差" in content
    # CRITICAL invariant: no raw trait_name
    assert "state.sleep_quality" not in content
    assert "state_profile" not in content


def test_tier2_works_for_all_three_insight_kinds():
    base = _outcome(natural_summary="", trait_family="mood", winning_value="开心")
    state_content = render_insight_content(
        insight_kind="state_change", outcomes=[base], user_lang_zh=True,
    )
    trend_content = render_insight_content(
        insight_kind="trend_shift", outcomes=[base], user_lang_zh=True,
    )
    conflict_content = render_insight_content(
        insight_kind="conflict_resolution", outcomes=[base], user_lang_zh=True,
    )
    for content in (state_content, trend_content, conflict_content):
        assert content is not None
        assert "情绪" in content
        assert "mood" not in content  # raw family name not leaked


# ─── Tier 3: skip ─────────────────────────────────────────────────────

def test_tier3_returns_none_when_no_natural_summary_and_unknown_family():
    """Both fallbacks fail → return None rather than leak trait_name."""
    content = render_insight_content(
        insight_kind="state_change",
        outcomes=[
            _outcome(
                natural_summary="",
                trait_family="",  # empty — unknown
                trait_name="some.totally.unknown.trait",
                winning_value="x",
            ),
        ],
        user_lang_zh=True,
    )
    assert content is None


def test_tier3_returns_none_when_family_known_but_value_empty():
    """If value can't be rendered, also skip."""
    content = render_insight_content(
        insight_kind="state_change",
        outcomes=[_outcome(natural_summary="", trait_family="mood", winning_value="")],
        user_lang_zh=True,
    )
    assert content is None


def test_empty_outcomes_returns_none():
    assert render_insight_content(
        insight_kind="state_change",
        outcomes=[],
        user_lang_zh=True,
    ) is None
