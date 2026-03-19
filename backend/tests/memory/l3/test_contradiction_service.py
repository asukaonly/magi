"""Tests for contradiction-driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l3.contradiction_service import ContradictionInsightService
from magi.memory.l3.models import ContradictionPacket


async def test_build_contradiction_candidate_from_outcomes() -> None:
    service = ContradictionInsightService()

    candidate = await service.build_candidate(
        ContradictionPacket(
            source_event_ids=["evt-1", "evt-2"],
            contradictions=[
                {
                    "trait_name": "stress_level",
                    "winning_value": "high",
                }
            ],
        )
    )

    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "conflict_resolution"
    assert candidate.source_event_ids == ["evt-1", "evt-2"]
    assert "stress_level" in candidate.content
    assert "conflicts around high" in candidate.content


async def test_build_contradiction_candidate_returns_none_without_contradictions() -> None:
    service = ContradictionInsightService()

    candidate = await service.build_candidate(
        ContradictionPacket(source_event_ids=["evt-1"], contradictions=[])
    )

    assert candidate is None
