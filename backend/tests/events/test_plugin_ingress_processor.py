from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from magi.events.plugin_ingress import PluginIngressRegistry
from unittest.mock import AsyncMock

import pytest

from _shared.sqlite_privacy import assert_sqlite_fragment_absent
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.runtime_trace import RuntimeTraceStore, StoredPluginIngressEventRecord
from magi_plugin_sdk.ingress import PluginIngressEventRecord


def ingress_registry(entries):
    registry = PluginIngressRegistry()
    registry.register("conn_test", "epoch_test", entries)
    return registry


class _RecordingHandler:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def handle_event(self, event: PluginIngressEventRecord, payload: dict[str, object]) -> None:
        self.events.append((event.event_type, payload))


class _FailingHandler:
    async def handle_event(self, event: PluginIngressEventRecord, payload: dict[str, object]) -> None:
        raise RuntimeError(f"cannot process {event.event_type}")


class _BlockingHandler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def handle_event(
        self,
        _event: PluginIngressEventRecord,
        _payload: dict[str, object],
    ) -> None:
        self.started.set()
        await self.release.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("completion_committed", [False, True])
async def test_failed_claim_persistence_recovers_without_replaying_an_active_handler(
    tmp_path, monkeypatch, completion_committed,
):
    from magi.events.lifecycle import PluginIngressProcessorModule
    from magi.events.plugin_ingress import PluginIngressHandlerRegistration

    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    registry = PluginIngressRegistry()
    slow, fast = _BlockingHandler(), _RecordingHandler()
    for cid, target, handler in (("slow", "slow-plugin", slow), ("fast", "fast-plugin", fast)):
        registry.register(cid, "epoch_test", [PluginIngressHandlerRegistration(
            target, "observed", handler, replay_safe=True,
        )])
    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store
    processor = PluginIngressProcessorModule(
        context, registry=registry,
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: "epoch_test"),
        global_clear_pending=AsyncMock(return_value=False), poll_interval_seconds=0.01,
    )
    original_complete = store.complete_plugin_ingress_event
    completion_failed = False

    async def complete(event_id):
        nonlocal completion_failed
        if not completion_failed:
            completion_failed = True
            if completion_committed:
                await original_complete(event_id)
            raise sqlite3.OperationalError("Transient completion storage failure")
        await original_complete(event_id)

    original_recover = store.recover_plugin_ingress_consumer
    recovery_attempts = 0

    async def recover(consumer_name):
        nonlocal recovery_attempts
        recovery_attempts += 1
        if recovery_attempts < 3:
            raise sqlite3.OperationalError("Transient recovery storage failure")
        await original_recover(consumer_name)

    monkeypatch.setattr(store, "complete_plugin_ingress_event", complete)
    monkeypatch.setattr(store, "recover_plugin_ingress_consumer", recover)
    await processor.init()
    try:
        slow_id = await store.append_plugin_ingress_event(StoredPluginIngressEventRecord(
            event_id=0, connection_id="slow", connection_epoch="epoch_test",
            source_kind="background_delivery", producer="slow-device", plugin_target="slow-plugin",
            event_type="observed", occurred_at_ms=1,
        ))
        await asyncio.wait_for(slow.started.wait(), 2)
        fast_ids = []
        for sequence in (1, 2):
            fast_ids.append(await store.append_plugin_ingress_event(StoredPluginIngressEventRecord(
                event_id=0, connection_id="fast", connection_epoch="epoch_test",
                source_kind="background_delivery", producer="fast-device", plugin_target="fast-plugin",
                event_type="observed", occurred_at_ms=sequence, cursor_key="stream",
                payload_json=f'{{"sequence":{sequence}}}',
            )))
        for _ in range(200):
            if recovery_attempts >= 3 and (await store.get_plugin_ingress_event(fast_ids[-1])).status == "completed":
                break
            await asyncio.sleep(0.01)
        assert [(await store.get_plugin_ingress_event(eid)).status for eid in fast_ids] == ["completed", "completed"]
        assert [payload["sequence"] for _, payload in fast.events] == (
            [1, 2] if completion_committed else [1, 1, 2]
        )
        assert recovery_attempts == 3
        assert (await store.get_plugin_ingress_event(slow_id)).status == "claimed"
        assert not slow.release.is_set()
    finally:
        slow.release.set()
        await processor.shutdown()
        await store.shutdown()


