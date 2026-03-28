"""Tests for TimelineAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.sensor_output import ContentBlock, SensorOutput, SensorOutputMetadata
from magi.timeline.adapter import TimelineAdapter
from magi.timeline.contracts import TimelineEvent


def _make_output(**overrides) -> SensorOutput:
    defaults = dict(
        source_type="test_source",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        title="Test Title",
        summary="Test Summary",
        content_blocks=[ContentBlock(kind="text", value="content")],
        tags=["tag1"],
        entities=[{"name": "entity1"}],
        provenance={"sensor_id": "test"},
        domain_payload={"retention_mode": "retain_raw", "privacy_labels": ["pii"]},
    )
    defaults.update(overrides)
    return SensorOutput(**defaults)


class TestTimelineAdapter:
    @pytest.mark.asyncio
    async def test_on_sensor_output_calls_upsert(self):
        service = MagicMock()
        service.upsert_event = AsyncMock(return_value="evt_adapter_1")
        adapter = TimelineAdapter(service)

        output = _make_output()
        await adapter.on_sensor_output("evt_adapter_1", output)

        service.upsert_event.assert_awaited_once()
        event = service.upsert_event.call_args[0][0]
        assert isinstance(event, TimelineEvent)
        assert event.event_id == "evt_adapter_1"
        assert event.source_item_id == "item-1"
        assert event.title == "Test Title"

    def test_build_timeline_event_maps_fields(self):
        output = _make_output()
        metadata = SensorOutputMetadata(
            entities=[{"name": "extra"}],
            tags=["extra-tag"],
            relation_candidates=[{"predicate": "LIKES"}],
        )

        event = TimelineAdapter._build_timeline_event("evt_adapter_2", output, metadata)

        assert event.event_id == "evt_adapter_2"
        assert event.source_type == "test_source"
        assert event.source_item_id == "item-1"
        assert event.occurred_at == 1700000000.0
        assert event.captured_at == 1700000001.0
        assert event.title == "Test Title"
        assert event.summary == "Test Summary"
        assert event.retention_mode == "retain_raw"
        assert event.privacy_labels == ["pii"]
        assert len(event.content_blocks) == 1
        assert event.content_blocks[0].kind == "text"
        # Entities merged
        assert len(event.entities) == 2
        # Tags merged and deduplicated
        assert "tag1" in event.tags
        assert "extra-tag" in event.tags
        # Processing status
        assert event.processing_status["stored"] is True
        assert event.processing_status["analyzed"] is True

    def test_build_timeline_event_no_metadata(self):
        output = _make_output()
        event = TimelineAdapter._build_timeline_event("evt_adapter_3", output, None)
        assert event.event_id == "evt_adapter_3"
        assert event.source_item_id == "item-1"
        assert event.entities == [{"name": "entity1"}]
        assert event.tags == ["tag1"]
        assert event.processing_status["analyzed"] is False

    def test_build_timeline_event_default_retention(self):
        output = _make_output(domain_payload={})
        event = TimelineAdapter._build_timeline_event("x:1", output, None)
        assert event.retention_mode == "analyze_only"
