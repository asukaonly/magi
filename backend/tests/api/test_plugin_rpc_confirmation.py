"""Lost replies, competing callers and worker replacement cannot duplicate mutations."""

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from _shared.db_schema import apply_chain_schema
from magi.api.services import plugin_rpc
from magi.api.routers import plugins_core_routes
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.runtime_trace import RuntimeTraceStore


def identity():
    return f"{int(time.time() * 1000)}-{uuid4()}"


@pytest.fixture
async def runtime(tmp_path, monkeypatch):
    path = tmp_path / "runtime_trace.db"
    apply_chain_schema("runtime_trace", path)
    store = RuntimeTraceStore(db_path=str(path))
    container = SimpleNamespace(runtime_trace_store=lambda: store)
    monkeypatch.setenv("MAGI_DATA_EPOCH", "epoch")
    monkeypatch.setattr(plugin_rpc, "get_container", lambda: container)
    monkeypatch.setattr(plugins_core_routes, "get_container", lambda: container)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    router = APIRouter(route_class=plugin_rpc.ConfirmedPluginRpcRoute)

    @router.post("/{plugin_id}/connections", status_code=201)
    async def create(plugin_id: str):
        calls.append(plugin_id)
        started.set()
        await release.wait()
        return {"connection_id": "conn_result"}

    app = FastAPI()
    app.include_router(_build_public_router(router, _PUBLIC_ROUTE_METHODS["plugins"]), prefix="/api/plugins")
    receipt_paths = {path: methods for path, methods in _PUBLIC_ROUTE_METHODS["plugins"].items()
                     if path.startswith("/requests/")}
    app.include_router(_build_public_router(plugins_core_routes.plugins_core_router,
                                           receipt_paths), prefix="/api/plugins")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test",
                           headers={"x-magi-client-id": "device-a", "x-magi-data-epoch": "epoch"}) as client:
        yield SimpleNamespace(client=client, store=store, started=started, release=release, calls=calls, container=container)


@pytest.mark.asyncio
async def test_lost_response_and_duplicate_in_flight_are_confirmable(runtime):
    r = runtime
    oid = identity()
    headers = {"x-magi-request-id": oid}
    pending = asyncio.create_task(r.client.post("/api/plugins/photos/connections", json={}, headers=headers))
    await r.started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    duplicate = await r.client.post("/api/plugins/photos/connections", json={}, headers=headers)
    assert duplicate.status_code == 202
    assert duplicate.json()["state"] == "running"
    r.release.set()
    for _ in range(100):
        receipt = (await r.client.get(f"/api/plugins/requests/{oid}")).json()
        if receipt["state"] == "completed":
            break
        await asyncio.sleep(0.01)
    assert receipt["http_status"] == 201
    assert receipt["result"] == {"connection_id": "conn_result"}
    replay = await r.client.post("/api/plugins/photos/connections", json={}, headers=headers)
    assert replay.status_code == 201 and replay.json() == receipt["result"]
    assert r.calls == ["photos"]
    wrong_body = await r.client.post("/api/plugins/photos/connections", json={"changed": True}, headers=headers)
    assert wrong_body.status_code == 409
    assert (await r.client.get(f"/api/plugins/requests/{oid}", headers={"x-magi-client-id": "device-b"})).status_code == 404


@pytest.mark.asyncio
async def test_worker_replacement_returns_uncertain_without_restarting_an_attempt(runtime):
    r = runtime
    oid = identity()
    admitted, _ = await r.store.claim_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        fingerprint="same", issued_at_ms=int(time.time() * 1000), connection_id="conn_result")
    assert admitted
    replacement = RuntimeTraceStore(db_path=r.store.db_path)
    admitted, receipt = await replacement.claim_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        fingerprint="same", issued_at_ms=int(time.time() * 1000), connection_id="conn_result")
    assert not admitted and receipt["state"] == "uncertain"


