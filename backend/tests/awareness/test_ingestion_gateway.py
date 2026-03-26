"""Tests for SensorIngestionGateway."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import (
    ContentBlock,
    SensorMemoryPolicy,
    SensorOutput,
    SensorOutputMetadata,
)
from magi.awareness.sensor_state import SqliteSensorStateStore
from magi.memory.event_contracts import MemoryDomain, IngestTarget, RetentionClass, TomDepth


class _FakeSensor(SensorBase):
    sensor_id = "test.fake"
    source_type = "fake_source"
    update_key_fields = ("id",)
    memory_policy = SensorMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=True,
        retention_class="permanent",
        importance_bias=0.7,
        author_type="external",
        content_type="observation",
    )

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        return self._build_output(
            source_item_id=str(item["id"]),
            title="Fake title",
            summary="Fake summary",
        )


def _make_output(**overrides: Any) -> SensorOutput:
    defaults = dict(
        source_type="fake_source",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        title="Test Event",
        summary="Something happened",
        content_blocks=[ContentBlock(kind="text", value="hello")],
        tags=["tag1"],
    )
    defaults.update(overrides)
    return SensorOutput(**defaults)


class TestSensorIngestionGateway:
    @pytest.mark.asyncio
    async def test_ingest_calls_unified_memory(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()

        result = await gateway.ingest(sensor, output)

        assert result.event_id == "fake_source:item-1"
        assert result.ingested is True
        memory.ingest_event.assert_awaited_once()

        # Verify the MemoryEvent dict was passed
        call_args = memory.ingest_event.call_args[0][0]
        assert call_args["event_type"] == "SENSOR_EVENT"
        assert call_args["source"] == "fake_source"

    @pytest.mark.asyncio
    async def test_ingest_applies_memory_policy(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()

        await gateway.ingest(sensor, output)

        call_args = memory.ingest_event.call_args[0][0]
        assert call_args["memory_domain"] == "external_activity"
        assert call_args["ingest_target"] == "l1_only"
        assert call_args["retention_class"] == "permanent"
        assert call_args["importance_score"] == 0.7

    @pytest.mark.asyncio
    async def test_ingest_with_timeline_adapter(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        adapter = MagicMock()
        adapter.on_sensor_output = AsyncMock()
        gateway = SensorIngestionGateway(
            unified_memory=memory,
            timeline_adapter=adapter,
        )
        sensor = _FakeSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(tags=["extra"])

        await gateway.ingest(sensor, output, metadata)

        adapter.on_sensor_output.assert_awaited_once_with(
            "fake_source:item-1", output, metadata,
        )

    @pytest.mark.asyncio
    async def test_ingest_no_adapter_is_ok(self):
        """Gateway works fine without a timeline adapter."""
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()

        result = await gateway.ingest(sensor, output)
        assert result.ingested is True

    @pytest.mark.asyncio
    async def test_ingest_updates_state_store(self, tmp_path):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        state_store = SqliteSensorStateStore(tmp_path / "state.db")
        gateway = SensorIngestionGateway(
            unified_memory=memory,
            sensor_state_store=state_store,
        )
        sensor = _FakeSensor()
        output = _make_output()

        await gateway.ingest(sensor, output)

        fps = await state_store.get_known_fingerprints("test.fake")
        assert len(fps) == 1

    @pytest.mark.asyncio
    async def test_ingest_processes_relations(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(
            relation_candidates=[
                {
                    "predicate": "LIKES",
                    "object_id": "topic:test",
                    "confidence": 0.9,
                },
            ],
        )

        result = await gateway.ingest(
            sensor, output, metadata,
            allowed_edge_whitelist=["LIKES"],
        )
        assert result.stats["relation_count"] == 1
        memory.upsert_user_graph_edge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ingest_skips_disallowed_relations(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        memory.upsert_user_graph_edge = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output()
        metadata = SensorOutputMetadata(
            relation_candidates=[
                {
                    "predicate": "LIKES",
                    "object_id": "topic:test",
                },
            ],
        )

        # No allowed edge whitelist → relations skipped
        result = await gateway.ingest(sensor, output, metadata)
        assert result.stats["relation_count"] == 0
        memory.upsert_user_graph_edge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_content_fallback_to_content_blocks(self):
        memory = MagicMock()
        memory.ingest_event = AsyncMock()
        gateway = SensorIngestionGateway(unified_memory=memory)
        sensor = _FakeSensor()
        output = _make_output(title="", summary="", content_blocks=[ContentBlock(kind="text", value="block text")])

        await gateway.ingest(sensor, output)

        call_args = memory.ingest_event.call_args[0][0]
        assert call_args["content"] == "block text"
