"""Tests for TimelineAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import (
    ActivityFacet,
    ContentBlock,
    SensorActivity,
    SensorNarration,
    SensorOutput,
    SensorOutputMetadata,
)
from magi.awareness.sensor_projection import build_sensor_projection
from magi.timeline.sensor_projection import build_sensor_timeline_event
from magi.timeline.adapter import TimelineAdapter
from magi.timeline.contracts import TimelineEvent


class _TimelineTestSensor(SensorBase):
    sensor_id = "test.timeline"
    source_type = "test_source"

    async def build_output(self, item):  # pragma: no cover - test helper only
        raise NotImplementedError


def _make_output(**overrides) -> SensorOutput:
    defaults = dict(
        source_type="test_source",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        activity=SensorActivity(
            source=ActivityFacet(
                code="test_source",
                i18n_key="activity.source.test_source",
                fallback="Test Source",
            ),
            action=ActivityFacet(
                code="observe",
                i18n_key="activity.action.observe",
                fallback="Observed",
            ),
        ),
        narration=SensorNarration(body="Test Summary", title="Test Title"),
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
    async def test_on_timeline_event_calls_upsert(self):
        service = MagicMock()
        service.upsert_event = AsyncMock(return_value="evt_adapter_1")
        adapter = TimelineAdapter(service)
        sensor = _TimelineTestSensor()

        output = _make_output()
        projection = build_sensor_projection(sensor, output)
        event = build_sensor_timeline_event("evt_adapter_1", output, projection)
        await adapter.on_timeline_event(event)

        service.upsert_event.assert_awaited_once()
        event = service.upsert_event.call_args[0][0]
        assert isinstance(event, TimelineEvent)
        assert event.event_id == "evt_adapter_1"
        assert event.source_item_id == "item-1"
        assert event.title == "Test Source Observed · Test Title"

    def test_build_timeline_event_maps_fields(self):
        sensor = _TimelineTestSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(
            entities=[{"name": "extra"}],
            tags=["extra-tag"],
            relation_candidates=[{"predicate": "LIKES"}],
        )

        projection = build_sensor_projection(sensor, output)
        event = build_sensor_timeline_event("evt_adapter_2", output, projection, metadata)

        assert event.event_id == "evt_adapter_2"
        assert event.source_type == "test_source"
        assert event.source_item_id == "item-1"
        assert event.occurred_at == 1700000000.0
        assert event.captured_at == 1700000001.0
        assert event.title == "Test Source Observed · Test Title"
        assert event.summary == "Test Source Observed Test Summary"
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
        sensor = _TimelineTestSensor()
        output = _make_output()
        projection = build_sensor_projection(sensor, output)
        event = build_sensor_timeline_event("evt_adapter_3", output, projection, None)
        assert event.event_id == "evt_adapter_3"
        assert event.source_item_id == "item-1"
        assert event.entities == [{"name": "entity1"}]
        assert event.tags == ["tag1"]
        assert event.processing_status["analyzed"] is False

    def test_build_timeline_event_default_retention(self):
        sensor = _TimelineTestSensor()
        output = _make_output(domain_payload={})
        projection = build_sensor_projection(sensor, output)
        event = build_sensor_timeline_event("x:1", output, projection, None)
        assert event.retention_mode == "analyze_only"
