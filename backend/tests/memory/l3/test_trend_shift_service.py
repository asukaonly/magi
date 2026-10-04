"""Tests for trend-shift driven L3 insight candidates."""

from __future__ import annotations

import pytest

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


async def test_build_trend_shift_candidate_from_reconcile_outcomes(monkeypatch) -> None:
    monkeypatch.setattr("magi.memory.l3.trend_shift_service.wants_zh", lambda: True)
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    natural_summary="压力连续两天维持在高位",
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
    assert candidate.content == "压力连续两天维持在高位。"


@pytest.mark.parametrize(
    "hours,event_count,stability,accepted",
    [
        (23.99, 3, "stable_pattern", False),
        (24.0, 3, "stable_pattern", True),
        (24.0, 2, "stable_pattern", False),
        (48.0, 3, "volatile_pattern", False),
        (48.0, 3, "temporary_state", False),
        (48.0, 3, "stable_pattern", True),
    ],
)
async def test_trend_gate_independently_checks_duration_evidence_and_stability(
    hours, event_count, stability, accepted
):
    event_ids = [f"evt-{index}" for index in range(event_count)]
    candidate = await TrendShiftService().build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    time_span_hours=hours, evidence_event_ids=event_ids, stability_kind=stability
                )
            ],
        )
    )
    if accepted:
        assert candidate is not None
        assert candidate.source_event_ids == event_ids
        assert candidate.insight_metadata["outcomes"][0]["time_span_hours"] == hours
    else:
        assert candidate is None


@pytest.mark.parametrize(
    "first_trait,next_trait",
    [
        ("preference.music.genres", "preference.music.artists"),
        ("interest.example", "interest.other"),
    ],
)
async def test_trend_key_groups_related_traits_without_colliding_across_themes_or_entities(
    first_trait, next_trait
):
    service = TrendShiftService()
    first = _outcome(
        trait_name=first_trait,
        winning_value="jazz",
        trait_family="preference_profile",
        natural_summary="The user follows jazz.",
    )
    second = _outcome(
        trait_name=next_trait,
        winning_value="artist",
        trait_family="preference_profile",
        natural_summary="The user follows an artist.",
        evidence_event_ids=["evt-3", "evt-4", "evt-5"],
    )

    async def build(entity_id, outcomes):
        candidate = await service.build_candidate(
            TrendShiftPacket(entity_id=entity_id, entity_type="user", outcomes=outcomes)
        )
        assert candidate is not None
        return candidate

    original = await build("user:self", [first])
    expanded = await build("user:self", [first, second])
    different_theme = await build("user:self", [_outcome()])
    other_entity = await build(
        "user:other",
        [
            _outcome(
                entity_id="user:other",
                trait_name=first_trait,
                winning_value="jazz",
                trait_family="preference_profile",
                natural_summary="The user follows jazz.",
            )
        ],
    )
    assert original.insight_key == expanded.insight_key
    assert len({original.insight_key, different_theme.insight_key, other_entity.insight_key}) == 3
    assert expanded.source_event_ids == ["evt-1", "evt-2", "evt-3", "evt-4", "evt-5"]


@pytest.mark.parametrize("machine_text", [False, True])
async def test_trend_service_preserves_complete_wording_and_rejects_machine_text(
    monkeypatch, machine_text
) -> None:
    monkeypatch.setattr("magi.memory.l3.trend_shift_service.wants_zh", lambda: True)
    candidate = await TrendShiftService().build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                _outcome(
                    trait_name="interest.codex",
                    winning_value="Codex",
                    natural_summary=(
                        "Recurring interested_in signal for Codex"
                        if machine_text
                        else "用户持续关注Codex。"
                    ),
                    trait_family="preference_profile",
                ),
                _outcome(
                    trait_name="interest.deepseek",
                    winning_value="DeepSeek",
                    natural_summary=(
                        "Recurring interested_in signal for DeepSeek"
                        if machine_text
                        else "用户持续关注DeepSeek。"
                    ),
                    trait_family="preference_profile",
                ),
            ],
        )
    )
    if machine_text:
        assert candidate is None
    else:
        assert candidate is not None
        assert candidate.content == "用户持续关注Codex；用户持续关注DeepSeek。"
