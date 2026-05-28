"""Tests for state-change driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.models import StateChangePacket
from magi.memory.l3.state_change_service import StateChangeService


def _outcome(**overrides) -> ReconciledTraitOutcome:
    """Build a ReconciledTraitOutcome with sensible defaults for state-change tests."""
    defaults = dict(
        entity_id="user:self",
        entity_type="user",
        trait_name="stress_level",
        winning_value="high",
        status="stable",
        confidence=0.9,
        evidence_event_ids=["evt-1", "evt-2"],
        time_span_hours=48.0,
        stability_kind="stable_pattern",
        recommended_snapshot_field="core_traits",
        natural_summary="",
        expires_at=None,
        trait_family="stress",
    )
    defaults.update(overrides)
    return ReconciledTraitOutcome(**defaults)


async def test_build_state_change_candidate_from_reconcile_outcomes() -> None:
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    evidence_event_ids=["evt-1", "evt-2"],
                    trait_family="stress",
                ),
                _outcome(
                    trait_name="mood",
                    winning_value="anxious",
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="mood",
                ),
            ],
        )
    )

    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "state_change"
    assert candidate.insight_key is not None
    assert candidate.review_state == "pending_confirmation"
    assert candidate.insight_metadata["policy"] == "state_change_gate_v3"
    assert candidate.source_event_ids == ["evt-1", "evt-2"]
    # Trait families should appear, raw trait_name should not
    assert "stress_level" not in candidate.content
    assert "stress" in candidate.content or "压力" in candidate.content


async def test_build_state_change_candidate_with_natural_summary() -> None:
    """When natural_summary is present, tier-1 rendering is used."""
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    evidence_event_ids=["evt-1", "evt-2"],
                    natural_summary="压力偏高，持续超过两天",
                    trait_family="stress",
                ),
                _outcome(
                    trait_name="mood",
                    winning_value="anxious",
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    natural_summary="情绪偏向焦虑",
                    trait_family="mood",
                ),
            ],
        )
    )

    assert candidate is not None
    assert "压力偏高" in candidate.content
    assert "情绪偏向焦虑" in candidate.content
    assert "stress_level" not in candidate.content


async def test_build_state_change_candidate_returns_none_without_evidence() -> None:
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    evidence_event_ids=[],
                    time_span_hours=6.0,
                    stability_kind="emerging_pattern",
                )
            ],
        )
    )

    assert candidate is None


async def test_build_state_change_candidate_ignores_weak_emerging_signal() -> None:
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="music.artists",
                    winning_value='["Lana Del Rey"]',
                    status="tentative",
                    confidence=0.4,
                    evidence_event_ids=["evt-1"],
                    time_span_hours=1.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                )
            ],
        )
    )

    assert candidate is None


async def test_state_change_insight_key_is_stable_for_trait_value_updates() -> None:
    service = StateChangeService()

    first = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="music.artists",
                    winning_value='["Lana Del Rey", "Olivia Rodrigo"]',
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-1", "evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                )
            ],
        )
    )
    second = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="music.artists",
                    winning_value='["indie rock"]',
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-3", "evt-4"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                )
            ],
        )
    )

    assert first is not None
    assert second is not None
    assert first.insight_key == second.insight_key


async def test_state_change_insight_key_groups_related_music_traits() -> None:
    service = StateChangeService()

    genres_only = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop"]',
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-1", "evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                )
            ],
        )
    )
    genres_and_artists = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop", "game_sounds"]',
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-1", "evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                ),
                _outcome(
                    trait_name="preference.music.artists",
                    winning_value='["Caro", "Caro"]',
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-3", "evt-4"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                ),
            ],
        )
    )

    assert genres_only is not None
    assert genres_and_artists is not None
    assert genres_only.insight_key == genres_and_artists.insight_key


async def test_state_change_content_uses_readable_labels_not_raw_trait_name(monkeypatch) -> None:
    """Renderer must never leak raw trait_name identifiers to user-facing content."""
    monkeypatch.setattr("magi.memory.l3.state_change_service.wants_zh", lambda: True)
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="preference.music.genres",
                    winning_value='["game_sounds", "japanese_pop", "game_sounds"]',
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-1", "evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    trait_family="taste_profile",
                )
            ],
        )
    )

    assert candidate is not None
    assert "preference.music.genres" not in candidate.content
    # Family label "审美" should appear (taste_profile)
    assert "审美" in candidate.content
