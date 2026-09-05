"""Connection deletion composes real source storage, memory, and manager lifecycles."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.awareness.ingestion_gateway import SensorIngestionGateway
from magi.awareness.source_ingestion import SourceBatchIngestor
from magi.awareness.source_store import SourceCheckpointConflict, SourceStore
from magi.config.models import AppConfig
from magi.core.sqlite import sqlite_connection_async
from magi.memory.sensor_ingestion import SensorEventCommitter
from magi.memory.unified_store import UnifiedMemoryStore
from magi.plugins.connection_content import ConnectionContentCoordinator
from magi.plugins.connection_settings import validate_connection_settings
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths
from magi_plugin_sdk import Plugin, PluginManifest, PluginPackageState
from magi_plugin_sdk.runtime import SourceChange, SourceChangeBatch
from magi_plugin_sdk.sensors import SensorBase, SensorOutputMetadata, SensorSpec


class ContentSensor(SensorBase):
    sensor_id = "notes"
    source_type = "notes"

    def __init__(self, events):
        super().__init__()
        self.events = events
        self.clear_error = None

    async def build_output(self, item):
        return self._build_output(
            source_item_id=item["id"],
            activity=self._build_activity(
                source=self._build_activity_facet(code="notes", i18n_key="notes", fallback="Notes"),
                action=self._build_activity_facet(code="write", i18n_key="write", fallback="Wrote")),
            narration=self._build_narration(body=item["text"]),
        )

    async def extract_metadata(self, item):
        return SensorOutputMetadata(tags=["notes"])

    async def clear_user_content(self, context):
        self.events.append(("sensor-clear", context.connection_id, context))
        if self.clear_error:
            raise self.clear_error
        (context.runtime_paths.plugin_cache_dir(context.plugin_id) / "sensor-content").unlink(missing_ok=True)


class ContentPlugin(Plugin):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.sensor = ContentSensor(events)
        self.clear_error = None

    def configure(self, **kwargs):
        super().configure(**kwargs)
        self.sensor.bind_plugin_context(connection=self.connection, context=self.context)
        self.events.append(("configured", self.connection_id, self))

    def get_sensors(self):
        return [("notes", self.sensor, SensorSpec("notes", "Notes", domain="timeline"))]

    async def clear_user_content(self, context):
        self.events.append(("plugin-clear", context.connection_id, context))
        if self.clear_error:
            raise self.clear_error
        (context.runtime_paths.plugin_cache_dir(context.plugin_id) / "plugin-content").unlink(missing_ok=True)

    async def shutdown(self):
        self.events.append(("shutdown", self.connection_id, self))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    events = []
    config = AppConfig()
    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    manifest = PluginManifest(
        id="notes", name="Notes", version="0.2.0", execution_mode="trusted_process",
        contribution_types=["sensor"], settings_fields=[
            {"key": "folder", "type": "input", "label": "Folder"},
            {"key": "token", "type": "secret", "label": "Token", "required": True},
        ])
    store = PluginConnectionStore(
        runtime_paths=RuntimePaths(base_dir=tmp_path),
        require_package=lambda plugin_id: manager._require_connection_package(plugin_id),
        authorize_enable=lambda connection: manager._authorize_connection(connection),
        validate_settings=lambda connection: validate_connection_settings(connection, manifest.settings_fields),
    )
    source = SourceStore(tmp_path / "sources.db")
    coordinator = ConnectionContentCoordinator(source)

    def factory(package, connection, context):
        instance = ContentPlugin(events)
        instance.configure(manifest=package, connection=connection, context=context)
        return instance

    manager = PluginManager(
        tool_registry=ToolRegistry(), sensor_registry=SensorRegistry(), search_paths=[],
        request_sensor_schedule_refresh=lambda: None, connection_store=store,
        instance_factory=factory, content_clearer=coordinator.clear,
        connection_disconnector=coordinator.disconnect,
    )
    manager._package_states[manifest.plugin_id] = PluginPackageState(manifest=manifest, trusted=True)
    connections = [manager.create_connection(
        "notes", display_name=name, enabled=True,
        settings={"folder": f"/selected/{name}"}, credentials={"token": f"private-{name}"})
        for name in ("left", "right")]
    for connection in connections:
        context = store.context(connection.connection_id)
        for filename in ("plugin-content", "sensor-content", "source-cursor"):
            (context.state_dir / filename).write_text(connection.display_name)
        (context.resources_dir / "preview.txt").write_text(connection.display_name)
        store.write_state(connection.connection_id, expected_revision=0,
                          private_state={"account": connection.display_name, "cursor": "private-progress"},
                          content_state={"preview": "retained-content"})
    yield SimpleNamespace(manager=manager, store=store, source=source, coordinator=coordinator,
                          connections=connections, events=events)
    asyncio.run(manager.shutdown())


async def seed_source(source, connection, *, ingestor=None, gateway=None, sensor=None):
    resource = await source.register_resource(connection, connection.display_name.encode(), media_type="text/plain")
    change = SourceChange(object_id="same-object", version="v1",
                          payload={"id": "same-object", "text": f"Imported {connection.display_name}"},
                          resources=[resource])
    checkpoint = await source.checkpoint(connection, "notes", "notes")
    pending = await source.stage_batch(connection, checkpoint, SourceChangeBatch(
        changes=[change], next_cursor=f"accepted-{connection.display_name}"))
    if ingestor:
        checkpoint = await ingestor.ingest(
            connection=connection, sensor=sensor, pending=pending,
            boundary=await gateway.capture_ingestion_boundary(), rule_revision="0.2.0",
            allowed_edge_whitelist=[])
    else:
        await source.record_receipt(pending, change, event_id=f"memory-{connection.display_name}", outcome="persisted")
        checkpoint = await source.accept_batch(connection, pending)
    version = await source.version(checkpoint, change)
    pending = await source.stage_batch(connection, checkpoint, SourceChangeBatch(
        changes=[SourceChange(object_id="pending", version="v2", payload={"text": "Pending"})],
        next_cursor="not-yet-accepted"))
    return SimpleNamespace(checkpoint=checkpoint, pending=pending, change=change,
                           resource=resource, evidence=version["evidence_ref"])


async def memory_rows(memory):
    async with sqlite_connection_async(memory.l1_db_path) as db:
        return [dict(row) for row in await db.execute_fetchall("SELECT * FROM fact_events ORDER BY event_id")]


@pytest.mark.asyncio
async def test_clear_one_connection_preserves_other_account_progress_credentials_and_imported_memory(runtime, tmp_path):
    memory = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"), l1_db_path=str(tmp_path / "l1.db"),
        enable_l0=False, enable_l1=True, enable_l2=False, enable_l3=False, enable_l4=False)
    await memory.initialize()
    gateway = SensorIngestionGateway(event_bus=SimpleNamespace(publish=AsyncMock(return_value=True)),
                                    memory_committer=SensorEventCommitter(unified_memory=memory))
    ingestor = SourceBatchIngestor(store=runtime.source, gateway=gateway)
    left, right = runtime.connections
    try:
        seeded = [await seed_source(runtime.source, connection, ingestor=ingestor, gateway=gateway,
                                   sensor=runtime.manager.get_connection_plugin(connection.connection_id).sensor)
                  for connection in runtime.connections]
        before_memory = await memory_rows(memory)
        assert len(before_memory) == 2
        before_boundary = await gateway.capture_ingestion_boundary()
        right_instance = runtime.manager.get_connection_plugin(right.connection_id)
        right_state = runtime.store.read_state(right.connection_id)
        left_private = runtime.store.read_state(left.connection_id)[1]
        start = len(runtime.events)
        cleared = await asyncio.to_thread(runtime.manager.clear_connection_content, left.connection_id,
                                          expected_revision=left.revision)

        assert cleared.enabled and cleared.settings == left.settings
        assert cleared.credential_refs == left.credential_refs
        assert runtime.store.context(left.connection_id).credentials.get("token") == "private-left"
        assert runtime.store.read_state(left.connection_id)[1:] == (left_private, {})
        assert runtime.store.get(right.connection_id) == right
        assert runtime.store.read_state(right.connection_id) == right_state
        assert runtime.manager.get_connection_plugin(right.connection_id) is right_instance
        assert runtime.store.context(right.connection_id).credentials.get("token") == "private-right"

        left_context, right_context = [runtime.store.context(item.connection_id) for item in runtime.connections]
        assert not (left_context.state_dir / "plugin-content").exists()
        assert not (left_context.state_dir / "sensor-content").exists()
        assert (left_context.state_dir / "source-cursor").read_text() == "left"
        assert list(left_context.resources_dir.iterdir()) == []
        assert (right_context.resources_dir / "preview.txt").read_text() == "right"
        assert (right_context.state_dir / "plugin-content").read_text() == "right"
        assert (right_context.state_dir / "sensor-content").read_text() == "right"

        events = runtime.events[start:]
        assert [event[0] for event in events] == [
            "shutdown", "configured", "plugin-clear", "sensor-clear", "shutdown", "configured"]
        assert {event[1] for event in events} == {left.connection_id}
        for kind, _, context in events:
            if kind not in {"plugin-clear", "sensor-clear"}:
                continue
            assert context.request.connection_id == left.connection_id
            assert context.request.clear_generation is None
            assert context.plugin_settings == left.settings
            assert context.preserve_credentials and context.preserve_source_progress
            assert not context.network_access_allowed
            assert context.runtime_paths.plugin_cache_dir("notes") == left_context.state_dir
            assert context.sensor_id == ("notes" if kind == "sensor-clear" else None)

        fresh = await runtime.source.checkpoint(cleared, "notes", "notes")
        assert fresh.cursor == seeded[0].checkpoint.cursor
        assert fresh.revision == seeded[0].checkpoint.revision + 1
        assert await runtime.source.pending(fresh) is None
        assert await runtime.source.current_object(fresh, "same-object") is None
        for ref in (seeded[0].resource, seeded[0].evidence):
            with pytest.raises(PermissionError):
                await runtime.source.read_resource(cleared, ref)
        with pytest.raises(SourceCheckpointConflict):
            await runtime.source.accept_batch(cleared, seeded[0].pending)
        with pytest.raises(SourceCheckpointConflict):
            await runtime.source.stage_batch(cleared, seeded[0].checkpoint, SourceChangeBatch())
        assert await runtime.source.checkpoint(right, "notes", "notes") == seeded[1].checkpoint
        assert await runtime.source.pending(seeded[1].checkpoint) == seeded[1].pending
        assert await runtime.source.read_resource(right, seeded[1].resource) == b"right"
        assert await runtime.source.read_resource(right, seeded[1].evidence)
        assert await memory_rows(memory) == before_memory
        assert await gateway.capture_ingestion_boundary() == before_boundary
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_disconnect_fences_only_its_source_connection_before_erasing_private_state(runtime):
    left, right = runtime.connections
    left_seed = await seed_source(runtime.source, left)
    right_seed = await seed_source(runtime.source, right)
    await asyncio.to_thread(runtime.manager.disconnect_connection, left.connection_id,
                            expected_revision=left.revision)
    with pytest.raises(KeyError):
        runtime.store.get(left.connection_id)
    assert not (runtime.store.root / "instances" / left.connection_id).exists()
    for stale in (left, left.model_copy(update={"revision": left.revision + 100})):
        with pytest.raises(SourceCheckpointConflict):
            await runtime.source.checkpoint(stale, "notes", "notes")
    with pytest.raises(SourceCheckpointConflict):
        await runtime.source.accept_batch(left, left_seed.pending)
    assert runtime.store.get(right.connection_id) == right
    assert runtime.store.context(right.connection_id).credentials.get("token") == "private-right"
    assert await runtime.source.pending(right_seed.checkpoint) == right_seed.pending
    assert await runtime.source.read_resource(right, right_seed.resource) == b"right"


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_hook", ["plugin", "sensor"])
async def test_clear_hook_failure_does_not_revoke_source_resources_or_claim_success(runtime, failing_hook):
    left = runtime.connections[0]
    seeded = await seed_source(runtime.source, left)
    plugin = runtime.manager.get_connection_plugin(left.connection_id)
    target = plugin if failing_hook == "plugin" else plugin.sensor
    target.clear_error = RuntimeError("Clear hook failed")
    with pytest.raises(RuntimeError, match="Clear hook failed"):
        await runtime.coordinator.clear(left, plugin, plugin.context)
    assert await runtime.source.checkpoint(left, "notes", "notes") == seeded.checkpoint
    assert await runtime.source.pending(seeded.checkpoint) == seeded.pending
    assert await runtime.source.read_resource(left, seeded.evidence)
    assert runtime.store.get(left.connection_id) == left


@pytest.mark.asyncio
async def test_mismatched_clear_context_is_rejected_before_hooks_or_source_changes(runtime):
    left, right = runtime.connections
    seeded = await seed_source(runtime.source, left)
    plugin = runtime.manager.get_connection_plugin(left.connection_id)
    start = len(runtime.events)
    with pytest.raises(ValueError, match="another connection"):
        await runtime.coordinator.clear(left, plugin, runtime.store.context(right.connection_id))
    assert runtime.events[start:] == []
    assert await runtime.source.read_resource(left, seeded.resource) == b"left"


@pytest.mark.asyncio
async def test_clear_timeout_cancels_hook_without_erasing_source_progress_or_evidence(runtime):
    left = runtime.connections[0]
    seeded = await seed_source(runtime.source, left)
    cancelled = asyncio.Event()
    plugin = runtime.manager.get_connection_plugin(left.connection_id)

    async def blocked_clear(context):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    plugin.clear_user_content = blocked_clear
    coordinator = ConnectionContentCoordinator(runtime.source, timeout_seconds=0.01)
    with pytest.raises(TimeoutError):
        await coordinator.clear(left, plugin, plugin.context)
    assert cancelled.is_set()
    assert await runtime.source.checkpoint(left, "notes", "notes") == seeded.checkpoint
    assert await runtime.source.pending(seeded.checkpoint) == seeded.pending
    assert await runtime.source.read_resource(left, seeded.evidence)
