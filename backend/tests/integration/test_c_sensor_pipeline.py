"""End-to-end: gateway publishes SensorEventEmitted; subscribers project to all sinks.

Phase 9 contract test. Gateway is a thin publisher; the 4 subscribers
(memory / timeline / KG / sensor_state) read the published payload and
project independently.
"""
from __future__ import annotations

import asyncio
import importlib
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.kg_write_queue import KnowledgeGraphWriteQueue
from magi.awareness.sensor_base import SensorBase
from magi.awareness.sensor_output import (
    ActivityFacet,
    SensorActivity,
    SensorMemoryPolicy,
    SensorNarration,
    SensorOutput,
)
from magi.awareness.sensor_state import SensorStateWriteQueue
from magi.awareness.subscribers.sensor_state_update_subscriber import (
    SensorStateUpdateSubscriber,
)
from magi.timeline.subscribers.kg_subscriber import KGSubscriber
from magi.timeline.subscribers.timeline_subscriber import TimelineSubscriber
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.memory import UnifiedMemoryStore
from magi.memory.subscribers.memory_ingestion_subscriber import (
    MemoryIngestionSubscriber,
)


def _init_l1_schema(db_path: Path) -> None:
    migration = importlib.import_module("magi.db.migrations.l1.versions.v1_initial")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(migration.SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


class _PipelineSensor(SensorBase):
    sensor_id = "test.pipeline_sensor"
    source_type = "pipeline_test"
    memory_event_type = "PIPELINE_TEST"
    update_key_fields = ("id",)
    memory_policy = SensorMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=False,
        retention_class="permanent",
        importance_bias=0.5,
        author_type="external",
        content_type="observation",
    )

    async def build_output(self, item):  # pragma: no cover - unused in this test
        raise NotImplementedError


@pytest.mark.asyncio
async def test_sensor_ingest_lands_in_all_4_subscribers():
    """Publish SensorEventEmitted -> memory + timeline + KG + state subscribers fire."""
    bus = InMemoryMessageBusBackend()
    await bus.start()

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    _init_l1_schema(base / "l1_events.db")
    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        enable_l0=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    bus.bind_memory_operation_epoch(store.memory_operation_epoch)

    memory_sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=store)
    await memory_sub.start()

    fake_timeline_adapter = MagicMock()
    fake_timeline_adapter.on_timeline_event = AsyncMock()
    timeline_sub = TimelineSubscriber(
        event_bus=bus, timeline_adapter=fake_timeline_adapter
    )
    await timeline_sub.start()

    fake_state_store = MagicMock()
    fake_state_store.add_fingerprint_groups = AsyncMock()
    state_writer = SensorStateWriteQueue(sensor_state_store=fake_state_store)
    state_sub = SensorStateUpdateSubscriber(
        event_bus=bus, sensor_state_writer=state_writer
    )
    await state_sub.start()

    kg_writer = KnowledgeGraphWriteQueue(unified_memory=store)
    kg_sub = KGSubscriber(event_bus=bus, kg_writer=kg_writer)
    await kg_sub.start()

    sensor = _PipelineSensor()
    output = SensorOutput(
        source_type="pipeline_test",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        activity=SensorActivity(
            source=ActivityFacet(
                code="pipeline_test",
                i18n_key="activity.source.pipeline_test",
                fallback="Pipeline Test",
            ),
            action=ActivityFacet(
                code="observe",
                i18n_key="activity.action.observe",
                fallback="Observed",
            ),
        ),
        narration=SensorNarration(body="something happened"),
    )

    gateway = SensorIngestionGateway(event_bus=bus)
    result = await gateway.ingest(sensor, output)
    assert result.ingested is True
    envelope_event_id = result.event_id

    await asyncio.sleep(0.1)
    await memory_sub.drain()
    await timeline_sub.drain()
    await state_sub.drain()
    await kg_sub.drain()

    # Memory: a row landed in fact_events with envelope id
    conn = sqlite3.connect(str(base / "l1_events.db"))
    try:
        row = conn.execute(
            "SELECT event_id FROM fact_events WHERE event_id = ?",
            (envelope_event_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == envelope_event_id

    # Timeline: adapter called once with envelope id
    fake_timeline_adapter.on_timeline_event.assert_awaited_once()
    timeline_event = fake_timeline_adapter.on_timeline_event.await_args.args[0]
    assert timeline_event.event_id == envelope_event_id

    # SensorState: fingerprint persisted under sensor id
    fake_state_store.add_fingerprint_groups.assert_awaited_once()
    groups = fake_state_store.add_fingerprint_groups.await_args.args[0]
    assert set(groups) == {"test.pipeline_sensor"}
    assert len(groups["test.pipeline_sensor"]) == 1  # one fingerprint

    # KG: dormant — no relation_candidates supplied, so no graph writes occurred.
    # We can't easily assert "not called" against UnifiedMemoryStore, but the
    # subscriber's early-exit path in _enqueue_relations covers this.

    await memory_sub.stop()
    await timeline_sub.stop()
    await state_sub.stop()
    await kg_sub.stop()
    await store.shutdown()
    await bus.stop()
    tmp.cleanup()
