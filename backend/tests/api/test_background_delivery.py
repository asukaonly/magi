from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from magi.api.routers import delivery
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.events.plugin_ingress import PluginIngressHandlerRegistration, PluginIngressRegistry
from magi.runtime_trace import RuntimeTraceStore


CONNECTION = "conn_" + "1" * 32
EPOCH = str(uuid4())


class Handler:
    async def handle_event(self, event, payload):
        pass


@pytest.mark.asyncio
async def test_committed_restore_retires_old_inbox_work_before_recovering_claims(receiver):
    client, store, _ = receiver
    old = batch(event())
    await client.post("/api/delivery/events", json=old)
    claimed = await store.claim_next_plugin_ingress_event(consumer_name="crashed")
    new = batch(event(stream="new", value="after restore"))
    await client.post("/api/delivery/events", json=new)
    await store.recover_background_delivery_claims(data_epoch=new["data_epoch"])
    assert await store.get_plugin_ingress_event(claimed.event_id) is None
    current = await store.claim_next_plugin_ingress_event(consumer_name="new worker")
    assert json.loads(current.payload_json) == {"value": "after restore"}
    assert await store.claim_next_plugin_ingress_event(consumer_name="new worker") is None


@pytest.mark.asyncio
async def test_restore_verification_holds_inbox_without_discarding_rollback_work(
    receiver, monkeypatch
):
    from unittest.mock import AsyncMock
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.events.lifecycle import PluginIngressProcessorModule

    client, store, registry = receiver
    body = batch(event())
    await client.post("/api/delivery/events", json=body)
    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store
    processor = PluginIngressProcessorModule(
        context,
        global_clear_pending=AsyncMock(return_value=False),
        registry=registry,
        connection_store=SimpleNamespace(ingress_epoch=lambda cid: EPOCH),
        poll_interval_seconds=0.01,
    )
    monkeypatch.setenv("MAGI_MEMORY_RESTORE_OPERATION_ID", str(uuid4()))
    await processor.init()
    assert processor._task is None and not processor._delivery_registry.ready
    assert (await store.background_delivery_status())["pending"] == 1
    # A failed restore returns to the old committed epoch, keeping its accepted work.
    monkeypatch.delenv("MAGI_MEMORY_RESTORE_OPERATION_ID")
    monkeypatch.setenv("MAGI_DATA_EPOCH", body["data_epoch"])
    await processor.init()
    try:
        for _ in range(100):
            if (await store.background_delivery_status())["pending"] == 0:
                break
            await asyncio.sleep(0.01)
        assert (await store.background_delivery_status()) == {"pending": 0, "failed": 0, "streams": [], "truncated": False}
    finally:
        await processor.shutdown()


def event(stream="photos", sequence=1, value="photo"):
    return {
        "event_id": str(uuid4()),
        "stream": stream,
        "sequence": sequence,
        "occurred_at_ms": 1,
        "payload": {
            "kind": "plugin_event",
            "connection_id": CONNECTION, "connection_epoch": EPOCH,
            "plugin_target": "photos",
            "event_type": "observed.v1",
            "data": {"value": value},
        },
    }


def batch(*events):
    return {
        "server_id": str(uuid4()),
        "data_epoch": str(uuid4()),
        "producer_id": str(uuid4()),
        "events": list(events),
    }


