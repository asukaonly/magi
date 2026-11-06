import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.notifications_routes import build_default_notifications_router
from magi.notifications.actions import materialize_event, notification_target
from magi.notifications.service import NotificationService
from magi.notifications.store import NotificationRow, NotificationStore


def test_inbox_destinations_and_lifecycle(tmp_path):
    store = NotificationStore(tmp_path / "notifications.db")
    store.ensure_schema()
    event = dict(user_id="local_user", session_id="session", payload={"request_id": "question"})
    for _ in range(2):
        assert materialize_event(store, channel="control.ask.requested", **event)
    rows = store.list_for_user("local_user")
    assert len(rows) == 1
    assert notification_target(rows[0]).model_dump() == {"kind": "chat", "id": "session"}
    assert store.push_feed("local_user", None) == {"next_id": rows[0].id, "items": []}
    assert store.push_feed("local_user", 0)["items"][0]["id"] == rows[0].id
    assert materialize_event(store, channel="control.ask.answered", **event)
    assert store.push_feed("local_user", 0)["items"] == []
    assert not materialize_event(store, channel="agent_response_chunk", **event)
    payload = {"task_id": "task", "status": "succeeded", "attempt_index": 1, "spec": {"title": "Research"}}
    assert materialize_event(store, channel="background_task_state_changed", **dict(event, payload=payload))
    assert len(store.push_feed("local_user", 0)["items"]) == 1


def test_feed_expiry_and_public_notification_read(tmp_path):
    store = NotificationStore(tmp_path / "notifications.db")
    store.ensure_schema()
    now = int(time.time() * 1000)
    old = store.insert(NotificationRow(user_id="local_user", kind="personal_task_reminder", dedupe_key="old", title="Private title", body="Private body", created_at_ms=now - 301000))
    live = store.insert(NotificationRow(user_id="local_user", kind="personal_task_reminder", dedupe_key="live", title="Title", body="Body", payload_json=json.dumps({"personal_item_id": "todo"})))
    other = store.insert(NotificationRow(user_id="other", kind="personal_task_reminder", dedupe_key="other", title="Other", body="Other"))
    feed = store.push_feed("local_user", 0)
    assert [item["id"] for item in feed["items"]] == [live]
    assert "Private" not in json.dumps(feed)
    assert feed["next_id"] == live
    service = NotificationService(store=store)
    app = FastAPI()
    router = build_default_notifications_router(service_dep=lambda: service)
    app.include_router(_build_public_router(router, _PUBLIC_ROUTE_METHODS["notifications"]))
    client = TestClient(app)
    assert client.get(f"/notifications/{live}").json()["target"] == {"kind": "task", "id": "todo"}
    assert client.get(f"/notifications/{other}").status_code == 404
    store.mark_dismissed(old, "explicit")
    assert client.get(f"/notifications/{old}").status_code == 404


def test_chat_deletion_removes_only_its_inbox_records(tmp_path):
    from magi.runtime_trace.persistence.chat_cleanup import SqliteTraceContentRepository
    path = tmp_path / "notifications.db"
    store = NotificationStore(path)
    store.ensure_schema()
    for session in ["one", "two"]:
        materialize_event(store, channel="control.ask.requested", user_id="local_user", session_id=session, payload={"request_id": "q"})
    SqliteTraceContentRepository(path).delete_session(user_id="local_user", session_id="one")
    rows = store.list_for_user("local_user")
    assert len(rows) == 1 and notification_target(rows[0]).id == "two"
