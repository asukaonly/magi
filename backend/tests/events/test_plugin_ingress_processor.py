from __future__ import annotations

import asyncio

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.runtime_trace import PluginIngressEventRecord, RuntimeTraceStore


class _RecordingHandler:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def handle_event(self, event: PluginIngressEventRecord, payload: dict[str, object]) -> None:
        self.events.append((event.event_type, payload))


class _FailingHandler:
    async def handle_event(self, event: PluginIngressEventRecord, payload: dict[str, object]) -> None:
        raise RuntimeError(f"cannot process {event.event_type}")


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
