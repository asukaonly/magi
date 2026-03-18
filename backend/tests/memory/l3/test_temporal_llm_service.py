"""Tests for temporal L3 evidence-pack and LLM service contracts."""

from __future__ import annotations

from magi.memory.l3.models import TemporalEvidenceItem, TemporalEvidencePack


def test_temporal_evidence_pack_keeps_window_and_event_ids() -> None:
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="finish portfolio"),
        ],
    )

    assert pack.summary_category == "day"
    assert pack.source_event_ids == ["evt-1", "evt-2"]
