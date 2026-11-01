import json
from uuid import uuid4

import httpx
import pytest
from magi.collector.queue import CollectorQueue
from magi.collector.transport import CollectorTransport, validate_address, CollectorRejected
from magi_plugin_sdk.runtime import SourceChange, SourceChangeBatch


def scope():
    return {"server_id": str(uuid4()), "data_epoch": str(uuid4()), "connection_id": "conn_" + uuid4().hex,
            "connection_epoch": str(uuid4()), "capability": {'capability_id': 'git_activity.observe', 'protocol': 'source.change.v1', 'schema_id': 'git_activity.session', 'schema_version': 1, 'direction': 'observe', 'supports_resources': False, 'payload_schema': {'type': 'object'}}, "source_type": "git_activity"}


def batch():
    return SourceChangeBatch(changes=[SourceChange(object_id="commit:one", version="1", payload={"text": "commit"})], next_cursor="next")


def test_queue_full_does_not_advance_checkpoint_and_restart_keeps_identity(tmp_path):
    value = scope()
    queue = CollectorQueue(tmp_path / "queue.db", value)
    queue.MAX_ROWS = 1
    queue.append(batch(), value)
    original = json.loads(queue.head()["event"])
    with pytest.raises(BufferError):
        queue.append(SourceChangeBatch(changes=[SourceChange(object_id="two", version="1", payload={})], next_cursor="lost"), value)
    assert queue.state()["checkpoint"] == "next"
    queue.close()
    queue = CollectorQueue(tmp_path / "queue.db", value)
    assert json.loads(queue.head()["event"]) == original
    queue.acknowledge(1)
    queue.append(SourceChangeBatch(changes=[SourceChange(object_id="two", version="1", payload={})]), value)
    assert queue.head()["sequence"] == 2
    queue.close()
    with pytest.raises(ValueError, match="identity"):
        CollectorQueue(tmp_path / "queue.db", {**value, "data_epoch": str(uuid4())})


@pytest.mark.asyncio
async def test_lost_ack_replays_same_event_and_only_valid_receipt_removes_it(tmp_path):
    value = scope()
    queue = CollectorQueue(tmp_path / "queue.db", value)
    queue.append(batch(), value)
    seen = []
    transport = CollectorTransport("http://127.0.0.1:19999", {})
    transport.session, transport.expires_at = "test", float("inf")

    async def serve(request):
        assert request.url.path == "/api/delivery/events"
        body = json.loads(request.content)
        seen.append(body["events"][0])
        if len(seen) == 1:
            raise httpx.ReadError("Response lost")
        return httpx.Response(200, json={"server_id": value["server_id"], "data_epoch": value["data_epoch"],
                    "receipts": [{"event_id": seen[-1]["event_id"], "status": "accepted", "code": "accepted"}]})

    await transport.client.aclose()
    transport.client = httpx.AsyncClient(base_url="http://127.0.0.1:19999/api", transport=httpx.MockTransport(serve))
    assert not await transport.deliver(queue, value)
    assert queue.status()["pending"] == 1
    queue.recover()
    assert await transport.deliver(queue, value)
    assert seen[0] == seen[1]
    assert queue.status()["pending"] == 0
    await transport.close()
    queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "revoked",
        "malformed",
        "wrong-event",
        "wrong-server",
        "wrong-epoch",
        "missing-receipt",
        "invalid-status",
        "accepted-wrong-code",
        "server-error",
    ],
)
async def test_invalid_delivery_receipts_preserve_exact_queued_event(tmp_path, fault):
    value = scope()
    path = tmp_path / "queue.db"
    queue = CollectorQueue(path, value)
    queue.append(batch(), value)
    original = dict(queue.head())
    event = json.loads(original["event"])
    transport = CollectorTransport("http://localhost", {})
    transport.session, transport.expires_at = "test", float("inf")
    receipt = {"event_id": event["event_id"], "status": "accepted", "code": "accepted"}
    response = {
        "server_id": value["server_id"],
        "data_epoch": value["data_epoch"],
        "receipts": [receipt],
    }
    if fault == "wrong-event":
        receipt["event_id"] = str(uuid4())
    if fault == "wrong-server":
        response["server_id"] = str(uuid4())
    if fault == "wrong-epoch":
        response["data_epoch"] = str(uuid4())
    if fault == "missing-receipt":
        response["receipts"] = []
    if fault == "invalid-status":
        receipt["status"] = "unknown"
    if fault == "accepted-wrong-code":
        receipt["code"] = "not-accepted"
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if fault == "revoked":
            return httpx.Response(403)
        if fault == "server-error":
            return httpx.Response(500)
        if fault == "malformed":
            return httpx.Response(200, content=b"{invalid")
        return httpx.Response(200, json=response)

    await transport.client.aclose()
    transport.client = httpx.AsyncClient(
        base_url="http://localhost/api", transport=httpx.MockTransport(respond)
    )
    try:
        if fault in {"revoked", "wrong-server", "wrong-epoch"}:
            with pytest.raises(CollectorRejected):
                await transport.deliver(queue, value)
        else:
            assert await transport.deliver(queue, value) is False
        assert len(requests) == 1 and requests[0]["events"] == [event]
        assert queue.status()["pending"] == 1
    finally:
        await transport.close()
        queue.close()
    reopened = CollectorQueue(path, value)
    try:
        reopened.recover()
        assert reopened.head()["event"] == original["event"]
        assert reopened.head()["sequence"] == original["sequence"]
    finally:
        reopened.close()


