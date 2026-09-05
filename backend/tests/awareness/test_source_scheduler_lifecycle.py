from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.ingestion_gateway import SourceIngestionResult
from magi.awareness.source_base import Source
from magi.awareness.source_output import (
    ActivityFacet,
    ContentBlock,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
)
from magi.awareness.scheduler_contrib import SourceSchedulerContrib
from magi.awareness.source_sync import PullSource
from magi.awareness.source_store import SourceStore, SourceCheckpointConflict
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import PluginConnection, SourceChangeBatch
from types import SimpleNamespace
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.memory.source_ingestion import SourceIngestionBoundary
from magi.plugins.sources import SourceRegistry, SourceSpec
from magi.scheduler.contracts import (
    ScheduledTargetState,
    ScheduledTargetType,
    build_source_target_key,
)
from magi.utils.runtime import RuntimePaths


class _FakeUnifiedMemory:
    async def ingest_event(self, event_dict):
        pass

    async def upsert_user_graph_edge(self, **kwargs):
        pass


class _FakeTimelineService:
    async def on_source_output(self, *args, **kwargs):
        return None


CONNECTION_ID = "pull-account"
CONNECTION = PluginConnection(
    connection_id=CONNECTION_ID, plugin_id="pull-plugin", display_name="Pull account", enabled=True,
    settings={"sources": {"pull_history": {"enabled": True, "sync_mode": "interval",
        "sync_interval_minutes": 5, "edge_whitelist": ["LIKES"]}}},
)


class _FakePluginManager:
    def __init__(self) -> None:
        self.package = SimpleNamespace(manifest=SimpleNamespace(version="0.2.0"))

    def get_package(self, plugin_id: str):
        return self.package if plugin_id == "pull-plugin" else None


class _FakeSchedulerRepository:
    def __init__(self) -> None:
        self.schedules: dict[str, object] = {}

    async def get_schedule(self, schedule_id: str):
        return self.schedules.get(schedule_id)


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.registrations: list[tuple[object, object]] = []
        self.repository = _FakeSchedulerRepository()
        self.interval_calls: list[dict[str, object]] = []
        self.unschedule_calls: list[dict[str, object]] = []
        self.once_calls: list[dict[str, object]] = []
        self.cursor_updates: list[dict[str, object]] = []

    def register_handler(self, target_type, handler) -> None:  # type: ignore[no-untyped-def]
        self.registrations.append((target_type, handler))

    async def schedule_interval(self, **kwargs):  # type: ignore[no-untyped-def]
        self.interval_calls.append(kwargs)
        schedule = type(
            "Schedule", (), {"schedule_id": kwargs["schedule_id"], "job_id": kwargs["schedule_id"]}
        )()
        self.repository.schedules[kwargs["schedule_id"]] = schedule
        return schedule

    async def unschedule(self, schedule_id, **kwargs):  # type: ignore[no-untyped-def]
        self.unschedule_calls.append({"schedule_id": schedule_id, **kwargs})
        self.repository.schedules.pop(schedule_id, None)

    async def schedule_once(self, **kwargs):  # type: ignore[no-untyped-def]
        self.once_calls.append(kwargs)
        return type("Schedule", (), {"schedule_id": kwargs["schedule_id"]})()

    async def update_target_cursor(self, target_type, target_key, *, cursor, watermark_ts=None):  # type: ignore[no-untyped-def]
        self.cursor_updates.append(
            {
                "target_type": target_type,
                "target_key": target_key,
                "cursor": cursor,
                "watermark_ts": watermark_ts,
            }
        )


