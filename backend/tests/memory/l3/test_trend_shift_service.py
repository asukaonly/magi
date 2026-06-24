"""Tests for trend-shift driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.models import TrendShiftPacket
from magi.memory.l3.trend_shift_service import TrendShiftService


def _outcome(**overrides) -> ReconciledTraitOutcome:
    """Build a ReconciledTraitOutcome with sensible defaults for trend-shift tests."""
    defaults = dict(
        entity_id="user:self",
        entity_type="user",
        trait_name="stress_level",
        winning_value="high",
        status="stable",
        confidence=0.92,
        evidence_event_ids=["evt-1", "evt-2", "evt-3"],
        time_span_hours=48.0,
        stability_kind="stable_pattern",
        recommended_snapshot_field="core_traits",
        natural_summary="",
        expires_at=None,
        trait_family="stress",
    )
    defaults.update(overrides)
    return ReconciledTraitOutcome(**defaults)


async def test_build_trend_shift_candidate_from_reconcile_outcomes() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    time_span_hours=48.0,
                    stability_kind="stable_pattern",
                    trait_family="stress",
                ),
            ],
        )
    )

    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "trend_shift"
    assert candidate.insight_key is not None
    assert candidate.review_state == "pending_confirmation"
    assert candidate.insight_metadata["policy"] == "trend_shift_gate_v4"
    assert candidate.source_event_ids == ["evt-1", "evt-2", "evt-3"]
    # Trait family label should appear, not raw trait_name
    assert "stress_level" not in candidate.content
    assert "stress" in candidate.content or "压力" in candidate.content


async def test_build_trend_shift_candidate_with_natural_summary() -> None:
    """When natural_summary is present, tier-1 rendering is used."""
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    natural_summary="压力连续两天维持在高位",
                    trait_family="stress",
                ),
            ],
        )
    )

    assert candidate is not None
    assert "压力连续两天维持在高位" in candidate.content
    assert "stress_level" not in candidate.content


async def test_build_trend_shift_candidate_returns_none_without_long_span_signal() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="stress_level",
                    winning_value="high",
                    status="corroborated",
                    confidence=0.75,
                    evidence_event_ids=["evt-1"],
                    time_span_hours=2.0,
                    stability_kind="temporary_state",
                    trait_family="stress",
                )
            ],
        )
    )

    assert candidate is None


async def test_build_trend_shift_candidate_returns_none_for_volatile_sparse_signal() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="music_interests",
                    winning_value="j-rock",
                    status="corroborated",
                    confidence=0.58,
                    evidence_event_ids=["evt-1", "evt-2"],
                    time_span_hours=118.0,
                    stability_kind="volatile_pattern",
                    trait_family="preference_profile",
                )
            ],
        )
    )

    assert candidate is None


async def test_trend_shift_insight_key_groups_related_music_traits() -> None:
    service = TrendShiftService()

    genres_only = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop"]',
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    trait_family="preference_profile",
                )
            ],
        )
    )
    genres_and_artists = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop"]',
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    trait_family="preference_profile",
                ),
                _outcome(
                    trait_name="preference.music.artists",
                    winning_value='["Caro"]',
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-4", "evt-5", "evt-6"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    trait_family="preference_profile",
                ),
            ],
        )
    )

    assert genres_only is not None
    assert genres_and_artists is not None
    assert genres_only.insight_key == genres_and_artists.insight_key


async def test_trend_shift_interest_outcomes_use_stable_theme_key() -> None:
    service = TrendShiftService()

    codex_and_deepseek = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="interest.codex-coding-tools-by-openai",
                    winning_value="Codex",
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    natural_summary="Recurring interested_in signal for Codex",
                    trait_family="preference_profile",
                ),
                _outcome(
                    trait_name="interest.deepseek",
                    winning_value="DeepSeek",
                    evidence_event_ids=["evt-4", "evt-5", "evt-6"],
                    natural_summary="Recurring interested_in signal for DeepSeek",
                    trait_family="preference_profile",
                ),
            ],
        )
    )
    expanded_interest_set = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="interest.codex-coding-tools-by-openai",
                    winning_value="Codex",
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    natural_summary="Recurring interested_in signal for Codex",
                    trait_family="preference_profile",
                ),
                _outcome(
                    trait_name="interest.deepseek",
                    winning_value="DeepSeek",
                    evidence_event_ids=["evt-4", "evt-5", "evt-6"],
                    natural_summary="Recurring interested_in signal for DeepSeek",
                    trait_family="preference_profile",
                ),
                _outcome(
                    trait_name="interest.glm-5-2",
                    winning_value="GLM-5.2",
                    evidence_event_ids=["evt-7", "evt-8", "evt-9"],
                    natural_summary="Recurring interested_in signal for GLM-5.2",
                    trait_family="preference_profile",
                ),
            ],
        )
    )

    assert codex_and_deepseek is not None
    assert expanded_interest_set is not None
    assert codex_and_deepseek.insight_key == expanded_interest_set.insight_key


async def test_trend_shift_interest_content_does_not_expose_rule_template(monkeypatch) -> None:
    monkeypatch.setattr("magi.memory.l3.trend_shift_service.wants_zh", lambda: True)
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="interest.codex-coding-tools-by-openai",
                    winning_value="Codex",
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    natural_summary="Recurring interested_in signal for Codex",
                    trait_family="preference_profile",
                ),
                _outcome(
                    trait_name="interest.deepseek",
                    winning_value="DeepSeek",
                    evidence_event_ids=["evt-4", "evt-5", "evt-6"],
                    natural_summary="Recurring interested_in signal for DeepSeek",
                    trait_family="preference_profile",
                ),
            ],
        )
    )

    assert candidate is not None
    assert "Recurring" not in candidate.content
    assert "interested_in" not in candidate.content
    assert "Codex" in candidate.content
    assert "DeepSeek" in candidate.content
    assert "持续关注" in candidate.content