@pytest.mark.parametrize("address", ["http://192.168.1.1:9000", "https://user:pass@example.com", "https://example.com?token=1", "file:///etc/passwd"])
def test_collector_rejects_unsafe_addresses(address):
    with pytest.raises(ValueError):
        validate_address(address)


def test_collector_lease_survives_host_exit_until_plugin_supervisor_releases_it(tmp_path):
    import os
    from magi.collector.cli import instance
    from magi.utils.worker_instance import duplicate_worker_lease
    if os.name != "posix":
        pytest.skip("Unix collector lease")
    with instance(tmp_path):
        inherited = duplicate_worker_lease()
        assert inherited is not None
    try:
        with pytest.raises(RuntimeError, match="already owns"):
            with instance(tmp_path):
                pass
    finally:
        os.close(inherited)
    with instance(tmp_path):
        pass


@pytest.mark.asyncio
async def test_long_outage_remains_retryable_and_resumes_without_manual_reset(tmp_path, monkeypatch):
    value = scope()
    queue = CollectorQueue(tmp_path / "queue.db", value)
    queue.append(batch(), value)
    clock = [1_000.0]
    monkeypatch.setattr("magi.collector.queue.time.time", lambda: clock[0])
    transport = CollectorTransport("http://localhost", {})
    transport.session, transport.expires_at = "test", float("inf")
    requests = []

    def respond(request):
        event = json.loads(request.content)["events"][0]
        requests.append(event)
        if len(requests) <= 20:
            raise httpx.ConnectError("Offline", request=request)
        return httpx.Response(200, json={"server_id": value["server_id"], "data_epoch": value["data_epoch"],
            "receipts": [{"event_id": event["event_id"], "status": "accepted", "code": "accepted"}]})

    await transport.client.aclose()
    transport.client = httpx.AsyncClient(base_url="http://localhost/api", transport=httpx.MockTransport(respond))
    try:
        for _ in range(20):
            assert not await transport.deliver(queue, value)
            assert queue.status()["failed"] == 0
            clock[0] += 301
        assert await transport.deliver(queue, value)
        assert queue.status()["pending"] == 0
        assert all(event == requests[0] for event in requests)
    finally:
        await transport.close()
        queue.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "identity", "schema", "claim-generation", "owner"])
async def test_scope_negotiates_data_contract_without_package_version(fault):
    from magi.core.device_models import CollectionCapability
    value = scope()
    declaration = CollectionCapability.model_validate(value["capability"])
    transport = CollectorTransport("http://127.0.0.1:19999", {"server_id": value["server_id"], "client_id": "device"})
    transport.session, transport.expires_at = "test", float("inf")
    requested = []

    async def serve(request):
        requested.append(request)
        if request.url.path == "/api/server/info":
            return httpx.Response(200, json={"server_id": value["server_id"], "protocol_version": 3,
                "maintenance": {"data_epoch": value["data_epoch"]}})
        response = {key: value[key] for key in ("connection_id", "connection_epoch", "source_type", "capability")}
        response["claimed_by"] = "other" if fault == "owner" else "device"
        if fault == "identity":
            response["capability"] = {**value["capability"], "schema_version": 2}
        if fault == "schema":
            response["capability"] = {**value["capability"], "payload_schema": {"type": "string"}}
        if request.method == "POST":
            assert json.loads(request.content) == {**declaration.identity().model_dump(mode="json"), "connection_epoch": value["connection_epoch"]}
            if fault == "claim-generation":
                response["connection_epoch"] = str(uuid4())
        return httpx.Response(200, json=response)

    await transport.client.aclose()
    transport.client = httpx.AsyncClient(base_url="http://127.0.0.1:19999/api", transport=httpx.MockTransport(serve))
    try:
        if fault is None:
            assert await transport.scope(value["connection_id"], {"git_activity": declaration}, claim=True) == value
            assert len(requested) == 3
        else:
            with pytest.raises(CollectorRejected):
                await transport.scope(value["connection_id"], {"git_activity": declaration}, claim=True)
    finally:
        await transport.close()


def test_invalid_observation_keeps_checkpoint_and_entire_batch(tmp_path):
    from jsonschema import ValidationError
    value = scope()
    value["capability"]["payload_schema"] = {"type": "object", "required": ["text"]}
    queue = CollectorQueue(tmp_path / "queue.db", value)
    try:
        original = queue.state()["checkpoint"]
        with pytest.raises(ValidationError):
            queue.append(SourceChangeBatch(changes=[batch().changes[0], SourceChange(object_id="invalid", version="1")], next_cursor="lost"), value)
        assert queue.state()["checkpoint"] == original
        assert queue.status()["pending"] == 0
    finally:
        queue.close()