@pytest.fixture
async def receiver(tmp_path, monkeypatch):
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    registry = PluginIngressRegistry()
    registry.ready = True
    registry.register(CONNECTION, EPOCH, [PluginIngressHandlerRegistration(
        "photos", "observed.v1", Handler(), replay_safe=True
    )])
    monkeypatch.setattr(
        delivery,
        "get_container",
        lambda: SimpleNamespace(
            runtime_trace_store=lambda: store, plugin_ingress_registry=lambda: registry,
            plugin_manager=lambda: SimpleNamespace(connection_store=SimpleNamespace(ingress_epoch=lambda cid: EPOCH)),
        ),
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(delivery.delivery_router, _PUBLIC_ROUTE_METHODS["delivery"]),
        prefix="/api/delivery",
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test", headers={"x-magi-client-id": "device-a"}) as client:
        yield client, store, registry
    await store.shutdown()


@pytest.mark.asyncio
async def test_public_admission_replays_after_lost_ack_without_duplicate_work(receiver):
    client, store, _ = receiver
    body = batch(event())
    first = await client.post("/api/delivery/events", json=body)
    assert first.status_code == 200
    assert first.json()["receipts"][0]["status"] == "accepted"
    second = await client.post("/api/delivery/events", json=body)
    assert second.json() == first.json()
    claimed = await store.claim_next_plugin_ingress_event(consumer_name="test")
    assert json.loads(claimed.payload_json) == {"value": "photo"}
    assert await store.claim_next_plugin_ingress_event(consumer_name="test") is None
    await store.complete_plugin_ingress_event(claimed.event_id)
    third = await client.post("/api/delivery/events", json=body)
    assert third.json() == first.json()
    assert await store.claim_next_plugin_ingress_event(consumer_name="test") is None


@pytest.mark.asyncio
async def test_partial_rejection_identity_conflict_and_sequence_checks(receiver):
    client, store, _ = receiver
    bad = event("unsupported")
    bad["payload"]["event_type"] = "unknown"
    body = batch(event(), bad)
    response = (await client.post("/api/delivery/events", json=body)).json()
    assert [r["status"] for r in response["receipts"]] == ["accepted", "rejected"]
    modified = deepcopy(body)
    modified["events"][0]["payload"]["data"]["value"] = "changed"
    assert (await client.post("/api/delivery/events", json=modified)).json()["receipts"][0][
        "code"
    ] == "event_identity_conflict"
    modified["events"][0] = event(sequence=1)
    assert (await client.post("/api/delivery/events", json=modified)).json()["receipts"][0][
        "code"
    ] == "stream_sequence_conflict"
    assert (await client.get("/api/delivery/status")).json()["pending"] == 1


@pytest.mark.asyncio
async def test_concurrent_replay_commits_one_receipt_and_one_work_item(receiver):
    client, store, _ = receiver
    body = batch(event())
    results = await asyncio.gather(
        *(client.post("/api/delivery/events", json=body) for _ in range(6))
    )
    assert all(
        r.status_code == 200 and r.json()["receipts"][0]["status"] == "accepted" for r in results
    )
    assert (await store.background_delivery_status())["pending"] == 1


@pytest.mark.asyncio
async def test_restart_retry_order_quarantine_and_clear(receiver):
    client, store, _ = receiver
    body = batch(event())
    await client.post("/api/delivery/events", json=body)
    first = await store.claim_next_plugin_ingress_event(consumer_name="crashed")
    body["events"] = [event(sequence=2), event(stream="music")]
    await client.post("/api/delivery/events", json=body)
    await store.recover_background_delivery_claims(data_epoch=body["data_epoch"])
    replay = await store.claim_next_plugin_ingress_event(consumer_name="restarted")
    assert replay.event_id == first.event_id
    await store.retry_background_delivery(replay.event_id)
    # The second photo is blocked, while an independent stream progresses.
    other = await store.claim_next_plugin_ingress_event(consumer_name="restarted")
    assert other.cursor_key == "music"
    await store.complete_plugin_ingress_event(other.event_id)
    assert await store.claim_next_plugin_ingress_event(consumer_name="restarted") is None
    for _ in range(9):
        await store.retry_background_delivery(first.event_id)
    assert (await store.background_delivery_status())["failed"] == 1
    assert (await client.post("/api/delivery/retry", json={})).status_code == 200
    assert (
        await store.claim_next_plugin_ingress_event(consumer_name="restarted")
    ).event_id == first.event_id
    async with store.plugin_ingress_global_clear_boundary():
        pass
    assert (await store.background_delivery_status()) == {"pending": 0, "failed": 0, "streams": [], "truncated": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["empty", "duplicate", "unknown", "large", "command"])
async def test_invalid_batches_never_enter_the_queue(receiver, change):
    client, store, _ = receiver
    body = batch(event())
    if change == "empty":
        body["events"] = []
    elif change == "duplicate":
        body["events"].append(body["events"][0])
    elif change == "unknown":
        body["secret"] = "no"
    elif change == "large":
        body["events"][0]["payload"]["data"] = {"value": "x" * 65536}
    else:
        body["events"][0]["payload"] = {"kind": "execute_tool", "command": "delete"}
    assert (await client.post("/api/delivery/events", json=body)).status_code == 422
    assert (await store.background_delivery_status())["pending"] == 0


@pytest.mark.asyncio
async def test_processor_readiness_and_storage_failure_do_not_ack(receiver, monkeypatch):
    client, store, registry = receiver
    body = batch(event())
    registry.ready = False
    assert (await client.post("/api/delivery/events", json=body)).json()["receipts"][0][
        "status"
    ] == "retry"
    registry.ready = True
    import sqlite3
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        store,
        "accept_background_event",
        AsyncMock(side_effect=sqlite3.OperationalError("disk full")),
    )
    result = (await client.post("/api/delivery/events", json=body)).json()["receipts"][0]
    assert result["status"] == "retry" and result["code"] == "storage_unavailable"


