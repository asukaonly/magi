"""Tests for trend-shift driven L3 insight candidates."""

from __future__ import annotations

from magi.memory.l3.models import TrendShiftPacket
from magi.memory.l3.trend_shift_service import TrendShiftService


async def test_build_trend_shift_candidate_from_reconcile_outcomes() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                {
                    "trait_name": "stress_level",
                    "winning_value": "high",
                    "status": "stable",
                    "time_span_hours": 48.0,
                    "stability_kind": "temporary_state",
                    "evidence_event_ids": ["evt-1", "evt-2", "evt-3"],
                }
            ],
        )
    )

    assert candidate is not None
    assert candidate.summary_type == "insight"
    assert candidate.summary_category == "trend_shift"
    assert candidate.source_event_ids == ["evt-1", "evt-2", "evt-3"]
    assert "stress_level" in candidate.content
    assert "48.0 hours" in candidate.content


async def test_build_trend_shift_candidate_returns_none_without_long_span_signal() -> None:
    service = TrendShiftService()

    candidate = await service.build_candidate(
        TrendShiftPacket(
            entity_id="user:self",
            entity_type="user",
            outcomes=[
                {
                    "trait_name": "stress_level",
                    "winning_value": "high",
                    "status": "corroborated",
                    "time_span_hours": 2.0,
                    "stability_kind": "temporary_state",
                    "evidence_event_ids": ["evt-1"],
                }
            ],
        )
    )

    assert candidate is None
