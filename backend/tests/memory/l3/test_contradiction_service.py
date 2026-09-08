"""Tests for contradiction-driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.contradiction_service import ContradictionInsightService
from magi.memory.l3.models import ContradictionPacket


def _outcome(**overrides) -> ReconciledTraitOutcome:
    defaults = dict(
        entity_id="user:u1",
        entity_type="user",
        trait_name="stress_level",
        winning_value="high",
        status="contradicted",
        confidence=0.7,
        evidence_event_ids=["evt-1"],
        time_span_hours=2.0,
        stability_kind="state_pattern",
        recommended_snapshot_field="stress",
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


async def test_uses_natural_summary_when_available() -> None:
    service = ContradictionInsightService()
    candidate = await service.build_candidate(
        ContradictionPacket(
            source_event_ids=["evt-1", "evt-2"],
            outcomes=[
                _outcome(
                    natural_summary="用户在压力评估上前后矛盾",
                ),
            ],
        )
    )
    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "conflict_resolution"
    assert candidate.source_event_ids == ["evt-1", "evt-2"]
    assert "前后矛盾" in candidate.content
    # CRITICAL: raw trait_name must never appear in content
    assert "stress_level" not in candidate.content
    assert "state.sleep_quality" not in candidate.content


async def test_skips_missing_fact_description_even_when_family_is_known() -> None:
    service = ContradictionInsightService()
    candidate = await service.build_candidate(
        ContradictionPacket(
            source_event_ids=["evt-1"],
            outcomes=[_outcome(natural_summary="", trait_family="stress")],
        )
    )
    assert candidate is None


async def test_returns_none_when_no_clean_rendering_possible() -> None:
    """When natural_summary is empty AND trait_family is unknown,
    refuse to generate the insight (don't leak raw trait_name)."""
    service = ContradictionInsightService()
    candidate = await service.build_candidate(
        ContradictionPacket(
            source_event_ids=["evt-1"],
            outcomes=[_outcome(
                natural_summary="",
                trait_family="",  # unknown family
                trait_name="some.unknown.path",
            )],
        )
    )
    # Renderer returns None → service returns None
    assert candidate is None


async def test_returns_none_without_outcomes() -> None:
    service = ContradictionInsightService()
    candidate = await service.build_candidate(
        ContradictionPacket(source_event_ids=["evt-1"], outcomes=[])
    )
    assert candidate is None