@pytest.mark.asyncio
async def test_clear_erases_results_but_preserves_non_replayable_identity(runtime):
    r = runtime
    oid = identity()
    await r.store.claim_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        fingerprint="same", issued_at_ms=int(time.time() * 1000), connection_id="conn_result")
    await r.store.finish_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        http_status=200, result={"private": "result"}, connection_id="conn_result")
    await r.store.forget_connection_rpc_results("conn_result")
    receipt = await r.store.read_plugin_rpc("device-a", "epoch", oid)
    assert receipt["state"] == "uncertain" and receipt["result"] is None
    admitted, _ = await r.store.claim_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        fingerprint="same", issued_at_ms=int(time.time() * 1000), connection_id="conn_result")
    assert not admitted


@pytest.mark.asyncio
async def test_identity_epoch_and_expiry_reject_before_execution(runtime):
    for headers in ({}, {"x-magi-request-id": identity(), "x-magi-data-epoch": "old"},
                    {"x-magi-request-id": f"{int(time.time() * 1000) - 86400001}-{uuid4()}"}):
        response = await runtime.client.post("/api/plugins/photos/connections", json={}, headers=headers)
        assert response.status_code == 409
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_expired_unadmitted_request_can_be_explicitly_closed(runtime):
    oid = f"{int(time.time() * 1000) - 8 * 86400000}-{uuid4()}"
    receipt = await runtime.client.get(f"/api/plugins/requests/{oid}")
    assert receipt.status_code == 200
    assert receipt.json()["state"] == "expired"
    response = await runtime.client.post(f"/api/plugins/requests/{oid}/resolve", json={"operator_reviewed": True})
    assert response.status_code == 200
    assert response.json()["http_status"] == 409
    assert response.json()["result"]["code"] == "request_resolved"
    assert runtime.calls == []
    delayed = await runtime.client.post("/api/plugins/photos/connections", json={}, headers={"x-magi-request-id": oid})
    assert delayed.status_code == 409


@pytest.mark.asyncio
async def test_resolution_requires_review_and_refuses_live_attempt(runtime):
    oid = identity()
    pending = asyncio.create_task(runtime.client.post("/api/plugins/photos/connections", json={}, headers={"x-magi-request-id": oid}))
    await runtime.started.wait()
    try:
        path = f"/api/plugins/requests/{oid}/resolve"
        assert (await runtime.client.post(path, json={})).status_code == 422
        assert (await runtime.client.post(path, json={"operator_reviewed": False})).status_code == 422
        assert (await runtime.client.post(path, json={"operator_reviewed": True})).status_code == 409
    finally:
        runtime.release.set()
        await pending
    result = await runtime.client.post(path, json={"operator_reviewed": True})
    assert result.status_code == 200 and result.json()["http_status"] == 201
    assert result.json()["result"] == {"connection_id": "conn_result"}


@pytest.mark.asyncio
async def test_uncertain_request_resolution_fences_delayed_original_and_retains_scope(runtime):
    oid = identity()
    await runtime.store.claim_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        fingerprint="original", issued_at_ms=int(time.time() * 1000), connection_id="conn_result")
    runtime.store.rpc_active.clear()
    path = f"/api/plugins/requests/{oid}/resolve"
    assert (await runtime.client.post(path, json={"operator_reviewed": True},
                                      headers={"x-magi-data-epoch": "replaced"})).status_code == 409
    response = await runtime.client.post(path, json={"operator_reviewed": True})
    assert response.status_code == 200 and response.json()["http_status"] == 409
    admitted, receipt = await runtime.store.claim_plugin_rpc(client_id="device-a", epoch="epoch", operation_id=oid,
        fingerprint="original", issued_at_ms=int(time.time() * 1000), connection_id="conn_result")
    assert not admitted and receipt["state"] == "completed" and receipt["http_status"] == 409
    assert (await runtime.client.get(f"/api/plugins/requests/{oid}", headers={"x-magi-client-id": "device-b"})).status_code == 404


@pytest.mark.asyncio
async def test_closing_unadmitted_identity_prevents_delayed_admission(runtime):
    oid = identity()
    response = await runtime.client.post(f"/api/plugins/requests/{oid}/resolve", json={"operator_reviewed": True})
    assert response.status_code == 200
    delayed = await runtime.client.post("/api/plugins/photos/connections", json={}, headers={"x-magi-request-id": oid})
    assert delayed.status_code == 409
    assert runtime.calls == []
