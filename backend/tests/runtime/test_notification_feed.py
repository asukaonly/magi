"""The trace owner bounds and converts notification feed records."""
import json
from contextlib import closing
from dataclasses import asdict
import sqlite3
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from magi.ipc import notification_handler
from magi.runtime_trace.store import RuntimeTraceStore
from magi.runtime_trace.contracts import RuntimeNotificationRecord


@pytest.fixture
def feed(tmp_path, ensure_db_schema):
    path = tmp_path / "trace.db"
    ensure_db_schema("runtime_trace", str(path))
    return RuntimeTraceStore(db_path=str(path)), path


@pytest.mark.asyncio
async def test_cursor_reset_bounded_batches_and_authoritative_routing(feed):
    store, path = feed
    assert (await store.read_notification_feed(after_id=None)).reset
    for _ in range(201):
        await store.append_notification(RuntimeNotificationRecord(0, "chat_message_upserted", "owner", "session", payload_json='{"user_id":"spoof","session_id":"spoof","turn_id":"spoof"}'))
    first = await store.read_notification_feed(after_id=0)
    assert len(first.events) == 200 and first.next_id == 200 and not first.reset
    assert first.events[0].data == {"user_id": "owner", "session_id": "session"}
    assert len((await store.read_notification_feed(after_id=first.next_id)).events) == 1
    assert (await store.read_notification_feed(after_id=None)).next_id == 201
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DELETE FROM runtime_notifications")
        conn.commit()
    assert (await store.read_notification_feed(after_id=201)).reset


@pytest.mark.asyncio
async def test_bad_payloads_advance_cursor_as_resync_events(feed):
    store, _ = feed
    for payload in ['x' * 70000, 'not-json', '[]', '{"a":NaN}', '{"a":1e309}', '{"a":' * 70 + '0' + '}' * 70]:
        await store.append_notification(RuntimeNotificationRecord(0, "event", "u", "s", payload_json=payload))
    result = await store.read_notification_feed(after_id=0)
    assert result.next_id == 6
    assert all(event.data is None for event in result.events)


@pytest.mark.asyncio
async def test_payload_budget_bounds_serialized_ipc_and_continues(feed, monkeypatch):
    store, _ = feed
    for _ in range(25):
        await store.append_notification(RuntimeNotificationRecord(0, "event", "u", "s", payload_json=json.dumps({"content": "x" * 60000})))
    result = await store.read_notification_feed(after_id=0)
    assert 0 < len(result.events) < 25
    assert len(json.dumps(asdict(result)).encode()) < 2 * 1024 * 1024
    rest = await store.read_notification_feed(after_id=result.next_id)
    assert len(result.events) + len(rest.events) == 25
    monkeypatch.setattr(notification_handler, "get_api_runtime_dependencies", lambda: SimpleNamespace(runtime_trace_store=store))
    assert (await notification_handler.read_notifications({"after_id": 25}))["events"] == []
    with pytest.raises(ValidationError):
        await notification_handler.read_notifications({"after_id": -1})
    with pytest.raises(ValidationError):
        await notification_handler.read_notifications({"after_id": 1, "path": "/private"})


@pytest.mark.asyncio
async def test_notification_feed_is_registered_as_private_read(feed, monkeypatch):
    from fastapi import FastAPI
    from magi.ipc.protocol import IpcRequest
    from magi.ipc.server import IpcServer, _is_read
    store, _ = feed
    monkeypatch.setattr(notification_handler, "get_api_runtime_dependencies", lambda: SimpleNamespace(runtime_trace_store=store))
    request = IpcRequest(id="feed", method="runtime.notifications", params={"after_id": None})
    server = IpcServer(auth_token="internal-secret", asgi_app=FastAPI())
    assert _is_read(request)
    assert await server._dispatcher.dispatch_request(request) == {"next_id": 0, "reset": True, "events": []}
