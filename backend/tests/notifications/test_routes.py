from fastapi import FastAPI
from fastapi.testclient import TestClient
from magi.notifications.store import NotificationStore, NotificationRow
from magi.notifications.service import NotificationService
from magi.api.routers.notifications_routes import build_default_notifications_router


def _client(tmp_path):
    store = NotificationStore(str(tmp_path / "n.db"))
    store.ensure_schema()
    store.insert(NotificationRow(user_id="default_user", kind="suggestion",
        dedupe_key="browser_history", title="t", body="b",
        payload_json='{"installable_plugin_ids":["edge-history"]}', created_at_ms=1000))
    svc = NotificationService(store=store)
    app = FastAPI()
    app.include_router(build_default_notifications_router(service_dep=lambda: svc))
    return TestClient(app), store


def test_list(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["unread_count"] == 1
    assert body["items"][0]["dedupe_key"] == "browser_history"
    assert body["items"][0]["payload"]["installable_plugin_ids"] == ["edge-history"]


def test_list_hides_profile_conflicts_while_memory_clear_is_pending(tmp_path):
    store = NotificationStore(str(tmp_path / "n.db"))
    store.ensure_schema()
    store.insert(NotificationRow(
        user_id="default_user",
        kind="suggestion",
        dedupe_key="profile_conflict:identity.name:user",
        title="old conflict",
        body="old evidence",
        payload_json='{"conflict_type":"profile_conflict"}',
        created_at_ms=1000,
    ))
    store.insert(NotificationRow(
        user_id="default_user",
        kind="suggestion",
        dedupe_key="browser_history",
        title="normal",
        body="normal",
        created_at_ms=2000,
    ))
    svc = NotificationService(store=store)

    async def _clear_pending() -> bool:
        return True

    app = FastAPI()
    app.include_router(build_default_notifications_router(
        service_dep=lambda: svc,
        profile_conflict_suppression_dep=_clear_pending,
    ))

    body = TestClient(app).get("/notifications").json()

    assert body["unread_count"] == 1
    assert [item["dedupe_key"] for item in body["items"]] == ["browser_history"]


def test_mark_read_all(tmp_path):
    client, store = _client(tmp_path)
    assert client.post("/notifications/mark-read", json={"all": True}).status_code == 200
    assert store.unread_count("default_user") == 0


def test_dismiss_and_action(tmp_path):
    client, store = _client(tmp_path)
    nid = store.list_for_user("default_user")[0].id
    assert client.post(f"/notifications/{nid}/dismiss", json={}).status_code == 200
    assert store.list_for_user("default_user") == []
    nid2 = store.insert(NotificationRow(user_id="default_user", kind="suggestion",
        dedupe_key="code_activity", title="t", body="b", created_at_ms=2000))
    assert client.post(f"/notifications/{nid2}/action", json={}).status_code == 200
    assert nid2 not in [i.id for i in store.list_for_user("default_user")]


def test_dismiss_all_clears_feed(tmp_path):
    client, store = _client(tmp_path)
    store.insert(NotificationRow(user_id="default_user", kind="suggestion",
        dedupe_key="code_activity", title="t", body="b", created_at_ms=2000))
    assert len(store.list_for_user("default_user")) == 2
    r = client.post("/notifications/dismiss-all", json={})
    assert r.status_code == 200
    assert r.json()["dismissed"] == 2
    assert store.list_for_user("default_user") == []