class _PullHistorySource(Source, PullSource):
    source_id = "timeline.pull_history"
    display_name = "Pull History"
    source_type = "pull_history"
    supports_pull_sync = True
    update_key_fields = ("item_id",)
    memory_policy = SourceMemoryPolicy()

    async def collect_items(self, context):
        return self.build_change_batch(
            items=[
                {
                    "item_id": "item-1",
                    "title": "Pulled item",
                    "timestamp": 1710000000.0,
                    "relation_candidates": [],
                }
            ],
            next_cursor="cursor-2",
            watermark_ts=1710000000.0,
            stats={"count": 1},
        )

    async def build_output(self, item):
        return self._build_output(
            source_item_id=str(item["item_id"]),
            activity=SourceActivity(
                source=ActivityFacet(
                    code="test_source",
                    i18n_key="activity.source.test",
                    fallback="test source",
                ),
                action=ActivityFacet(
                    code="pull",
                    i18n_key="activity.action.pull",
                    fallback="pull",
                ),
                object=ActivityFacet(
                    code=str(item["item_id"]),
                    i18n_key="activity.object.item",
                    fallback=str(item["title"]),
                ),
            ),
            narration=SourceNarration(
                title=str(item["title"]),
                body=str(item["title"]),
            ),
            occurred_at=float(item["timestamp"]),
            content_blocks=[ContentBlock(kind="text", value=str(item["title"]))],
        )


class _EpochBoundarySource(_PullHistorySource):
    def __init__(self, *, clear_phase: str, advance_epoch) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._clear_phase = clear_phase
        self._advance_epoch = advance_epoch
        self._clear_triggered = False

    def _trigger_clear(self, phase: str) -> None:
        if self._clear_triggered or self._clear_phase != phase:
            return
        self._clear_triggered = True
        self._advance_epoch()

    async def collect_items(self, context):
        self._trigger_clear("collect_items")
        return self.build_change_batch(
            items=[
                {
                    "item_id": f"item-{index}",
                    "title": f"Pulled item {index}",
                    "timestamp": 1710000000.0 + index,
                    "modified_at": 1710000000.0 + index,
                }
                for index in range(2)
            ],
            next_cursor="cursor-after-clear",
            watermark_ts=1710000001.0,
            stats={"count": 2, "cursor_kind": "modified_at"},
        )

    async def fetch_item(self, item):
        self._trigger_clear("fetch_item")
        return await super().fetch_item(item)

    async def build_output(self, item):
        output = await super().build_output(item)
        self._trigger_clear("build_output")
        return output

    async def extract_metadata(self, item):
        metadata = await super().extract_metadata(item)
        self._trigger_clear("extract_metadata")
        return metadata


class _OpaqueCursorSource(_PullHistorySource):
    async def collect_items(self, context):
        return self.build_change_batch(
            items=[
                {
                    "item_id": f"item-{idx}",
                    "title": f"Pulled item {idx}",
                    "timestamp": 1710000000.0 + idx,
                    "modified_at": 1710000000.0 + idx,
                    "relation_candidates": [],
                }
                for idx in range(55)
            ],
            next_cursor='{"version":1,"mode":"backfill","page":2}',
            watermark_ts=1710000055.0,
            stats={"count": 55, "cursor_kind": "opaque"},
        )


class _ModifiedCursorSource(_OpaqueCursorSource):
    async def collect_items(self, context):
        result = await super().collect_items(context)
        return result.model_copy(update={"next_cursor": "cursor-final", "stats": {"count": 55}})


class _ContextRecordingSource(_PullHistorySource):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[object] = []

    async def collect_items(self, context):
        self.contexts.append(context)
        return self.build_change_batch(
            items=[],
            next_cursor=None,
            watermark_ts=None,
            stats={"count": 0},
        )


def _build_source_registry(tmp_path) -> SourceRegistry:
    return _build_source_registry_with_source(_PullHistorySource(), tmp_path)