@pytest.mark.asyncio
async def test_notification_reads_are_monotonic_and_ack_only_after_persistence(
    receiver, monkeypatch
):
    from unittest.mock import Mock
    import sqlite3

    client, _, _ = receiver
    mark_read = Mock()
    monkeypatch.setattr(
        delivery, "get_notification_store", lambda: SimpleNamespace(mark_read=mark_read)
    )
    body = batch(event())
    body["events"][0]["payload"] = {"kind": "notification_read", "notification_id": 42}
    assert (await client.post("/api/delivery/events", json=body)).json()["receipts"][0][
        "status"
    ] == "accepted"
    mark_read.assert_called_once_with([42])
    mark_read.side_effect = sqlite3.OperationalError("disk full")
    assert (await client.post("/api/delivery/events", json=body)).json()["receipts"][0][
        "status"
    ] == "retry"


@pytest.mark.asyncio
async def test_authenticated_devices_cannot_collide_in_a_producer_stream(receiver):
    client, store, _ = receiver
    body = batch(event())
    for device in ("device-a", "device-b"):
        response = await client.post("/api/delivery/events", json=body, headers={"x-magi-client-id": device})
        assert response.json()["receipts"][0]["status"] == "accepted"
    assert (await store.background_delivery_status())["pending"] == 2


@pytest.mark.asyncio
async def test_clear_fences_unsent_events_and_keeps_other_connection_work(receiver, monkeypatch):
    client, store, registry = receiver
    first = batch(event())
    await client.post("/api/delivery/events", json=first)
    epoch = str(uuid4())
    connection_store = delivery.get_container().plugin_manager().connection_store
    monkeypatch.setattr(delivery, "get_container", lambda: SimpleNamespace(
        runtime_trace_store=lambda: store, plugin_ingress_registry=lambda: registry,
        plugin_manager=lambda: SimpleNamespace(connection_store=connection_store),
    ))
    connection_store.ingress_epoch = lambda cid: epoch
    await store.retire_connection_ingress(CONNECTION)
    replay = await client.post("/api/delivery/events", json=first)
    assert replay.json()["receipts"][0]["code"] == "connection_epoch_changed"
    assert (await store.background_delivery_status())["pending"] == 0
    assert (await client.get(f"/api/delivery/connections/{CONNECTION}")).json()["connection_epoch"] == epoch


@pytest.mark.asyncio
async def test_stream_watermark_compacts_receipts_without_reexecuting_old_positions(receiver):
    import sqlite3
    client, store, _ = receiver
    body = batch(event())
    old = deepcopy(body)
    for sequence in range(1, 31):
        body["events"] = [event(sequence=sequence)]
        assert (await client.post("/api/delivery/events", json=body)).json()["receipts"][0]["status"] == "accepted"
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM background_delivery_receipts").fetchone()[0] == 1
    assert (await client.post("/api/delivery/events", json=old)).json()["receipts"][0]["code"] == "stream_sequence_conflict"
    assert (await client.post("/api/delivery/events", json=body)).json()["receipts"][0]["status"] == "accepted"
    assert (await store.background_delivery_status())["pending"] == 30


@pytest.mark.asyncio
async def test_scoped_recovery_does_not_change_another_device_or_executing_record(receiver):
    client, store, _ = receiver
    body = batch(event())
    for device in ("device-a", "device-b"):
        await client.post("/api/delivery/events", json=body, headers={"x-magi-client-id": device})
    first = await store.claim_next_plugin_ingress_event(consumer_name="test")
    await store.fail_plugin_ingress_event(first.event_id, error_text="permission_required")
    state = (await client.get("/api/delivery/status")).json()
    row = next(r for r in state["streams"] if r["failed"])
    assert row["last_error"] == "permission_required"
    assert row["oldest_at_ms"] > 0 and "payload" not in row
    selection = {k: row[k] for k in ("producer_id", "connection_id", "stream")}
    assert (await client.post("/api/delivery/retry", json=selection)).status_code == 200
    claimed = await store.claim_next_plugin_ingress_event(consumer_name="test")
    assert claimed.event_id == first.event_id
    assert (await client.post("/api/delivery/discard", json=selection)).status_code == 200
    assert (await store.get_plugin_ingress_event(claimed.event_id)).status == "claimed"
    await store.fail_plugin_ingress_event(claimed.event_id, error_text="permission_required")
    await client.post("/api/delivery/discard", json=selection)
    assert await store.get_plugin_ingress_event(claimed.event_id) is None
    assert (await store.background_delivery_status())["pending"] == 1
    assert (await client.post("/api/delivery/events", json=body)).json()["receipts"][0]["status"] == "accepted"
    assert (await store.background_delivery_status())["pending"] == 1


