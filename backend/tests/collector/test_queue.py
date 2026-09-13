import json
from uuid import uuid4

import httpx
import pytest
from magi.collector.queue import CollectorQueue
from magi.collector.transport import CollectorTransport, validate_address, CollectorRejected
from magi_plugin_sdk.runtime import SourceChange, SourceChangeBatch


def scope():
    return {"server_id": str(uuid4()), "data_epoch": str(uuid4()), "connection_id": "conn_" + uuid4().hex,
            "connection_epoch": str(uuid4()), "plugin_id": "git-activity", "plugin_version": "0.3.2", "source_type": "git_activity"}


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
async def test_bad_ack_and_revoked_credentials_never_remove_events(tmp_path):
    value = scope()
    queue = CollectorQueue(tmp_path / "queue.db", value)
    queue.append(batch(), value)
    transport = CollectorTransport("http://localhost", {})
    transport.session, transport.expires_at = "test", float("inf")
    await transport.client.aclose()
    transport.client = httpx.AsyncClient(base_url="http://localhost/api", transport=httpx.MockTransport(lambda _: httpx.Response(403)))
    with pytest.raises(CollectorRejected):
        await transport.deliver(queue, value)
    assert queue.status()["pending"] == 1
    await transport.close()
    queue.close()


@pytest.mark.parametrize("address", ["http://192.168.1.1:9000", "https://user:pass@example.com", "https://example.com?token=1", "file:///etc/passwd"])
def test_collector_rejects_unsafe_addresses(address):
    with pytest.raises(ValueError):
        validate_address(address)
