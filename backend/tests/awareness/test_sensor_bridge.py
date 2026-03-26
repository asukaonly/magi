"""Tests for TimelineSensorBase backward-compatibility bridge."""

from __future__ import annotations

import time
from typing import Any

import pytest

from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import ContentBlock, SensorOutput, SensorOutputMetadata
from magi.timeline.contracts import TimelineContentBlock, TimelineEvent
from magi.timeline.sensors.base import TimelineSensorBase


class _LegacySensor(TimelineSensorBase):
    """Simulates an existing sensor plugin that uses the legacy API."""

    sensor_id = "legacy.test"
    source_type = "legacy_source"
    supports_pull_sync = True
    update_key_fields = ("id",)

    async def build_timeline_event(self, item: dict[str, Any]) -> TimelineEvent:
        return self._build_event(
            source_item_id=str(item["id"]),
            title=str(item.get("title", "Legacy Title")),
            summary=str(item.get("summary", "Legacy Summary")),
            occurred_at=item.get("occurred_at"),
            content_blocks=[TimelineContentBlock(kind="text", value="legacy content")],
            tags=["legacy-tag"],
            provenance={"sensor_id": self.sensor_id, "custom": True},
        )

    async def extract_candidates(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "entities": [{"name": "test_entity"}],
            "tags": ["extracted-tag"],
            "relation_candidates": [
                {"predicate": "LIKES", "object_id": "topic:test"},
            ],
        }


class TestTimelineSensorBaseIsaSensorBase:
    def test_isinstance(self):
        sensor = _LegacySensor()
        assert isinstance(sensor, SensorBase)
        assert isinstance(sensor, TimelineSensorBase)

    def test_has_memory_policy(self):
        sensor = _LegacySensor()
        assert sensor.memory_policy is not None
        assert sensor.memory_policy.memory_domain == "external_activity"


class TestTimelineSensorBaseBridge:
    @pytest.mark.asyncio
    async def test_build_output_delegates_to_build_timeline_event(self):
        sensor = _LegacySensor()
        item = {"id": "item-1", "title": "My Title", "summary": "My Summary", "occurred_at": 1700000000.0}

        output = await sensor.build_output(item)

        assert isinstance(output, SensorOutput)
        assert output.source_type == "legacy_source"
        assert output.source_item_id == "item-1"
        assert output.title == "My Title"
        assert output.summary == "My Summary"
        assert output.occurred_at == 1700000000.0
        assert len(output.content_blocks) == 1
        assert output.content_blocks[0].kind == "text"
        assert output.content_blocks[0].value == "legacy content"
        assert "legacy-tag" in output.tags
        assert output.provenance["custom"] is True
        # Domain payload should carry legacy fields
        assert output.domain_payload["retention_mode"] == "analyze_only"

    @pytest.mark.asyncio
    async def test_extract_metadata_delegates_to_extract_candidates(self):
        sensor = _LegacySensor()
        item = {"id": "item-1"}

        metadata = await sensor.extract_metadata(item)

        assert isinstance(metadata, SensorOutputMetadata)
        assert len(metadata.entities) == 1
        assert metadata.entities[0]["name"] == "test_entity"
        assert "extracted-tag" in metadata.tags
        assert len(metadata.relation_candidates) == 1
        assert metadata.relation_candidates[0]["predicate"] == "LIKES"

    @pytest.mark.asyncio
    async def test_legacy_build_event_still_works(self):
        sensor = _LegacySensor()
        item = {"id": "item-2", "title": "Direct", "summary": "Direct"}

        event = await sensor.build_timeline_event(item)

        assert isinstance(event, TimelineEvent)
        assert event.event_id == "legacy_source:item-2"
        assert event.retention_mode == "analyze_only"

    def test_legacy_dedup_still_works(self):
        sensor = _LegacySensor()
        item = {"id": "abc"}
        fp = sensor.source_item_version_fingerprint(item)
        assert isinstance(fp, str)
        identity = sensor.source_item_identity(item)
        assert identity == "abc"

    @pytest.mark.asyncio
    async def test_legacy_fetch_item(self):
        sensor = _LegacySensor()
        result = await sensor.fetch_item({"key": "value"})
        assert result == {"key": "value"}

    def test_retention_mode_default(self):
        sensor = _LegacySensor()
        assert sensor.retention_mode == "analyze_only"

    def test_retention_mode_custom(self):
        sensor = _LegacySensor(retention_mode="retain_raw")
        assert sensor.retention_mode == "retain_raw"
