"""Tests for temporal L3 evidence-pack and LLM service contracts."""

from __future__ import annotations

import pytest

from magi.memory.l3.models import TemporalEvidenceItem, TemporalEvidencePack
from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService


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


@pytest.mark.asyncio
async def test_build_temporal_evidence_pack_filters_runtime_and_preserves_importance() -> None:
    service = TemporalSummaryLLMService()

    pack = service.build_evidence_pack(
        events=[
            {
                "event_id": "evt-1",
                "event_type": "UserMessage",
                "raw_content": "I care more about growth than salary.",
                "memory_domain": "user_authored",
                "importance_score": 0.8,
                "timestamp": 100.0,
            },
            {
                "event_id": "evt-2",
                "event_type": "TimelineEvent",
                "raw_content": "Read several remote-work job posts.",
                "memory_domain": "external_activity",
                "importance_score": 0.6,
                "timestamp": 120.0,
            },
            {
                "event_id": "evt-3",
                "event_type": "TaskCompleted",
                "raw_content": "worker finished",
                "memory_domain": "runtime_telemetry",
                "importance_score": 0.2,
                "timestamp": 130.0,
            },
        ],
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
    )

    assert pack.source_event_ids == ["evt-1", "evt-2"]
    assert pack.source_event_count == 2
    assert pack.importance_aggregate == pytest.approx(0.7)
    assert pack.event_type_distribution == {"UserMessage": 1, "TimelineEvent": 1}
