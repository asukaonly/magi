"""Tests for state-change driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l3.models import StateChangePacket
from magi.memory.l3.state_change_service import StateChangeService


async def test_build_state_change_candidate_from_reconcile_outcomes() -> None:
    service = StateChangeService()

    candidate = await service.build_candidate(
        StateChangePacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                {
                    "trait_name": "stress_level",
                    "winning_value": "high",
                    "status": "stable",
                    "evidence_event_ids": ["evt-1", "evt-2"],
                },
                {
                    "trait_name": "mood",
                    "winning_value": "anxious",
                    "status": "corroborated",
                    "evidence_event_ids": ["evt-2"],
                },
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
                {
                    "trait_name": "stress_level",
                    "winning_value": "high",
                    "status": "stable",
                    "evidence_event_ids": [],
                }
            ],
        )
    )

    assert candidate is None