def _build_source_registry_with_source(source: Source, tmp_path) -> SourceRegistry:
    context = PluginContext(CONNECTION, tmp_path / "state", tmp_path / "resources", MagicMock())
    context.state_dir.mkdir(parents=True, exist_ok=True)
    context.resources_dir.mkdir(parents=True, exist_ok=True)
    source.bind_plugin_context(connection=CONNECTION, context=context)
    source_registry = SourceRegistry()
    registered_id = f"{CONNECTION_ID}:{source.source_id}"
    source_registry.register(
        "pull-plugin", registered_id, source,
        SourceSpec(
            source_id=registered_id, display_name="Pull History",
            description="Pull-capable source", domain="timeline", surface="timeline", sync_mode="interval",
            metadata={"source_type": "pull_history", "connection_id": CONNECTION_ID,
                      "local_source_id": source.source_id, "default_settings": CONNECTION.settings["sources"]["pull_history"]},
        ),
    )
    return source_registry


class _FakeIngestionGateway:
    def __init__(
        self,
        *,
        fail_on_attempt: int | None = None,
        reject_on_attempt: int | None = None,
        clear_after_attempt: int | None = None,
    ) -> None:
        self.items: list[object] = []
        self.attempt_count = 0
        self.fail_on_attempt = fail_on_attempt
        self.reject_on_attempt = reject_on_attempt
        self.clear_after_attempt = clear_after_attempt
        self.memory_epoch = 11
        self.clear_generation = 0
        self.clear_cutoff_at = 0.0
        self.memory_epoch_capture_count = 0
        self.expected_epochs: list[int | None] = []
        self.allow_pre_clear_events: list[bool] = []
        self.governed_skip_count = 0

    async def capture_ingestion_boundary(self) -> SourceIngestionBoundary:
        self.memory_epoch_capture_count += 1
        return SourceIngestionBoundary(
            expected_epoch=self.memory_epoch,
            clear_generation=self.clear_generation,
            clear_cutoff_at=self.clear_cutoff_at,
        )

    def advance_memory_epoch(self) -> None:
        self.memory_epoch += 1
        self.clear_generation += 1
        self.clear_cutoff_at = time.time()
        self.items.clear()

    async def ingest(
        self,
        source,
        output,
        metadata,
        *,
        allowed_edge_whitelist=None,
        boundary=None,
        allow_pre_clear_events=False,
        host_idempotency_key=None,
    ):  # type: ignore[no-untyped-def]
        assert host_idempotency_key
        self.attempt_count += 1
        assert boundary is not None
        self.expected_epochs.append(boundary.expected_epoch)
        self.allow_pre_clear_events.append(bool(allow_pre_clear_events))
        if self.fail_on_attempt == self.attempt_count:
            raise OSError("L1 unavailable")
        if self.reject_on_attempt == self.attempt_count:
            return SourceIngestionResult(
                event_id=f"event-{self.attempt_count}",
                ingested=False,
            )
        effective_epoch = int(boundary.expected_epoch)
        older_than_clear = bool(
            boundary.clear_generation > 0
            and not allow_pre_clear_events
            and float(output.occurred_at) <= float(boundary.clear_cutoff_at)
        )
        if effective_epoch == self.memory_epoch and not older_than_clear:
            self.items.append(output)
            result = SourceIngestionResult(
                event_id=f"event-{self.attempt_count}",
                ingested=True,
                stats={"memory_outcome": "persisted", "projection_published": True},
            )
        else:
            self.governed_skip_count += 1
            skip_reason = (
                "memory_clear_epoch_changed"
                if effective_epoch != self.memory_epoch
                else "memory_clear_cutoff"
            )
            result = SourceIngestionResult(
                event_id=f"event-{self.attempt_count}",
                ingested=True,
                stats={
                    "memory_outcome": "governed_skip",
                    "projection_published": False,
                    "skip_reason": skip_reason,
                },
            )
        if self.clear_after_attempt == self.attempt_count:
            self.advance_memory_epoch()
        return result


