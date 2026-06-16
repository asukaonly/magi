"""Tests for POST /notifications/{notification_id}/resolve-conflict (PB-T3).

Verifies:
- confirm action promotes shadow + marks notification actioned (200, resolved=True)
- reject action discards shadow + marks notification actioned (200, resolved=True)
- already-resolved shadow (idempotent) → 200, resolved=False, notification actioned
- non-conflict notification → 400
- unknown notification id → 404
- l2 store unavailable → 503
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.notifications.service import NotificationService
from magi.notifications.store import NotificationRow, NotificationStore
from magi.api.routers.notifications_routes import build_default_notifications_router

from _shared.memory_schema import apply_memory_shared_schema


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_ENTITY_ID = "user:conflict_resolve_api_test"
_TRAIT_NAME = "diet_preference"
_TARGET_ID = "topic:vegan"

_CANDIDATE_BASE = {
    "entity_id": _ENTITY_ID,
    "entity_type": "user",
    "trait_family": "preference_profile",
    "trait_name": _TRAIT_NAME,
    "trait_value": "vegan",
    "confidence_score": 0.40,
    "evidence_events": ["evt-api-test-1"],
    "volatility_index": 0.2,
    "source_domain": "user_authored",
    "inference_depth": "topology_only",
    "validation_state": "tentative",
    "first_inferred_at": 1_710_000_000.0,
    "last_validated_at": 1_710_000_000.0,
    "target_entity_id": _TARGET_ID,
    "target_entity_type": "topic",
    "target_scope": "entity_bound",
    "temporal_scope": "stable",
    "decay_policy": "evidence_only",
    "decay_anchor_at": 1_710_000_000.0,
    "context_ref_id": "",
    "expires_at": None,
    "memory_subdomain": "",
    "natural_summary": "",
}


@pytest_asyncio.fixture
async def l2_store(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store


class _FakeUnifiedMemory:
    def __init__(self, l2_store):
        self.l2 = l2_store


@pytest_asyncio.fixture
async def setup(tmp_path, l2_store):
    """Return (TestClient, notif_store, l2_store) with a seeded shadow conflict."""
    # Build notification store.
    ns = NotificationStore(str(tmp_path / "notifications.db"))
    ns.ensure_schema()
    svc = NotificationService(store=ns)

    unified_memory = _FakeUnifiedMemory(l2_store)

    # Create shadow: authoritative "vegan" (user_authored) + inferred "omnivore" → shadow.
    auth_id = await l2_store.upsert_assertion_candidate({
        **_CANDIDATE_BASE,
        "trait_value": "vegan",
        "source_domain": "user_authored",
        "evidence_events": ["evt-auth-resolve-1"],
    })
    shadow_id = await l2_store.upsert_assertion_candidate({
        **_CANDIDATE_BASE,
        "trait_value": "omnivore",
        "source_domain": "external_activity",
        "evidence_events": ["evt-inf-resolve-1"],
        "first_inferred_at": 1_710_000_100.0,
        "last_validated_at": 1_710_000_100.0,
    })

    # Insert conflict notification.
    payload = json.dumps({
        "conflict_type": "profile_conflict",
        "shadow_id": shadow_id,
        "authoritative_id": auth_id,
        "trait_name": _TRAIT_NAME,
        "authoritative_value": "vegan",
        "inferred_value": "omnivore",
        "entity_id": _ENTITY_ID,
    })
    notif_id = ns.insert(NotificationRow(
        user_id="default_user",
        kind="profile_conflict",
        dedupe_key=f"profile_conflict:{_TRAIT_NAME}:{_TARGET_ID}",
        title="Conflict: diet_preference",
        body="Your inferred preference conflicts with what you said.",
        payload_json=payload,
        status="unread",
        created_at_ms=1_710_000_000_000,
    ))

    app = FastAPI()
    app.include_router(
        build_default_notifications_router(
            service_dep=lambda: svc,
            unified_memory_dep=lambda: unified_memory,
        )
    )
    client = TestClient(app)
    return client, ns, l2_store, notif_id, shadow_id, auth_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_conflict_confirm(setup):
    """confirm promotes the shadow and marks the notification actioned."""
    client, ns, l2_store, notif_id, shadow_id, auth_id = setup

    r = client.post(f"/notifications/{notif_id}/resolve-conflict", json={"action": "confirm"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"
    assert body["action"] == "confirm"
    assert body["resolved"] is True

    # Notification marked actioned (no longer in the default visible feed).
    row = ns.get(notif_id)
    assert row is not None
    assert row.status == "actioned"

    # Shadow is now promoted to stable.
    promoted = await l2_store.get_tom_assertion(assertion_id=shadow_id)
    assert promoted is not None
    assert promoted["status"] == "stable"
    assert promoted["user_feedback"] == "confirmed"


@pytest.mark.asyncio
async def test_resolve_conflict_reject(setup):
    """reject discards the shadow and marks the notification actioned."""
    client, ns, l2_store, notif_id, shadow_id, auth_id = setup

    r = client.post(f"/notifications/{notif_id}/resolve-conflict", json={"action": "reject"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"
    assert body["action"] == "reject"
    assert body["resolved"] is True

    # Notification marked actioned.
    row = ns.get(notif_id)
    assert row is not None
    assert row.status == "actioned"

    # Shadow is now user_rejected.
    rejected = await l2_store.get_tom_assertion(assertion_id=shadow_id)
    assert rejected is not None
    assert rejected["validation_state"] == "user_rejected"


@pytest.mark.asyncio
async def test_resolve_conflict_idempotent_already_resolved(setup):
    """If shadow was already resolved, resolved=False but still 200 and notification actioned."""
    client, ns, l2_store, notif_id, shadow_id, auth_id = setup

    # First confirm.
    r1 = client.post(f"/notifications/{notif_id}/resolve-conflict", json={"action": "confirm"})
    assert r1.status_code == 200

    # Unmark actioned to allow a second call (simulate retry by reinserting notification).
    # Actually, the second call should still work (notification might already be actioned).
    # Re-insert a fresh notification pointing to the same already-promoted shadow.
    ns2_id = ns.insert(NotificationRow(
        user_id="default_user",
        kind="profile_conflict",
        dedupe_key=f"profile_conflict:{_TRAIT_NAME}:{_TARGET_ID}_retry",
        title="Conflict again",
        body="retry",
        payload_json=json.dumps({
            "conflict_type": "profile_conflict",
            "shadow_id": shadow_id,
            "authoritative_id": auth_id,
            "trait_name": _TRAIT_NAME,
            "authoritative_value": "vegan",
            "inferred_value": "omnivore",
            "entity_id": _ENTITY_ID,
        }),
        status="unread",
        created_at_ms=1_710_000_002_000,
    ))

    r2 = client.post(f"/notifications/{ns2_id}/resolve-conflict", json={"action": "confirm"})
    assert r2.status_code == 200
    body2 = r2.json()
    # Shadow is no longer in "shadow" status, so resolve_shadow_conflict returns None.
    assert body2["resolved"] is False
    # Notification still gets actioned.
    row2 = ns.get(ns2_id)
    assert row2 is not None
    assert row2.status == "actioned"


def test_resolve_conflict_non_conflict_notification(tmp_path):
    """A plain suggestion notification → 400."""
    ns = NotificationStore(str(tmp_path / "notifications.db"))
    ns.ensure_schema()
    svc = NotificationService(store=ns)

    notif_id = ns.insert(NotificationRow(
        user_id="default_user",
        kind="suggestion",
        dedupe_key="browser_history",
        title="Use browser history",
        body="Install the browser extension.",
        payload_json='{"category": "browser_history"}',
        status="unread",
        created_at_ms=1_710_000_000_000,
    ))

    app = FastAPI()
    app.include_router(
        build_default_notifications_router(
            service_dep=lambda: svc,
            unified_memory_dep=lambda: _FakeUnifiedMemory(None),
        )
    )
    client = TestClient(app)
    r = client.post(f"/notifications/{notif_id}/resolve-conflict", json={"action": "confirm"})
    assert r.status_code == 400, r.text


def test_resolve_conflict_unknown_notification_id(tmp_path):
    """Unknown notification id → 404."""
    ns = NotificationStore(str(tmp_path / "notifications.db"))
    ns.ensure_schema()
    svc = NotificationService(store=ns)

    app = FastAPI()
    app.include_router(
        build_default_notifications_router(
            service_dep=lambda: svc,
            unified_memory_dep=lambda: _FakeUnifiedMemory(None),
        )
    )
    client = TestClient(app)
    r = client.post("/notifications/99999/resolve-conflict", json={"action": "reject"})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_resolve_conflict_l2_unavailable(setup):
    """When unified_memory is None → 503."""
    client_orig, ns, l2_store, notif_id, shadow_id, auth_id = setup

    # Build a client with no unified_memory.
    svc = NotificationService(store=ns)
    app2 = FastAPI()
    app2.include_router(
        build_default_notifications_router(
            service_dep=lambda: svc,
            unified_memory_dep=lambda: None,
        )
    )
    client2 = TestClient(app2, raise_server_exceptions=False)
    r = client2.post(f"/notifications/{notif_id}/resolve-conflict", json={"action": "confirm"})
    assert r.status_code == 503, r.text
