"""End-to-end: gateway commits L1 before publishing derived source projections."""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection

from magi.awareness.ingestion_gateway import SourceIngestionGateway
from magi.awareness.source_ingestion import SourceBatchIngestor
from magi.awareness.source_store import SourceStore
from magi.awareness.kg_write_queue import KnowledgeGraphWriteQueue
from magi.awareness.source_base import Source
from magi.awareness.source_output import (
    ActivityFacet,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
    SourceOutput,
)
from magi.awareness.source_state import SourceStateWriteQueue
from magi.awareness.subscribers.source_state_update_subscriber import (
    SourceStateUpdateSubscriber,
)
from magi.timeline.subscribers.kg_subscriber import KGSubscriber
from magi.timeline.subscribers.timeline_subscriber import TimelineSubscriber
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.memory import SourceEventCommitter, UnifiedMemoryStore


def _init_l1_schema(db_path: Path) -> None:
    migration = importlib.import_module("magi.db.migrations.l1.versions.v1_initial")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(migration.SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


class _PipelineSource(Source):
    source_id = "test.pipeline_source"
    source_type = "pipeline_test"
    memory_event_type = "PIPELINE_TEST"
    update_key_fields = ("id",)
    memory_policy = SourceMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=False,
        retention_class="permanent",
        importance_bias=0.5,
        author_type="external",
        content_type="observation",
    )

    async def build_output(self, item):
        return SourceOutput.from_dict(item["output"])


@pytest.mark.asyncio
async def test_source_ingest_commits_memory_before_derived_subscribers():
    """Commit L1 synchronously, then publish timeline, graph, and state projections."""
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

    fake_timeline_adapter = MagicMock()
    fake_timeline_adapter.on_timeline_event = AsyncMock()
    timeline_sub = TimelineSubscriber(event_bus=bus, timeline_adapter=fake_timeline_adapter)
    await timeline_sub.start()

    fake_state_store = MagicMock()
    fake_state_store.add_fingerprint_groups = AsyncMock()
    state_writer = SourceStateWriteQueue(source_state_store=fake_state_store)
    state_sub = SourceStateUpdateSubscriber(event_bus=bus, source_state_writer=state_writer)
    await state_sub.start()

    kg_writer = KnowledgeGraphWriteQueue(unified_memory=store)
    kg_sub = KGSubscriber(event_bus=bus, kg_writer=kg_writer)
    await kg_sub.start()

    source = _PipelineSource()
    output = SourceOutput(
        source_type="pipeline_test",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        activity=SourceActivity(
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
        narration=SourceNarration(body="something happened"),
    )

    gateway = SourceIngestionGateway(
        event_bus=bus,
        memory_committer=SourceEventCommitter(unified_memory=store),
    )
    connection = PluginConnection(
        connection_id="pipeline-account", plugin_id="pipeline", display_name="Pipeline", enabled=True,
    )
    context = PluginContext(connection, base / "state", base / "resources", MagicMock())
    source.bind_plugin_context(connection=connection, context=context)
    source_store = SourceStore(base / "sources.db")
    checkpoint = await source_store.checkpoint(connection, source.source_id, source.source_type)
    batch = source.build_change_batch([{"id": "item-1", "output": output.to_dict()}], next_cursor="next")
    pending = await source_store.stage_batch(connection, checkpoint, batch)
    ingestor = SourceBatchIngestor(store=source_store, gateway=gateway)
    checkpoint = await ingestor.ingest(
        connection=connection, source=source, pending=pending,
        boundary=await gateway.capture_ingestion_boundary(), rule_revision="test-package-revision",
        allowed_edge_whitelist=[],
    )
    version = await source_store.version(checkpoint, batch.changes[0])
    envelope_event_id = version["receipt"]["event_id"]
    assert checkpoint.cursor == "next"

    await asyncio.sleep(0.1)
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

    # SourceState: fingerprint is scoped to its host-issued connection and source.
    fake_state_store.add_fingerprint_groups.assert_awaited_once()
    groups = fake_state_store.add_fingerprint_groups.await_args.args[0]
    source_key = f"{connection.connection_id}:{source.source_id}"
    assert set(groups) == {source_key}
    assert len(groups[source_key]) == 1

    # KG: dormant — no relation_candidates supplied, so no graph writes occurred.
    # We can't easily assert "not called" against UnifiedMemoryStore, but the
    # subscriber's early-exit path in _enqueue_relations covers this.

    await timeline_sub.stop()
    await state_sub.stop()
    await kg_sub.stop()
    await store.shutdown()
    await bus.stop()
    tmp.cleanup()