@pytest.mark.asyncio
async def test_source_schedule_registration_module_registers_handler_and_syncs_schedules(
    monkeypatch, tmp_path
) -> None:
    from magi.awareness.lifecycle import SourceScheduleRegistrationModule
    from magi.scheduler.contracts import ScheduledTargetType, build_source_schedule_id

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.source_store = SourceStore(tmp_path / "sources.db")
    context.plugins.source_registry = _build_source_registry(tmp_path)
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())
    context.agent_runtime.source_ingestion_gateway = _FakeIngestionGateway()

    module = SourceScheduleRegistrationModule(context)
    await module.init()

    registrations = context.scheduler.scheduler_service.registrations
    assert len(registrations) == 1
    assert registrations[0][0] == ScheduledTargetType.SOURCE_SYNC
    assert context.scheduler.scheduler_service.interval_calls[0][
        "schedule_id"
    ] == build_source_schedule_id(
        CONNECTION_ID,
        "pull_history",
    )
    assert context.agent_runtime.source_scheduler_contrib is not None

    await module.shutdown()
    assert context.agent_runtime.source_scheduler_contrib is None


@pytest.mark.asyncio
async def test_source_schedule_registration_module_supports_manual_sync(tmp_path) -> None:
    from magi.awareness.lifecycle import SourceScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.source_store = SourceStore(tmp_path / "sources.db")
    context.plugins.source_registry = _build_source_registry(tmp_path)
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())
    context.agent_runtime.source_ingestion_gateway = _FakeIngestionGateway()

    module = SourceScheduleRegistrationModule(context)
    await module.init()

    schedule = await module.queue_manual_sync("pull_history", connection_id=CONNECTION_ID)

    assert schedule.schedule_id.startswith("source-sync-manual:pull-account:pull_history:")
    assert context.scheduler.scheduler_service.once_calls[0]["run_at"] <= time.time() + 1.0

    await module.shutdown()


@pytest.mark.asyncio
async def test_source_schedule_registration_module_queues_backfill_with_stable_scope(
    tmp_path,
) -> None:
    from magi.awareness.lifecycle import SourceScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.source_store = SourceStore(tmp_path / "sources.db")
    context.plugins.source_registry = _build_source_registry(tmp_path)
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())
    context.agent_runtime.source_ingestion_gateway = _FakeIngestionGateway()

    module = SourceScheduleRegistrationModule(context)
    await module.init()

    first = await module.queue_manual_sync(
        "pull_history",
        connection_id=CONNECTION_ID,
        sync_mode="backfill",
        backfill_scope="last_30_days",
        backfill_days=30,
    )
    second = await module.queue_manual_sync(
        "pull_history",
        connection_id=CONNECTION_ID,
        sync_mode="backfill",
        backfill_scope="last_30_days",
        backfill_days=30,
    )

    assert first.schedule_id == "source-sync-backfill:pull-account:pull_history:last_30_days"
    assert second.schedule_id == first.schedule_id
    once_call = context.scheduler.scheduler_service.once_calls[0]
    assert once_call["target_payload"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "last_30_days",
        "backfill_days": 30,
    }
    assert once_call["metadata"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "last_30_days",
        "backfill_days": 30,
    }

    await module.shutdown()


@pytest.mark.asyncio
async def test_source_schedule_registration_module_queues_custom_backfill_with_stable_range(
    tmp_path,
) -> None:
    from magi.awareness.lifecycle import SourceScheduleRegistrationModule

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = RuntimePaths(tmp_path / "runtime")
    context.plugins.source_store = SourceStore(tmp_path / "sources.db")
    context.plugins.source_registry = _build_source_registry(tmp_path)
    context.plugins.plugin_manager = _FakePluginManager()
    context.timeline.timeline_service = _FakeTimelineService()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.memory.unified_memory = _FakeUnifiedMemory()
    context.message_bus.message_bus = MagicMock(publish=AsyncMock())
    context.agent_runtime.source_ingestion_gateway = _FakeIngestionGateway()

    module = SourceScheduleRegistrationModule(context)
    await module.init()

    first = await module.queue_manual_sync(
        "pull_history",
        connection_id=CONNECTION_ID,
        sync_mode="backfill",
        backfill_scope="custom",
        backfill_start_date="2026-06-01",
        backfill_end_date="2026-06-30",
    )
    second = await module.queue_manual_sync(
        "pull_history",
        connection_id=CONNECTION_ID,
        sync_mode="backfill",
        backfill_scope="custom",
        backfill_start_date="2026-06-01",
        backfill_end_date="2026-06-30",
    )

    assert (
        first.schedule_id
        == "source-sync-backfill:pull-account:pull_history:custom:2026-06-01:2026-06-30"
    )
    assert second.schedule_id == first.schedule_id
    once_call = context.scheduler.scheduler_service.once_calls[0]
    assert once_call["target_payload"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
    }
    assert once_call["metadata"]["sync_request"] == {
        "mode": "backfill",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
    }

    await module.shutdown()