@pytest.mark.asyncio
async def test_claims_serialize_connections_and_reserve_capacity_for_other_plugins(receiver):
    client, store, registry = receiver
    for n, target in ((1, "photos"), (2, "photos"), (3, "photos"), (4, "other")):
        cid = "conn_" + str(n) * 32
        if n != 1:
            registry.register(cid, EPOCH, [PluginIngressHandlerRegistration(target, "observed.v1", Handler(), replay_safe=True)])
        item = event(stream=f"stream{n}")
        item["payload"].update(connection_id=cid, plugin_target=target)
        await client.post("/api/delivery/events", json=batch(item))
    claims = [await store.claim_next_plugin_ingress_event(consumer_name="test") for _ in range(3)]
    assert [c.plugin_target for c in claims] == ["photos", "photos", "other"]
    assert await store.claim_next_plugin_ingress_event(consumer_name="test") is None
    await store.complete_plugin_ingress_event(claims[0].event_id)
    assert (await store.claim_next_plugin_ingress_event(consumer_name="test")).connection_id == "conn_" + "3" * 32


@pytest.mark.asyncio
async def test_permanent_handler_error_is_quarantined_without_secret_text(receiver, monkeypatch):
    from unittest.mock import AsyncMock
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.events.lifecycle import PluginIngressProcessorModule
    client, store, registry = receiver
    monkeypatch.setattr(Handler, "handle_event", AsyncMock(side_effect=PermissionError("private-credential-value")))
    body = batch(event())
    await client.post("/api/delivery/events", json=body)
    monkeypatch.setenv("MAGI_DATA_EPOCH", body["data_epoch"])
    context = RuntimeBootstrapContext()
    context.runtime_trace.store = store
    processor = PluginIngressProcessorModule(context, registry=registry, connection_store=SimpleNamespace(ingress_epoch=lambda cid: EPOCH),
        global_clear_pending=AsyncMock(return_value=False), poll_interval_seconds=0.01)
    await processor.init()
    try:
        for _ in range(100):
            status = await store.background_delivery_status()
            if status["failed"]: break
            await asyncio.sleep(0.01)
        assert status["failed"] == 1
        assert status["streams"][0]["attempts"] == 0
        assert status["streams"][0]["last_error"] == "permission_required"
        assert "private-credential-value" not in json.dumps(status)
    finally:
        await processor.shutdown()


@pytest.mark.asyncio
async def test_collector_routes_use_public_router_and_do_not_expose_center_settings(monkeypatch):
    from unittest.mock import AsyncMock
    scope = SimpleNamespace(metadata={"remote_collection": "source.change.v1"})
    store = SimpleNamespace(get=lambda _: SimpleNamespace(enabled=True, settings={"secret": "private"}),
                            ingress_epoch=lambda _: EPOCH, collector_binding=lambda *_: "device")
    manager = SimpleNamespace(connection_store=store, get_package=lambda _: SimpleNamespace(manifest=SimpleNamespace(version="0.3.2")))
    contributor = SimpleNamespace(claim_collector=AsyncMock())
    monkeypatch.setattr(delivery, "get_container", lambda: SimpleNamespace(plugin_manager=lambda: manager,
        source_registry=lambda: SimpleNamespace(resolve_source=lambda *_, **kwargs: ("git-activity", "source", None, scope)),
        source_scheduler_contrib=lambda: contributor))
    app = FastAPI()
    app.include_router(_build_public_router(delivery.delivery_router, _PUBLIC_ROUTE_METHODS["delivery"]), prefix="/api/delivery")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test", headers={"x-magi-client-id": "device", "x-magi-collector-source": "git_activity"}) as client:
        response = await client.get(f"/api/delivery/collector/{CONNECTION}")
        assert response.status_code == 200
        assert "private" not in response.text and "settings" not in response.text
        invalid = await client.post(f"/api/delivery/collector/{CONNECTION}", json={"plugin_id": "wrong", "plugin_version": "0.3.2"})
        assert invalid.status_code == 409
        contributor.claim_collector.assert_not_awaited()
        valid = await client.post(f"/api/delivery/collector/{CONNECTION}", json={"plugin_id": "git-activity", "plugin_version": "0.3.2"})
        assert valid.status_code == 200
        contributor.claim_collector.assert_awaited_once_with(CONNECTION, "git_activity", "device")
