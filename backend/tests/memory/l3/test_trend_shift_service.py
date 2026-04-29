"""Tests for trend-shift driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.models import TrendShiftPacket
from magi.memory.l3.trend_shift_service import TrendShiftService


async def test_build_trend_shift_candidate_from_reconcile_outcomes() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
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
                )
            ],
        )
    )

    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "trend_shift"
    assert candidate.insight_key is not None
    assert candidate.review_state == "pending_confirmation"
    assert candidate.insight_metadata["policy"] == "trend_shift_gate_v3"
    assert candidate.source_event_ids == ["evt-1", "evt-2", "evt-3"]
    assert "stress" in candidate.content
    assert "48.0" in candidate.content


async def test_build_trend_shift_candidate_returns_none_without_long_span_signal() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="stress_level",
                    winning_value="high",
                    status="corroborated",
                    confidence=0.75,
                    evidence_event_ids=["evt-1"],
                    time_span_hours=2.0,
                    stability_kind="temporary_state",
                    recommended_snapshot_field="core_traits",
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
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="music_interests",
                    winning_value="j-rock",
                    status="corroborated",
                    confidence=0.58,
                    evidence_event_ids=["evt-1", "evt-2"],
                    time_span_hours=118.0,
                    stability_kind="volatile_pattern",
                    recommended_snapshot_field="core_traits",
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
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop"]',
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    recommended_snapshot_field="preferences",
                )
            ],
        )
    )
    genres_and_artists = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop"]',
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-1", "evt-2", "evt-3"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    recommended_snapshot_field="preferences",
                ),
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="preference.music.artists",
                    winning_value='["Caro"]',
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-4", "evt-5", "evt-6"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    recommended_snapshot_field="preferences",
                ),
            ],
        )
    )

    assert genres_only is not None
    assert genres_and_artists is not None
    assert genres_only.insight_key == genres_and_artists.insight_key