@pytest.mark.asyncio
async def test_source_sync_backfill_request_uses_initial_history_context(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    source = _ContextRecordingSource()
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(source, tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_source_sync(
        schedule_id="source-sync-backfill:pull-account:pull_history:last_30_days",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            last_cursor="existing-cursor",
            last_success_at=1710000000.0,
        ),
        sync_payload={
            "connection_id": CONNECTION_ID,
            "sync_request": {
                "mode": "backfill",
                "backfill_scope": "last_30_days",
                "backfill_days": 30,
            }
        },
    )

    assert len(source.contexts) == 1
    context = source.contexts[0]
    assert context.last_cursor is None
    source_settings = context.plugin_settings["sources"]["pull_history"]
    assert source_settings["initial_sync_policy"] == "lookback_days"
    assert source_settings["initial_sync_lookback_days"] == 30


@pytest.mark.asyncio
async def test_source_sync_custom_backfill_request_uses_custom_history_context(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    source = _ContextRecordingSource()
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(source, tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_source_sync(
        schedule_id="source-sync-backfill:pull-account:pull_history:custom:2026-06-01:2026-06-30",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            last_cursor="existing-cursor",
            last_success_at=1710000000.0,
        ),
        sync_payload={
            "connection_id": CONNECTION_ID,
            "sync_request": {
                "mode": "backfill",
                "backfill_scope": "custom",
                "backfill_start_date": "2026-06-01",
                "backfill_end_date": "2026-06-30",
            }
        },
    )

    assert len(source.contexts) == 1
    context = source.contexts[0]
    assert context.last_cursor is None
    source_settings = context.plugin_settings["sources"]["pull_history"]
    assert source_settings["initial_sync_policy"] == "custom_range"
    assert source_settings["initial_sync_start_date"] == "2026-06-01"
    assert source_settings["initial_sync_end_date"] == "2026-06-30"


@pytest.mark.asyncio
async def test_source_sync_backfill_continuation_keeps_backfill_cursor(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    source = _ContextRecordingSource()
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(source, tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    accepted_cursor = '{"version":1,"mode":"backfill","capture_before":1718409600}'
    checkpoint = await contrib.source_store.checkpoint(CONNECTION, source.source_id, source.source_type)
    pending = await contrib.source_store.stage_batch(
        CONNECTION, checkpoint, SourceChangeBatch(changes=[], next_cursor=accepted_cursor),
    )
    await contrib.source_store.accept_batch(CONNECTION, pending)

    await contrib._run_source_sync(
        schedule_id="source-sync-continuation:pull-account:pull_history:abc123",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            last_cursor="stale-scheduler-cursor",
            last_success_at=1710000000.0,
        ),
        sync_payload={
            "connection_id": CONNECTION_ID,
            "sync_request": {
                "mode": "backfill",
                "backfill_scope": "custom",
                "backfill_start_date": "2026-06-01",
                "backfill_end_date": "2026-06-30",
            }
        },
    )

    assert len(source.contexts) == 1
    assert (
        source.contexts[0].last_cursor
        == '{"version":1,"mode":"backfill","capture_before":1718409600}'
    )


@pytest.mark.asyncio
async def test_source_sync_opaque_cursor_skips_mid_batch_checkpoint(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(_OpaqueCursorSource(), tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    result = await contrib._run_source_sync(
        schedule_id="source-sync:pull-account:pull_history",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=False,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            last_cursor=None,
            last_success_at=None,
        ),
        sync_payload={"connection_id": CONNECTION_ID},
    )

    assert result.next_cursor == '{"version":1,"mode":"backfill","page":2}'
    assert len(ingestion_gateway.items) == 55
    assert scheduler_service.cursor_updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["raise", "reject"])
async def test_source_sync_does_not_checkpoint_unconfirmed_item(
    tmp_path,
    failure_mode: str,
) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway(
        fail_on_attempt=50 if failure_mode == "raise" else None,
        reject_on_attempt=50 if failure_mode == "reject" else None,
    )
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(_ModifiedCursorSource(), tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    with pytest.raises((OSError, RuntimeError)):
        await contrib._run_source_sync(
            schedule_id="source-sync:pull-account:pull_history",
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            source_type="pull_history",
            manual=False,
            target_state=ScheduledTargetState(
                target_type=ScheduledTargetType.SOURCE_SYNC,
                target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
                last_cursor="cursor-before-run",
                last_success_at=1710000000.0,
            ),
            sync_payload={"connection_id": CONNECTION_ID},
        )

    assert ingestion_gateway.attempt_count == 50
    assert len(ingestion_gateway.items) == 49
    assert scheduler_service.cursor_updates == []


@pytest.mark.asyncio
async def test_source_sync_retains_receipts_without_partial_checkpoint(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway(fail_on_attempt=51)
    target_key = build_source_target_key(CONNECTION_ID, "pull_history")
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(_ModifiedCursorSource(), tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    with pytest.raises(OSError, match="L1 unavailable"):
        await contrib._run_source_sync(
            schedule_id="source-sync:pull-account:pull_history",
            target_key=target_key,
            source_type="pull_history",
            manual=False,
            target_state=ScheduledTargetState(
                target_type=ScheduledTargetType.SOURCE_SYNC,
                target_key=target_key,
                last_cursor="cursor-before-run",
                last_success_at=1710000000.0,
            ),
            sync_payload={"connection_id": CONNECTION_ID},
        )

    assert ingestion_gateway.attempt_count == 51
    assert len(ingestion_gateway.items) == 50
    assert scheduler_service.cursor_updates == []
    checkpoint = await contrib.source_store.checkpoint(CONNECTION, "timeline.pull_history", "pull_history")
    assert checkpoint.cursor is None
    pending = await contrib.source_store.pending(checkpoint)
    assert pending is not None
    versions = [await contrib.source_store.version(checkpoint, change) for change in pending.batch.changes]
    assert sum(version["receipt"] is not None for version in versions) == 50



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clear_phase",
    ["collect_items", "fetch_item", "build_output", "extract_metadata"],
)
async def test_source_sync_discards_stale_batch_when_clear_crosses_source_phase(
    tmp_path,
    clear_phase: str,
) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    initial_epoch = ingestion_gateway.memory_epoch
    source = _EpochBoundarySource(
        clear_phase=clear_phase,
        advance_epoch=ingestion_gateway.advance_memory_epoch,
    )
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(source, tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    with pytest.raises(SourceCheckpointConflict, match="Memory was cleared"):
        await contrib._run_source_sync(
            schedule_id="source-sync:pull-account:pull_history",
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            source_type="pull_history",
            manual=False,
            target_state=ScheduledTargetState(
                target_type=ScheduledTargetType.SOURCE_SYNC,
                target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
                last_cursor="cursor-before-clear",
                last_success_at=1710000000.0,
            ),
            sync_payload={"connection_id": CONNECTION_ID},
        )

    checkpoint = await contrib.source_store.checkpoint(CONNECTION, source.source_id, source.source_type)
    assert checkpoint.cursor is None
    assert scheduler_service.cursor_updates == []
    assert ingestion_gateway.memory_epoch_capture_count == 1
    assert ingestion_gateway.expected_epochs == [initial_epoch]
    assert ingestion_gateway.governed_skip_count == 1
    assert ingestion_gateway.items == []


@pytest.mark.asyncio
async def test_source_sync_keeps_batch_epoch_between_item_iterations(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway(clear_after_attempt=1)
    initial_epoch = ingestion_gateway.memory_epoch
    source = _EpochBoundarySource(
        clear_phase="never",
        advance_epoch=ingestion_gateway.advance_memory_epoch,
    )
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(source, tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    with pytest.raises(SourceCheckpointConflict, match="Memory was cleared"):
        await contrib._run_source_sync(
            schedule_id="source-sync:pull-account:pull_history",
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
            source_type="pull_history",
            manual=False,
            target_state=ScheduledTargetState(
                target_type=ScheduledTargetType.SOURCE_SYNC,
                target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
                last_cursor="cursor-before-clear",
                last_success_at=1710000000.0,
            ),
            sync_payload={"connection_id": CONNECTION_ID},
        )

    checkpoint = await contrib.source_store.checkpoint(CONNECTION, source.source_id, source.source_type)
    assert checkpoint.cursor is None
    assert scheduler_service.cursor_updates == []
    assert ingestion_gateway.memory_epoch_capture_count == 1
    assert ingestion_gateway.expected_epochs == [initial_epoch, initial_epoch]
    assert ingestion_gateway.governed_skip_count == 1
    assert ingestion_gateway.items == []


@pytest.mark.asyncio
async def test_automatic_source_sync_advances_past_pre_clear_history(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    ingestion_gateway.clear_generation = 2
    ingestion_gateway.clear_cutoff_at = 1_800_000_000.0
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(_PullHistorySource(), tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    result = await contrib._run_source_sync(
        schedule_id="source-sync:pull-account:pull_history",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=False,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        ),
        admitted_at=1_800_000_001.0,
        sync_payload={"connection_id": CONNECTION_ID},
    )

    assert result.success is True
    assert result.next_cursor == "cursor-2"
    assert ingestion_gateway.items == []
    assert ingestion_gateway.governed_skip_count == 1
    assert ingestion_gateway.allow_pre_clear_events == [False]


@pytest.mark.asyncio
async def test_manual_source_sync_requested_after_clear_can_restore_history(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    ingestion_gateway.clear_generation = 2
    ingestion_gateway.clear_cutoff_at = 1_800_000_000.0
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(_PullHistorySource(), tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_source_sync(
        schedule_id="source-sync-manual:pull-account:pull_history:test",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        ),
        admitted_at=1_800_000_001.0,
        sync_payload={"connection_id": CONNECTION_ID},
    )

    assert len(ingestion_gateway.items) == 1
    assert ingestion_gateway.allow_pre_clear_events == [True]


@pytest.mark.asyncio
async def test_manual_source_sync_queued_before_clear_cannot_restore_history(tmp_path) -> None:
    scheduler_service = _FakeSchedulerService()
    ingestion_gateway = _FakeIngestionGateway()
    ingestion_gateway.clear_generation = 2
    ingestion_gateway.clear_cutoff_at = 1_800_000_000.0
    contrib = SourceSchedulerContrib(
        scheduler_service=scheduler_service,
        source_registry=_build_source_registry_with_source(_PullHistorySource(), tmp_path),
        plugin_manager=_FakePluginManager(),
        runtime_paths=RuntimePaths(tmp_path / "runtime"),
        get_config=lambda: None,
        ingestion_gateway=ingestion_gateway,
    )

    await contrib._run_source_sync(
        schedule_id="source-sync-manual:pull-account:pull_history:test",
        target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        source_type="pull_history",
        manual=True,
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(CONNECTION_ID, "pull_history"),
        ),
        admitted_at=1_799_999_999.0,
        sync_payload={"connection_id": CONNECTION_ID},
    )

    assert ingestion_gateway.items == []
    assert ingestion_gateway.governed_skip_count == 1
    assert ingestion_gateway.allow_pre_clear_events == [False]
