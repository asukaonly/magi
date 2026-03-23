"""Tests for state-change driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.models import StateChangePacket
from magi.memory.l3.state_change_service import StateChangeService


async def test_build_state_change_candidate_from_reconcile_outcomes() -> None:
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
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
                ),
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="mood",
                    winning_value="anxious",
                    status="corroborated",
                    confidence=0.8,
                    evidence_event_ids=["evt-2"],
                    time_span_hours=12.0,
                    stability_kind="emerging_pattern",
                    recommended_snapshot_field="core_traits",
                ),
            ],
        )
    )

    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "state_change"
    assert candidate.source_event_ids == ["evt-1", "evt-2"]
    assert "stress_level" in candidate.content
    assert "anxious" in candidate.content


async def test_build_state_change_candidate_returns_none_without_evidence() -> None:
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
                    entity_id="user:self",
                    entity_type="user",
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=[],
                    time_span_hours=6.0,
                    stability_kind="emerging_pattern",
                    recommended_snapshot_field="core_traits",
                )
            ],
        )
    )

    assert candidate is None