@pytest.mark.asyncio
async def test_slow_connection_does_not_block_other_plugin_processing(tmp_path):
    from magi.events.lifecycle import PluginIngressProcessorModule
    from magi.events.plugin_ingress import PluginIngressHandlerRegistration

    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    registry = PluginIngressRegistry()
    slow, fast = _BlockingHandler(), _RecordingHandler()
    for cid, target, handler in (("slow", "photo", slow), ("fast", "music", fast)):
        registry.register(cid, "epoch_test", [PluginIngressHandlerRegistration(target, "observed", handler)])
        await store.append_plugin_ingress_event(StoredPluginIngressEventRecord(connection_id=cid, connection_epoch="epoch_test", event_id=0,
            source_kind="desktop", producer="device", plugin_target=target, event_type="observed", occurred_at_ms=1))
    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store
    processor = PluginIngressProcessorModule(context, registry=registry,
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: "epoch_test"),
        global_clear_pending=AsyncMock(return_value=False), poll_interval_seconds=0.01)
    await processor.init()
    try:
        await asyncio.wait_for(slow.started.wait(), 2)
        for _ in range(100):
            if fast.events: break
            await asyncio.sleep(0.01)
        assert fast.events == [("observed", {})]
        assert not slow.release.is_set()
    finally:
        slow.release.set()
        await processor.shutdown()
        await store.shutdown()


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
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: "epoch_test"),
        registry=ingress_registry([
            PluginIngressHandlerRegistration(
                plugin_target="example_target",
                event_type="example_event",
                handler=handler,
            )
        ]),
        poll_interval_seconds=0.01,
        global_clear_pending=AsyncMock(return_value=False),
    )
    await processor.init()

    try:
        event_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                connection_id="conn_test", connection_epoch="epoch_test",
                event_id=0,
                source_kind="desktop",
                producer="example_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=1_711_523_200_000,
                payload_json='{"foo":"bar"}',
                created_at_ms=1_711_523_200_050,
            )
        )

        processed = None
        for _ in range(100):
            processed = await store.get_plugin_ingress_event(event_id)
            if handler.events and processed is not None and processed.status == "completed":
                break
            await asyncio.sleep(0.02)

        assert handler.events == [
            (
                "example_event",
                {"foo": "bar"},
            )
        ]
        assert processed is not None
        assert processed.status == "completed"
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
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: "epoch_test"),
        registry=ingress_registry([
            PluginIngressHandlerRegistration(
                plugin_target="example_target",
                event_type="example_event",
                handler=_FailingHandler(),
            )
        ]),
        poll_interval_seconds=0.01,
        global_clear_pending=AsyncMock(return_value=False),
    )
    await processor.init()

    try:
        event_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                connection_id="conn_test", connection_epoch="epoch_test",
                event_id=0,
                source_kind="desktop",
                producer="example_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=1_711_523_200_000,
                payload_json='{"foo":"bar"}',
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
        assert "cannot process example_event" in failed.last_error
    finally:
        await processor.shutdown()
        await store.shutdown()


@pytest.mark.asyncio
async def test_plugin_ingress_clear_waits_for_claimed_handler_and_deletes_result(
    tmp_path: Path,
) -> None:
    from magi.events.plugin_ingress import PluginIngressHandlerRegistration
    from magi.events.lifecycle import PluginIngressProcessorModule

    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    private_marker = "magi-plugin-ingress-private-marker-that-must-not-survive"
    await store.initialize()
    handler = _BlockingHandler()
    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store
    processor = PluginIngressProcessorModule(
        context,
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: "epoch_test"),
        registry=ingress_registry([
            PluginIngressHandlerRegistration(
                plugin_target="example_target",
                event_type="example_event",
                handler=handler,
            )
        ]),
        poll_interval_seconds=0.01,
        global_clear_pending=AsyncMock(return_value=False),
    )
    await processor.init()
    processor_stopped = False

    try:
        event_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                connection_id="conn_test", connection_epoch="epoch_test",
                event_id=0,
                source_kind="desktop",
                producer="example_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=1_711_523_200_000,
                payload_json=f'{{"private":"{private_marker}"}}',
            )
        )
        await handler.started.wait()
        boundary_entered = asyncio.Event()

        async def clear_ingress() -> None:
            async with store.plugin_ingress_global_clear_boundary():
                boundary_entered.set()

        clear_task = asyncio.create_task(clear_ingress())
        await asyncio.sleep(0)
        assert boundary_entered.is_set() is False

        handler.release.set()
        await clear_task

        assert await store.get_plugin_ingress_event(event_id) is None
        await processor.shutdown()
        processor_stopped = True
        assert_sqlite_fragment_absent(store.db_path, private_marker)
    finally:
        if not processor_stopped:
            await processor.shutdown()
        await store.shutdown()


@pytest.mark.asyncio
async def test_plugin_ingress_processor_discards_queue_while_global_clear_pending(
    tmp_path: Path,
) -> None:
    from magi.events.plugin_ingress import PluginIngressHandlerRegistration
    from magi.events.lifecycle import PluginIngressProcessorModule

    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    handler = _RecordingHandler()
    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store
    processor = PluginIngressProcessorModule(
        context,
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: "epoch_test"),
        registry=ingress_registry([
            PluginIngressHandlerRegistration(
                plugin_target="example_target",
                event_type="example_event",
                handler=handler,
            )
        ]),
        poll_interval_seconds=0.01,
        global_clear_pending=AsyncMock(return_value=True),
    )
    await processor.init()

    try:
        event_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                connection_id="conn_test", connection_epoch="epoch_test",
                event_id=0,
                source_kind="desktop",
                producer="example_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=1_711_523_200_000,
                payload_json='{"private":"old"}',
            )
        )
        for _ in range(100):
            if await store.get_plugin_ingress_event(event_id) is None:
                break
            await asyncio.sleep(0.01)

        assert await store.get_plugin_ingress_event(event_id) is None
        assert handler.events == []
    finally:
        await processor.shutdown()
        await store.shutdown()
