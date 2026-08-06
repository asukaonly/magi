"""Public API contracts for governed pending-memory reviews."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.memory.l2.reviews.models import PendingReviewResolution
from magi.memory.l2.reviews.repository import PendingReviewConflictError


def _client(monkeypatch, store) -> TestClient:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.review_routes._resolve_unified_memory",
        lambda: SimpleNamespace(l2=store, identity_resolver=None),
    )
    return TestClient(app)


def test_review_routes_are_reachable_through_public_router() -> None:
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    methods = {route.path: route.methods for route in public.routes if hasattr(route, "methods")}

    assert methods["/l2/reviews"] == {"GET"}
    assert methods["/l2/reviews/{review_id}/resolve"] == {"POST"}


def test_list_reviews_uses_canonical_self_subject(monkeypatch) -> None:
    store = SimpleNamespace(
        list_pending_reviews=AsyncMock(
            return_value=[{"review_id": "rev_1", "status": "pending", "version": 1}]
        )
    )
    client = _client(monkeypatch, store)

    response = client.get("/api/memory/l2/reviews")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    store.list_pending_reviews.assert_awaited_once_with(
        subject_id="user:local_user",
        status="pending",
        limit=100,
    )


def test_resolve_review_forwards_only_editable_fields(monkeypatch) -> None:
    store = SimpleNamespace(
        resolve_pending_review=AsyncMock(
            return_value=PendingReviewResolution(
                review_id="rev_1",
                status="confirmed",
                version=2,
                assertion_id="assert_1",
            )
        )
    )
    client = _client(monkeypatch, store)

    response = client.post(
        "/api/memory/l2/reviews/rev_1/resolve",
        json={
            "action": "confirm_with_edit",
            "expected_version": 1,
            "edit": {"trait_value": "明年春天去海边"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "review_id": "rev_1",
        "status": "confirmed",
        "version": 2,
        "assertion_id": "assert_1",
    }
    call = store.resolve_pending_review.await_args.kwargs
    assert call["edit"] == {"trait_value": "明年春天去海边"}
    assert call["resolved_by"] == "user:local_user"
    assert call["resolution_event_id"].startswith("review_event_")
    assert call["route_contract_version"] == 5
    assert call["evidence_rule_version"] == 2


def test_stale_review_version_returns_conflict(monkeypatch) -> None:
    store = SimpleNamespace(
        resolve_pending_review=AsyncMock(
            side_effect=PendingReviewConflictError("pending review version is stale")
        )
    )
    client = _client(monkeypatch, store)

    response = client.post(
        "/api/memory/l2/reviews/rev_1/resolve",
        json={"action": "reject", "expected_version": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "pending review version is stale"
