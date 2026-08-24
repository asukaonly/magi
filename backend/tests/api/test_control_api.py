"""Tests for the /api/control router."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.control.common import InteractionBroker
from magi.control.permission.contracts import (
    PermissionRule,
    PermissionScope,
)
from magi.control.permission.rules import PermissionRuleStore
from magi.control.session_store import ControlSessionStore
from magi.control.settings import ControlSettings, PermissionMode
from magi.control.settings_manager import ControlSettingsManager
from magi.api.routers import control as control_module
from magi.api.routers.control import control_router
from magi.runtime_trace import RuntimeNotificationRecord


class _FakeRuntimeTraceStore:
    def __init__(self, notifications: list[RuntimeNotificationRecord]) -> None:
        self._notifications = notifications

    async def get_latest_notification_id(self) -> int:
        if not self._notifications:
            return 0
        return max(item.notification_id for item in self._notifications)

    async def list_notifications(self, *, after_id: int, limit: int = 50) -> list[RuntimeNotificationRecord]:
        _ = limit
        return [
            item for item in self._notifications if item.notification_id > after_id
        ]


@pytest.fixture()
async def wiring(monkeypatch):
    manager = ControlSettingsManager(ControlSettings())
    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    broker = InteractionBroker()
    session_store = ControlSessionStore()

    monkeypatch.setattr(control_module, "resolve_control_settings_manager", lambda: manager)
    monkeypatch.setattr(control_module, "resolve_permission_rule_store", lambda: rules)
    monkeypatch.setattr(control_module, "resolve_control_interaction_broker", lambda: broker)
    monkeypatch.setattr(control_module, "resolve_control_session_store", lambda: session_store)

    return {
        "manager": manager,
        "rules": rules,
        "broker": broker,
        "store": session_store,
    }


@pytest.fixture()
def client(wiring):
    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_get_settings_defaults(client):
    resp = client.get("/api/control/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["permission_mode"] == PermissionMode.HIGH_ONLY.value
    assert body["plan_approval_required"] is False


def test_put_settings_updates_mode(client):
    resp = client.put(
        "/api/control/settings", json={"permission_mode": "off"}
    )
    assert resp.status_code == 200
    assert resp.json()["permission_mode"] == "off"

    # Subsequent GET reflects the change.
    again = client.get("/api/control/settings")
    assert again.json()["permission_mode"] == "off"


def test_put_settings_rejects_unknown_mode(client):
    resp = client.put(
        "/api/control/settings", json={"permission_mode": "bogus"}
    )
    assert resp.status_code == 422


def test_session_override_roundtrip(client):
    resp = client.put(
        "/api/control/sessions/sid-1/settings",
        json={"permission_mode": "all"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["override"]["permission_mode"] == "all"
    assert body["effective"]["permission_mode"] == "all"

    # Clearing drops the override.
    cleared = client.put(
        "/api/control/sessions/sid-1/settings", json={"clear": True}
    )
    assert cleared.status_code == 200
    assert cleared.json()["override"] is None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_and_delete_session_rule(wiring):
    rules: PermissionRuleStore = wiring["rules"]
    rule = PermissionRule(
        rule_id="r1",
        tool_name="bash",
        scope=PermissionScope.SESSION,
        matcher={"command": "ls"},
        allow=True,
    )
    await rules.add(rule, session_id="sid-9")

    # Use an inline client; we already have the monkeypatched module-level
    # requires bound to this rules instance.
    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)

    listed = client.get("/api/control/rules?session_id=sid-9").json()["rules"]
    assert len(listed) == 1
    assert listed[0]["rule_id"] == "r1"

    resp = client.delete("/api/control/rules/r1?session_id=sid-9")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": "r1"}

    empty = client.get("/api/control/rules?session_id=sid-9").json()["rules"]
    assert empty == []


def test_delete_missing_rule_returns_404(client):
    resp = client.delete("/api/control/rules/unknown")
    assert resp.status_code == 404


def test_clear_session_rules(client, wiring):
    # Add via the store directly, then call the endpoint.
    import asyncio

    async def _seed():
        await wiring["rules"].add(
            PermissionRule(
                rule_id="rA",
                tool_name="bash",
                scope=PermissionScope.SESSION,
                matcher={},
                allow=True,
            ),
            session_id="sid-x",
        )

    asyncio.get_event_loop().run_until_complete(_seed())
    resp = client.delete("/api/control/rules?session_id=sid-x")
    assert resp.status_code == 200
    assert resp.json()["cleared"] is True
    after = client.get("/api/control/rules?session_id=sid-x").json()["rules"]
    assert after == []


# ---------------------------------------------------------------------------
# Permission + ask respond
# ---------------------------------------------------------------------------


def test_permission_respond_misses_when_no_pending(client):
    resp = client.post(
        "/api/control/permission/does-not-exist/respond",
        json={"outcome": "allow"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_permission_respond_resolves_waiter(wiring):
    broker: InteractionBroker = wiring["broker"]
    import asyncio

    async def waiter() -> dict:
        return await broker.wait(
            interaction_id="req-1", kind="permission", timeout_seconds=5.0
        )

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)  # ensure waiter is registered

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)
    resp = client.post(
        "/api/control/permission/req-1/respond",
        json={"outcome": "allow", "scope": "session"},
    )
    assert resp.status_code == 200
    answer = await waiter_task
    assert answer["outcome"] == "allowed"
    assert answer["scope"] == "session"


@pytest.mark.asyncio
async def test_ask_respond_resolves_waiter(wiring):
    broker: InteractionBroker = wiring["broker"]
    import asyncio

    waiter = asyncio.create_task(
        broker.wait(interaction_id="ask-1", kind="ask", timeout_seconds=5.0)
    )
    await asyncio.sleep(0.05)

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)
    resp = client.post(
        "/api/control/ask/ask-1/respond",
        json={"answer": "sure"},
    )
    assert resp.status_code == 200
    assert await waiter == "sure"


@pytest.mark.asyncio
async def test_choice_only_ask_rejects_free_text_without_consuming_waiter(wiring):
    broker: InteractionBroker = wiring["broker"]
    import asyncio

    waiter = asyncio.create_task(
        broker.wait(
            interaction_id="ask-choice",
            kind="ask",
            timeout_seconds=5.0,
            metadata={
                "allow_free_text": False,
                "options": ["yes", "no"],
            },
        )
    )
    await asyncio.sleep(0.05)

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)
    invalid = client.post(
        "/api/control/ask/ask-choice/respond",
        json={"answer": "maybe"},
    )
    assert invalid.status_code == 400
    assert waiter.done() is False

    valid = client.post(
        "/api/control/ask/ask-choice/respond",
        json={"answer": " yes "},
    )
    assert valid.status_code == 200
    assert await waiter == "yes"


# ---------------------------------------------------------------------------
# Session snapshots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_plan_and_todos_and_ask(wiring):
    store: ControlSessionStore = wiring["store"]
    await store.enter_plan_mode("sid-2")
    await store.mutate_run_plan(
        "sid-2",
        run_id="run-2",
        plan_id=None,
        expected_version=0,
        required=True,
        item_mutations=[{"title": "a"}, {"title": "b", "status": "in_progress"}],
    )
    await store.open_ask(
        "sid-2", question="Proceed?", options=["yes", "no"]
    )

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)
    plan = client.get("/api/control/sessions/sid-2/plan").json()
    assert plan["active"] is True

    todos = client.get("/api/control/sessions/sid-2/todos").json()
    assert todos["plan"]["run_id"] == "run-2"
    assert [t["content"] for t in todos["plan"]["items"]] == ["a", "b"]
    assert all("created_at_ms" in t for t in todos["plan"]["items"])
    assert all("updated_at_ms" in t for t in todos["plan"]["items"])

    ask = client.get("/api/control/sessions/sid-2/ask").json()
    assert ask["ask"]["question"] == "Proceed?"
    assert ask["ask"]["options"] == ["yes", "no"]


def test_session_plan_falls_back_to_runtime_notifications(wiring, monkeypatch):
    monkeypatch.setattr(
        control_module,
        "resolve_runtime_trace_store",
        lambda: _FakeRuntimeTraceStore(
            [
                RuntimeNotificationRecord(
                    notification_id=3,
                    channel="control.plan.updated",
                    user_id="user-1",
                    session_id="sid-fallback",
                    turn_id="turn-1",
                    payload_json=json.dumps(
                        {
                            "session_id": "sid-fallback",
                            "plan": {
                                "active": False,
                                "allowed_tools": [],
                                "plan_text": "Inspect runtime heartbeat path",
                                "entered_at": None,
                            },
                        }
                    ),
                    created_at_ms=123,
                )
            ]
        ),
    )

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)

    plan = client.get("/api/control/sessions/sid-fallback/plan")
    assert plan.status_code == 200
    assert plan.json()["plan_text"] == "Inspect runtime heartbeat path"


def test_session_todos_do_not_restore_from_notification_projection(wiring, monkeypatch):
    monkeypatch.setattr(
        control_module,
        "resolve_runtime_trace_store",
        lambda: _FakeRuntimeTraceStore([]),
    )
    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)

    todos = client.get("/api/control/sessions/sid-empty/todos")
    assert todos.status_code == 200
    assert todos.json() == {"plan": None}


@pytest.mark.asyncio
async def test_get_pending_permissions_filters_by_session(wiring, monkeypatch):
    from magi.control.permission.brokered_prompter import (
        PendingPermissionRegistry,
    )
    from magi.control.permission.contracts import (
        PermissionRequest,
        RiskLevel,
        ToolOrigin,
    )

    registry = PendingPermissionRegistry()
    monkeypatch.setattr(
        control_module,
        "resolve_pending_permission_registry",
        lambda: registry,
    )

    req_a = PermissionRequest(
        request_id="req-a",
        tool_name="bash",
        arguments={"command": "rm file"},
        risk_level=RiskLevel.HIGH,
        origin=ToolOrigin.CHAT,
        agent_id="chat",
        session_id="sid-A",
        turn_id=None,
        workspace=None,
        timeout_seconds=120.0,
    )
    req_a.expires_at = req_a.created_at + 120.0
    req_b = PermissionRequest(
        request_id="req-b",
        tool_name="bash",
        arguments={"command": "ls"},
        risk_level=RiskLevel.MEDIUM,
        origin=ToolOrigin.CHAT,
        agent_id="chat",
        session_id="sid-B",
        turn_id=None,
        workspace=None,
    )
    await registry.add(req_a)
    await registry.add(req_b)

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)

    resp = client.get("/api/control/sessions/sid-A/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["request_id"] for item in body["items"]] == ["req-a"]
    assert body["items"][0]["timeout_seconds"] == 120.0
    assert body["items"][0]["expires_at_ms"] == int(req_a.expires_at * 1000)

    empty = client.get("/api/control/sessions/sid-C/permissions").json()
    assert empty["items"] == []


def test_get_pending_permissions_without_registry_returns_empty(
    wiring, monkeypatch
):
    def _raise():
        raise RuntimeError("no registry")

    monkeypatch.setattr(
        control_module,
        "resolve_pending_permission_registry",
        _raise,
    )

    app = FastAPI()
    app.include_router(control_router, prefix="/api/control")
    client = TestClient(app)
    resp = client.get("/api/control/sessions/sid-x/permissions")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}
