"""Tests for awareness layer sensor contracts and components."""

from __future__ import annotations

from typing import Any

import pytest

from magi.awareness.sensor_output import (
    ActivityFacet,
    ContentBlock,
    SensorActivity,
    SensorMemoryPolicy,
    SensorNarration,
    SensorOutput,
    SensorOutputMetadata,
)
from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_sync import SensorSyncContext


# ── SensorOutput ──

class TestSensorOutput:
    def test_round_trip(self):
        output = SensorOutput(
            source_type="test_sensor",
            source_item_id="item-1",
            occurred_at=1700000000.0,
            captured_at=1700000001.0,
            activity=SensorActivity(
                source=ActivityFacet(
                    code="test_sensor",
                    i18n_key="activity.source.test_sensor",
                    fallback="Test Sensor",
                ),
                action=ActivityFacet(
                    code="observe",
                    i18n_key="activity.action.observe",
                    fallback="Observed",
                ),
            ),
            narration=SensorNarration(body="Something happened", title="Test Event"),
            content_blocks=[ContentBlock(kind="text", value="hello")],
            tags=["tag1"],
            entities=[{"name": "test"}],
            provenance={"sensor_id": "test"},
            domain_payload={"custom": True},
        )
        d = output.to_dict()
        restored = SensorOutput.from_dict(d)
        assert restored.source_type == "test_sensor"
        assert restored.source_item_id == "item-1"
        assert restored.occurred_at == 1700000000.0
        assert restored.activity.source.code == "test_sensor"
        assert restored.narration.title == "Test Event"
        assert len(restored.content_blocks) == 1
        assert restored.content_blocks[0].kind == "text"
        assert restored.tags == ["tag1"]
        assert restored.domain_payload == {"custom": True}

    def test_from_dict_minimal(self):
        d = {
            "source_type": "s",
            "source_item_id": "id1",
            "occurred_at": 100.0,
            "captured_at": 200.0,
            "activity": {
                "source": {
                    "code": "test_source",
                    "i18n_key": "activity.source.test_source",
                    "fallback": "Test Source",
                },
                "action": {
                    "code": "observe",
                    "i18n_key": "activity.action.observe",
                    "fallback": "Observed",
                },
            },
            "narration": {
                "body": "Observed event",
            },
        }
        output = SensorOutput.from_dict(d)
        assert output.source_type == "s"
        assert output.activity.action.code == "observe"
        assert output.narration.body == "Observed event"
        assert output.content_blocks == []
        assert output.tags == []


class TestSensorMemoryPolicy:
    def test_frozen(self):
        policy = SensorMemoryPolicy()
        with pytest.raises(AttributeError):
            policy.importance_bias = 0.9  # type: ignore[misc]

    def test_defaults(self):
        policy = SensorMemoryPolicy()
        assert policy.memory_domain == "external_activity"
        assert policy.ingest_target == "l1_only"
        assert policy.cognition_eligible is True
        assert policy.retention_class == "compressible"
        assert policy.importance_bias == 0.5

    def test_custom_values(self):
        policy = SensorMemoryPolicy(
            memory_domain="runtime_telemetry",
            ingest_target="runtime_only",
            cognition_eligible=False,
            retention_class="disposable",
            importance_bias=0.3,
        )
        assert policy.retention_class == "disposable"
        assert policy.importance_bias == 0.3


class TestSensorOutputMetadata:
    def test_defaults(self):
        meta = SensorOutputMetadata()
        assert meta.entities == []
        assert meta.tags == []
        assert meta.relation_candidates == []


# ── SensorBase ──

class _ConcreteSensor(SensorBase):
    sensor_id = "test.concrete"
    source_type = "test_source"
    update_key_fields = ("id", "hash")
    memory_policy = SensorMemoryPolicy(importance_bias=0.7)

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        return self._build_output(
            source_item_id=str(item["id"]),
            activity=self._build_activity(
                source=self._build_activity_facet(
                    code="test_source",
                    i18n_key="activity.source.test_source",
                    fallback="Test Source",
                ),
                action=self._build_activity_facet(
                    code="observe",
                    i18n_key="activity.action.observe",
                    fallback="Observed",
                ),
            ),
            narration=self._build_narration(
                title=str(item.get("title", "")),
                body=str(item.get("summary", "")),
            ),
            occurred_at=item.get("occurred_at"),
            tags=item.get("tags", []),
        )


class TestSensorBase:
    def test_memory_policy(self):
        sensor = _ConcreteSensor()
        assert sensor.memory_policy.importance_bias == 0.7

    def test_fingerprint_dedup(self):
        sensor = _ConcreteSensor()
        item = {"id": "1", "hash": "abc"}
        fp = sensor.source_item_version_fingerprint(item)
        assert isinstance(fp, str)
        assert len(fp) == 40  # SHA1 hex

        item2 = {"id": "1", "hash": "def"}
        fp2 = sensor.source_item_version_fingerprint(item2)
        assert fp != fp2

    def test_source_item_identity(self):
        sensor = _ConcreteSensor()
        identity = sensor.source_item_identity({"id": "x", "hash": "y"})
        assert identity == "x:y"

    @pytest.mark.asyncio
    async def test_discover_changes(self):
        sensor = _ConcreteSensor()
        items = [{"id": "1", "hash": "a"}, {"id": "2", "hash": "b"}]
        fp = sensor.source_item_version_fingerprint(items[0])
        changes = await sensor.discover_changes(items, known_fingerprints={fp})
        assert len(changes) == 1
        assert changes[0]["id"] == "2"

    @pytest.mark.asyncio
    async def test_build_output_helper(self):
        sensor = _ConcreteSensor()
        item = {"id": "item-1", "title": "Test", "summary": "Sum", "occurred_at": 1700000000.0}
        output = await sensor.build_output(item)
        assert output.source_type == "test_source"
        assert output.source_item_id == "item-1"
        assert output.narration.title == "Test"
        assert output.narration.body == "Sum"

    @pytest.mark.asyncio
    async def test_extract_metadata_default(self):
        sensor = _ConcreteSensor()
        meta = await sensor.extract_metadata({})
        assert isinstance(meta, SensorOutputMetadata)
        assert meta.entities == []

    @pytest.mark.asyncio
    async def test_collect_items_not_implemented(self):
        sensor = _ConcreteSensor()
        ctx = SensorSyncContext(
            source_type="test", manual=False,
            last_cursor=None, last_success_at=None,
            limit=100, runtime_paths=None,  # type: ignore[arg-type]
        )
        with pytest.raises(NotImplementedError):
            await sensor.collect_items(ctx)

    @pytest.mark.asyncio
    async def test_fetch_item_default(self):
        sensor = _ConcreteSensor()
        result = await sensor.fetch_item({"key": "value"})
        assert result == {"key": "value"}
