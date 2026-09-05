"""Production scheduler-to-L1 coverage for connection-scoped source batches."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection, SourceChange, SourceChangeBatch
from magi_plugin_sdk.sensors import SensorBase, SensorOutputMetadata, SensorSpec

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.scheduler_contrib import SensorSchedulerContrib
from magi.awareness.source_store import source_object_identity
from magi.core.sqlite import sqlite_connection_async
from magi.memory.sensor_ingestion import SensorEventCommitter
from magi.memory.unified_store import UnifiedMemoryStore


class NotesSensor(SensorBase):
    sensor_id = "notes.sensor"
    source_type = "notes"
    supports_pull_sync = True
    update_key_fields = ("id",)

    def __init__(self, owner, tmp_path):
        super().__init__()
        context = PluginContext(owner, tmp_path / owner.connection_id / "state", tmp_path / owner.connection_id / "resources", Mock())
        context.state_dir.mkdir(parents=True)
        context.resources_dir.mkdir(parents=True)
        self.bind_plugin_context(connection=owner, context=context)
        self.collect_count = 0
        self.fail_object = None
        self.batch = SourceChangeBatch(changes=[
            SourceChange(object_id="one", version="v1", payload={"id": "one", "text": "First note"}),
            SourceChange(object_id="two", version="v1", payload={"id": "two", "text": "Second note"}),
        ], next_cursor="opaque:1")

    async def collect_items(self, context):
        assert context.connection_id == self.connection.connection_id
        assert context.source_type == "notes"
        assert context.runtime_paths.plugin_cache_dir("notes") == self.context.state_dir
        self.collect_count += 1
        return self.batch

    async def build_output(self, item):
        if item["id"] == self.fail_object:
            raise RuntimeError("Transient source enrichment failed")
        return self._build_output(
            source_item_id=item["id"],
            activity=self._build_activity(
                source=self._build_activity_facet(code="notes", i18n_key="notes", fallback="Notes"),
                action=self._build_activity_facet(code="write", i18n_key="write", fallback="Wrote"),
                qualifiers={"count": 2},
            ),
            narration=self._build_narration(body=item["text"]),
            domain_payload={"source_connection_id": "forged", "author_hint": "user"},
        )

    async def extract_metadata(self, item):
        return SensorOutputMetadata(tags=["notes"], fact_hints=[{
            "fact_kind": "interaction", "predicate": "WROTE", "evidence": {"text": item["text"]}
        }])


def owner(name="account-a"):
    return PluginConnection(connection_id=name, plugin_id="notes", display_name=name, enabled=True)


async def setup_runtime(tmp_path, sensors):
    memory = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"), l1_db_path=str(tmp_path / "l1.db"),
        enable_l0=False, enable_l1=True, enable_l2=False, enable_l3=False, enable_l4=False,
    )
    await memory.initialize()
    bus = SimpleNamespace(publish=AsyncMock(return_value=True))
    gateway = SensorIngestionGateway(event_bus=bus, memory_committer=SensorEventCommitter(unified_memory=memory))
    registry = Mock()
    registry.resolve_source_sensor.side_effect = lambda source_type, connection_id: (
        "notes", "notes.sensor", sensors[connection_id], SensorSpec(sensor_id="notes.sensor", display_name="Notes")
    )
    manager = Mock()
    manager.get_package.return_value = SimpleNamespace(manifest=SimpleNamespace(version="0.2.0"))
    contrib = SensorSchedulerContrib(
        scheduler_service=Mock(), sensor_registry=registry, plugin_manager=manager,
        runtime_paths=SimpleNamespace(runtime_dir=tmp_path), get_config=lambda: None, ingestion_gateway=gateway,
    )
    return memory, contrib, bus


async def sync(contrib, connection_id="account-a", scheduler_cursor=None):
    return await contrib._run_sensor_sync(
        schedule_id="manual", target_key=f"{connection_id}:notes", source_type="notes", manual=True,
        target_state=SimpleNamespace(last_cursor=scheduler_cursor, last_success_at=None),
        sync_payload={"connection_id": connection_id},
    )


async def events(memory):
    async with sqlite_connection_async(memory.l1_db_path) as db:
        rows = await db.execute_fetchall("SELECT * FROM fact_events ORDER BY source_item_id, idempotency_key")
        return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_scheduler_commits_real_l1_and_connection_identity_without_changing_source_type(tmp_path):
    sensors = {name: NotesSensor(owner(name), tmp_path) for name in ("account-a", "account-b")}
    memory, contrib, bus = await setup_runtime(tmp_path, sensors)
    try:
        await sync(contrib, "account-a")
        await sync(contrib, "account-b")
        stored = await events(memory)
        assert len(stored) == 4
        assert {row["source"] for row in stored} == {"notes"}
        assert len({row["idempotency_key"] for row in stored}) == 4
        assert source_object_identity("account-a", "notes.sensor", "one") in {row["source_item_id"] for row in stored}
        emitted = bus.publish.await_args_list[0].args[0].data
        assert emitted.output_dict["domain_payload"]["source_connection_id"] == "account-a"
        assert emitted.output_dict["domain_payload"]["projection_rule_revision"] == "0.2.0"
        assert emitted.metadata_dict["fact_hints"][0]["predicate"] == "WROTE"
        assert emitted.output_dict["activity"]["qualifiers"]["count"] == 2
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_partial_failure_retries_original_batch_before_advancing_cursor(tmp_path):
    sensor = NotesSensor(owner(), tmp_path)
    sensor.fail_object = "two"
    memory, contrib, _ = await setup_runtime(tmp_path, {"account-a": sensor})
    try:
        with pytest.raises(RuntimeError, match="Transient"):
            await sync(contrib)
        checkpoint = await contrib.source_store.checkpoint(owner(), "notes.sensor", "notes")
        assert checkpoint.cursor is None
        assert len(await events(memory)) == 1
        sensor.fail_object = None
        sensor.batch = SourceChangeBatch(changes=[], next_cursor="must-not-collect")
        result = await sync(contrib, scheduler_cursor="stale-scheduler-cache")
        assert result.next_cursor == "opaque:1"
        assert sensor.collect_count == 1
        assert len(await events(memory)) == 2
        assert await contrib.source_store.pending(await contrib.source_store.checkpoint(owner(), "notes.sensor", "notes")) is None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_new_object_revision_reaches_l1_and_deletion_does_not_forget_history(tmp_path):
    sensor = NotesSensor(owner(), tmp_path)
    sensor.batch = SourceChangeBatch(changes=[sensor.batch.changes[0]], next_cursor="one")
    memory, contrib, _ = await setup_runtime(tmp_path, {"account-a": sensor})
    try:
        await sync(contrib)
        sensor.batch = SourceChangeBatch(changes=[SourceChange(object_id="one", version="v2", payload={"id": "one", "text": "Revised note"})], next_cursor="two")
        await sync(contrib)
        assert len(await events(memory)) == 2
        sensor.batch = SourceChangeBatch(changes=[SourceChange(object_id="one", version="v3", operation="delete")], next_cursor="three")
        await sync(contrib)
        assert len(await events(memory)) == 2
        checkpoint = await contrib.source_store.checkpoint(owner(), "notes.sensor", "notes")
        assert (await contrib.source_store.current_object(checkpoint, "one"))["deleted"] == 1
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_untyped_sensor_result_is_rejected_without_checkpoint_progress(tmp_path):
    sensor = NotesSensor(owner(), tmp_path)
    sensor.batch = SimpleNamespace(items=[], next_cursor="invalid")
    memory, contrib, _ = await setup_runtime(tmp_path, {"account-a": sensor})
    try:
        with pytest.raises(TypeError, match="SourceChangeBatch"):
            await sync(contrib)
        assert (await contrib.source_store.checkpoint(owner(), "notes.sensor", "notes")).cursor is None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_scoped_output_resource_is_imported_and_revoked_with_source_delete(tmp_path):
    sensor = NotesSensor(owner(), tmp_path)
    sensor.batch = SourceChangeBatch(changes=[sensor.batch.changes[0]], next_cursor="one")
    thumbnail = sensor.context.resources_dir / "thumbnail.txt"
    thumbnail.write_text("private content")
    build = sensor.build_output

    async def with_resource(item):
        output = await build(item)
        output.raw_payload_ref = str(thumbnail)
        return output

    sensor.build_output = with_resource
    memory, contrib, bus = await setup_runtime(tmp_path, {"account-a": sensor})
    try:
        await sync(contrib)
        from magi_plugin_sdk.runtime import ResourceRef
        output = bus.publish.await_args.args[0].data.output_dict
        ref = ResourceRef.model_validate(output["domain_payload"]["source_resource_refs"][0])
        assert output["raw_payload_ref"] == ref.resource_id
        assert await contrib.source_store.read_resource(owner(), ref) == b"private content"
        sensor.batch = SourceChangeBatch(changes=[SourceChange(object_id="one", version="v2", operation="delete")], next_cursor="two")
        await sync(contrib)
        with pytest.raises(PermissionError):
            await contrib.source_store.read_resource(owner(), ref)
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_resource_path_outside_connection_is_rejected(tmp_path):
    sensor = NotesSensor(owner(), tmp_path)
    external = tmp_path / "outside.txt"
    external.write_text("another connection secret")
    build = sensor.build_output

    async def with_resource(item):
        output = await build(item)
        output.raw_payload_ref = str(external)
        return output

    sensor.build_output = with_resource
    memory, contrib, _ = await setup_runtime(tmp_path, {"account-a": sensor})
    try:
        with pytest.raises(PermissionError, match="host-allocated"):
            await sync(contrib)
        assert not await events(memory)
        assert (await contrib.source_store.checkpoint(owner(), "notes.sensor", "notes")).cursor is None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_push_timeline_uses_same_source_acceptance_and_real_l1(tmp_path, monkeypatch):
    from magi.timeline import handler as timeline
    sensor = NotesSensor(owner(), tmp_path)
    memory, contrib, bus = await setup_runtime(tmp_path, {"account-a": sensor})
    contrib._sensor_registry.resolve_source_sensor.side_effect = lambda source_type, connection_id: (
        "notes", "notes.sensor", sensor, SensorSpec(sensor_id="notes.sensor", display_name="Notes", domain="timeline")
    )
    monkeypatch.setattr(timeline, "get_runtime_paths", lambda: SimpleNamespace(runtime_dir=tmp_path))
    handler = timeline.build_timeline_handler(None, memory, sensor_registry=contrib._sensor_registry, plugin_manager=contrib._plugin_manager, ingestion_gateway=contrib._ingestion_gateway)
    try:
        result = await handler({"source_type": "notes", "connection_id": "account-a", "source_change": sensor.batch.changes[0].model_dump()})
        assert result["handled"] is True
        assert result["event_id"]
        assert len(await events(memory)) == 1
        checkpoint = await contrib.source_store.checkpoint(owner(), "notes.sensor", "notes")
        assert checkpoint.cursor is None
        assert (await contrib.source_store.current_object(checkpoint, "one"))["version"] == "v1"
        with pytest.raises(ValueError, match="connection"):
            await handler({"source_type": "notes"})
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_push_only_sensor_is_queued_without_worker_reentry_then_committed(tmp_path):
    sensor = NotesSensor(owner(), tmp_path)
    sensor.supports_pull_sync = False
    memory, contrib, _ = await setup_runtime(tmp_path, {"account-a": sensor})
    contrib._scheduler_service.schedule_once = AsyncMock()
    payload = {"source_type": "notes", "connection_id": "account-a", "source_change": sensor.batch.changes[0].model_dump()}
    try:
        await contrib.queue_source_change(payload)
        assert sensor.collect_count == 0
        call = contrib._scheduler_service.schedule_once.await_args.kwargs
        assert call["target_payload"]["connection_id"] == "account-a"
        assert call["target_payload"]["source_type"] == "notes"
        result = await contrib._run_sensor_sync(
            schedule_id=call["schedule_id"], target_key=call["target_key"], source_type="notes",
            manual=False, target_state=SimpleNamespace(last_success_at=None),
            sync_payload=call["target_payload"],
        )
        assert result.success
        assert sensor.collect_count == 0
        assert len(await events(memory)) == 1
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_connection_readiness_ignores_other_account_and_deleted_l1(tmp_path):
    from magi.awareness.source_readiness import visible_source_event_ids
    sensors = {name: NotesSensor(owner(name), tmp_path) for name in ("account-a", "account-b")}
    memory, contrib, _ = await setup_runtime(tmp_path, sensors)
    try:
        await sync(contrib, "account-a")
        await sync(contrib, "account-b")
        ids = await visible_source_event_ids(contrib.source_store, memory, connection_id="account-a", source_type="notes")
        assert len(ids) == 2
        await memory.l1.mark_deleted(ids[0])
        remaining = await visible_source_event_ids(contrib.source_store, memory, connection_id="account-a", source_type="notes")
        assert len(remaining) == 1
        assert ids[0] not in remaining
        assert len(await visible_source_event_ids(contrib.source_store, memory, connection_id="account-b", source_type="notes")) == 2
    finally:
        await memory.shutdown()
