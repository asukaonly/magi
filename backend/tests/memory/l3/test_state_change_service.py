"""Tests for state-change driven L3 insight candidates."""

from __future__ import annotations

import pytest

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
        fact_completeness="complete",
        natural_summary="用户的压力水平是高。",
        expires_at=None,
        trait_family="stress",
    )
    defaults.update(overrides)
    if "natural_summary" not in overrides:
        value = str(defaults["winning_value"])
        if str(defaults["trait_name"]).startswith("interest."):
            defaults["natural_summary"] = f"用户关注{value}。"
        elif defaults["trait_family"] == "preference_profile":
            defaults["natural_summary"] = f"用户偏好的音乐是{value}。"
        elif defaults["trait_family"] == "mood":
            defaults["natural_summary"] = f"用户感到{value}。"
        else:
            defaults["natural_summary"] = f"用户的压力水平是{value}。"
    return ReconciledTraitOutcome(**defaults)


async def test_build_state_change_candidate_from_reconcile_outcomes(monkeypatch) -> None:
    monkeypatch.setattr("magi.memory.l3.state_change_service.wants_zh", lambda: True)
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    natural_summary="压力偏高，持续超过两天",
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    evidence_event_ids=["evt-1", "evt-2"],
                    trait_family="stress",
                ),
                _outcome(
                    natural_summary="情绪偏向焦虑",
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
    assert candidate.content == "压力偏高，持续超过两天；情绪偏向焦虑。"


@pytest.mark.parametrize("evidence_ids", [[], ["evt-1"]])
async def test_long_stable_state_still_requires_at_least_one_source_event(evidence_ids):
    candidate = await StateChangeService().build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    evidence_event_ids=evidence_ids,
                    time_span_hours=48,
                    stability_kind="stable_pattern",
                )
            ],
        )
    )
    if evidence_ids:
        assert candidate is not None
        assert candidate.source_event_ids == evidence_ids
    else:
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
                    trait_family="preference_profile",
                )
            ],
        )
    )

    assert candidate is None


@pytest.mark.parametrize("change", ["value", "related_trait"])
async def test_state_key_survives_related_changes_without_theme_or_entity_collisions(change):
    service = StateChangeService()
    first = _outcome(
        trait_name="preference.music.genres",
        winning_value='["jazz"]',
        trait_family="preference_profile",
    )
    changed = _outcome(
        trait_name="preference.music.genres" if change == "value" else "preference.music.artists",
        winning_value='["indie rock"]',
        trait_family="preference_profile",
        evidence_event_ids=["evt-3", "evt-4"],
    )

    async def build(entity_id, outcomes):
        candidate = await service.build_candidate(
            StateChangePacket(entity_id=entity_id, entity_type="user", outcomes=outcomes)
        )
        assert candidate is not None
        return candidate

    original = await build("user:self", [first])
    updated = await build("user:self", [changed] if change == "value" else [first, changed])
    other_theme = await build("user:self", [_outcome()])
    other_entity = await build(
        "user:other",
        [
            _outcome(
                entity_id="user:other",
                trait_name=first.trait_name,
                winning_value=first.winning_value,
                trait_family="preference_profile",
            )
        ],
    )
    assert original.insight_key == updated.insight_key
    assert len({original.insight_key, other_theme.insight_key, other_entity.insight_key}) == 3
    assert updated.source_event_ids == (
        ["evt-3", "evt-4"] if change == "value" else ["evt-1", "evt-2", "evt-3", "evt-4"]
    )
    metadata = updated.insight_metadata["outcomes"]
    assert [row["trait_name"] for row in metadata] == (
        [changed.trait_name] if change == "value" else [first.trait_name, changed.trait_name]
    )
    assert metadata[-1]["winning_value"] == ["indie rock"]
