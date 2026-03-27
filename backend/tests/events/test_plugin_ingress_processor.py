from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.runtime_trace import PluginIngressEventRecord, RuntimeTraceStore
from magi.utils.runtime import RuntimePaths

_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from screen_time.plugin import ScreenTimePlugin
from screen_time.state import ScreenTimeStateStore


class _RecordingHandler:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def handle_event(self, event: PluginIngressEventRecord, payload: dict[str, object]) -> None:
        self.events.append((event.event_type, payload))


class _FailingHandler:
    async def handle_event(self, event: PluginIngressEventRecord, payload: dict[str, object]) -> None:
        raise RuntimeError(f"cannot process {event.event_type}")


class _LoadedPluginManager:
    def __init__(self, plugins: list[object]) -> None:
        self._plugins = list(plugins)

    def iter_loaded_plugins(self) -> list[object]:
        return list(self._plugins)


@pytest.mark.asyncio
async def test_plugin_ingress_processor_routes_matching_events(tmp_path) -> None:
    from magi.events.plugin_ingress import PluginIngressHandlerRegistration
    from magi.events.lifecycle import PluginIngressProcessorModule

    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    handler = _RecordingHandler()

    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store

    processor = PluginIngressProcessorModule(
        context,
        handlers=[
            PluginIngressHandlerRegistration(
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                handler=handler,
            )
        ],
        poll_interval_seconds=0.01,
    )
    await processor.init()

    try:
        await store.append_plugin_ingress_event(
            PluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=1_711_523_200_000,
                payload_json='{"bundle_id":"com.apple.Safari","app_name":"Safari"}',
                created_at_ms=1_711_523_200_050,
            )
        )

        for _ in range(100):
            if handler.events:
                break
            await asyncio.sleep(0.02)

        assert handler.events == [
            (
                "frontmost_app_activated",
                {"bundle_id": "com.apple.Safari", "app_name": "Safari"},
            )
        ]
    finally:
        await processor.shutdown()
        await store.shutdown()


@pytest.mark.asyncio
async def test_plugin_ingress_processor_marks_events_failed_when_handler_raises(tmp_path) -> None:
    from magi.events.plugin_ingress import PluginIngressHandlerRegistration
    from magi.events.lifecycle import PluginIngressProcessorModule

    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()

    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store

    processor = PluginIngressProcessorModule(
        context,
        handlers=[
            PluginIngressHandlerRegistration(
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                handler=_FailingHandler(),
            )
        ],
        poll_interval_seconds=0.01,
    )
    await processor.init()

    try:
        event_id = await store.append_plugin_ingress_event(
            PluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=1_711_523_200_000,
                payload_json='{"bundle_id":"com.apple.Safari","app_name":"Safari"}',
                created_at_ms=1_711_523_200_050,
            )
        )

        for _ in range(100):
            failed = await store.get_plugin_ingress_event(event_id)
            if failed is not None and failed.status == "failed":
                break
            await asyncio.sleep(0.02)

        failed = await store.get_plugin_ingress_event(event_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.last_error is not None
        assert "cannot process frontmost_app_activated" in failed.last_error
    finally:
        await processor.shutdown()
        await store.shutdown()


@pytest.mark.asyncio
async def test_plugin_ingress_processor_loads_screen_time_handler_from_plugin_manager(tmp_path) -> None:
    from magi.events.lifecycle import PluginIngressProcessorModule

    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")
    store = RuntimeTraceStore(db_path=str(runtime_paths.runtime_trace_db_path))
    await store.initialize()

    plugin = ScreenTimePlugin()
    plugin.configure(manifest=None, settings={})

    context = RuntimeBootstrapContext()
    context.core.runtime_paths = runtime_paths
    context.plugins.plugin_manager = _LoadedPluginManager([plugin])
    context.runtime_trace.store = store

    processor = PluginIngressProcessorModule(
        context,
        poll_interval_seconds=0.01,
    )

    with patch("sys.platform", "darwin"):
        await processor.init()

    try:
        first_event_id = await store.append_plugin_ingress_event(
            PluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 15, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json='{"bundle_id":"com.apple.Safari","app_name":"Safari"}',
                created_at_ms=1_711_523_200_000,
            )
        )
        second_event_id = await store.append_plugin_ingress_event(
            PluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 42, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json='{"bundle_id":"com.apple.Terminal","app_name":"Terminal"}',
                created_at_ms=1_711_523_200_100,
            )
        )

        for _ in range(100):
            first = await store.get_plugin_ingress_event(first_event_id)
            second = await store.get_plugin_ingress_event(second_event_id)
            if (
                first is not None
                and first.status == "completed"
                and second is not None
                and second.status == "completed"
            ):
                break
            await asyncio.sleep(0.02)

        first = await store.get_plugin_ingress_event(first_event_id)
        second = await store.get_plugin_ingress_event(second_event_id)
        assert first is not None
        assert second is not None
        assert first.status == "completed"
        assert second.status == "completed"

        state_store = ScreenTimeStateStore()
        completed = await state_store.flush_completed(
            runtime_paths=runtime_paths,
            now=datetime(2026, 3, 27, 11, 5, tzinfo=timezone.utc),
        )

        assert completed == [
            {
                "bucket_start": "2026-03-27T10:00:00+00:00",
                "bucket_end": "2026-03-27T11:00:00+00:00",
                "bundle_id": "com.apple.Safari",
                "app_name": "Safari",
                "duration_seconds": 1620,
                "session_count": 1,
            },
            {
                "bucket_start": "2026-03-27T10:00:00+00:00",
                "bucket_end": "2026-03-27T11:00:00+00:00",
                "bundle_id": "com.apple.Terminal",
                "app_name": "Terminal",
                "duration_seconds": 1080,
                "session_count": 1,
            },
        ]
    finally:
        await processor.shutdown()
        await store.shutdown()
