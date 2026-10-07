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
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
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
    from magi.core.container import get_container

    manager = ControlSettingsManager(ControlSettings())
    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    broker = InteractionBroker()
    session_store = ControlSessionStore()

    monkeypatch.setattr(control_module, "resolve_permission_rule_store", lambda: rules)
    monkeypatch.setattr(control_module, "resolve_control_interaction_broker", lambda: broker)

    container = get_container()
    with container.control_settings_manager.override(
        manager
    ), container.control_session_store.override(session_store):
        yield {"manager": manager, "rules": rules, "broker": broker, "store": session_store}


@pytest.fixture()
def client(wiring):
    app = FastAPI()
    app.include_router(_build_public_router(control_router, _PUBLIC_ROUTE_METHODS["control"]), prefix="/api/control")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_put_settings_updates_mode(client):
    initial = client.get("/api/control/settings")
    assert initial.status_code == 200
    assert initial.json()["permission_mode"] == PermissionMode.HIGH_ONLY.value
    assert initial.json()["plan_approval_required"] is False
    resp = client.put(
        "/api/control/settings",
        json={
            "permission_mode": "off",
            "revision": client.get("/api/control/settings").json()["revision"],
        },
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
        json={"permission_mode": "all", "revision": client.get("/api/control/sessions/sid-1/settings").json()["revision"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["override"]["permission_mode"] == "all"
    assert body["effective"]["permission_mode"] == "all"

    # Clearing drops the override.
    cleared = client.put(
        "/api/control/sessions/sid-1/settings", json={"clear": True, "revision": body["revision"]}
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


@pytest.mark.asyncio
async def test_clear_session_rules_preserves_other_sessions_and_persistent_rules(client, wiring):
    for rule_id, session_id, scope in [
        ("target", "sid-x", PermissionScope.SESSION),
        ("other", "sid-y", PermissionScope.SESSION),
        ("persistent", None, PermissionScope.PERSISTENT_EXACT),
    ]:
        await wiring["rules"].add(
            PermissionRule(rule_id=rule_id, tool_name="bash", scope=scope, matcher={}, allow=True),
            session_id=session_id,
        )
    assert {
        r["rule_id"] for r in client.get("/api/control/rules?session_id=sid-x").json()["rules"]
    } == {"target", "persistent"}
    response = client.delete("/api/control/rules?session_id=sid-x")
    assert response.status_code == 200
    assert response.json()["cleared"] is True
    assert {
        r["rule_id"] for r in client.get("/api/control/rules?session_id=sid-x").json()["rules"]
    } == {"persistent"}
    assert {
        r["rule_id"] for r in client.get("/api/control/rules?session_id=sid-y").json()["rules"]
    } == {"other", "persistent"}


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
async def test_permission_respond_resolves_waiter(client, wiring):
    broker: InteractionBroker = wiring["broker"]
    import asyncio

    async def waiter() -> dict:
        return await broker.wait(
            interaction_id="req-1", kind="permission", timeout_seconds=5.0
        )

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)  # ensure waiter is registered

    resp = client.post(
        "/api/control/permission/req-1/respond",
        json={"outcome": "allow", "scope": "session"},
    )
    assert resp.status_code == 200
    answer = await waiter_task
    assert answer["outcome"] == "allowed"
    assert answer["scope"] == "session"


@pytest.mark.asyncio
async def test_ask_respond_resolves_waiter(client, wiring):
    broker: InteractionBroker = wiring["broker"]
    import asyncio

    waiter = asyncio.create_task(
        broker.wait(interaction_id="ask-1", kind="ask", timeout_seconds=5.0)
    )
    await asyncio.sleep(0.05)

    resp = client.post(
        "/api/control/ask/ask-1/respond",
        json={"answer": "sure"},
    )
    assert resp.status_code == 200
    assert await waiter == "sure"


@pytest.mark.asyncio
async def test_choice_only_ask_rejects_free_text_without_consuming_waiter(client, wiring):
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
async def test_session_plan_and_ask(client, wiring):
    store: ControlSessionStore = wiring["store"]
    await store.enter_plan_mode("sid-2")
    await store.open_ask(
        "sid-2", question="Proceed?", options=["yes", "no"]
    )

    plan = client.get("/api/control/sessions/sid-2/plan").json()
    assert plan["active"] is True

    ask = client.get("/api/control/sessions/sid-2/ask").json()
    assert ask["ask"]["question"] == "Proceed?"
    assert ask["ask"]["options"] == ["yes", "no"]


def test_session_plan_falls_back_to_runtime_notifications(client, monkeypatch):
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

    plan = client.get("/api/control/sessions/sid-fallback/plan")
    assert plan.status_code == 200
    assert plan.json()["plan_text"] == "Inspect runtime heartbeat path"


@pytest.mark.asyncio
async def test_pending_permissions_follow_runtime_binding_and_session_scope(client, wiring):
    from magi.control.permission.brokered_prompter import (
        PendingPermissionRegistry,
    )
    from magi.control.permission.contracts import (
        PermissionRequest,
        RiskLevel,
        ToolOrigin,
    )

    registry = PendingPermissionRegistry()
    from magi.core.container import get_container

    container = get_container()
    with container.pending_permission_registry.override(None):
        startup = client.get("/api/control/sessions/sid-A/permissions")
        assert startup.status_code == 200
        assert startup.json() == {"items": []}

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

    with container.pending_permission_registry.override(registry):
        response = client.get("/api/control/sessions/sid-A/permissions")
        assert response.status_code == 200
        assert response.json() == {"items": [req_a.to_dict()]}
        assert client.get("/api/control/sessions/sid-B/permissions").json() == {
            "items": [req_b.to_dict()]
        }
        assert client.get("/api/control/sessions/sid-C/permissions").json() == {"items": []}


def test_global_settings_reject_stale_or_missing_revision(client):
    snapshot = client.get("/api/control/settings").json()
    assert client.put("/api/control/settings", json={"permission_mode": "off"}).status_code == 428
    accepted = client.put("/api/control/settings", json={**snapshot, "permission_mode": "all"})
    assert accepted.status_code == 200
    stale = client.put("/api/control/settings", json={**snapshot, "permission_mode": "off"})
    assert stale.status_code == 409
    assert client.get("/api/control/settings").json()["permission_mode"] == "all"


def test_session_revision_includes_global_policy_and_other_client_override(client):
    path = "/api/control/sessions/shared/settings"
    snapshot = client.get(path).json()
    base = client.get("/api/control/settings").json()
    assert client.put("/api/control/settings", json={**base, "permission_mode": "all"}).status_code == 200
    assert client.put(path, json={"revision": snapshot["revision"], "permission_mode": "off"}).status_code == 409
    current = client.get(path).json()
    accepted = client.put(path, json={"revision": current["revision"], "permission_mode": "high_only"})
    assert accepted.status_code == 200
    assert client.put(path, json={"revision": current["revision"], "clear": True}).status_code == 409
    assert client.get(path).json()["effective"]["permission_mode"] == "high_only"
