"""HTTP API for the notification center (durable user_notifications)."""
from __future__ import annotations

import json
from typing import Callable, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from magi.notifications.service import NotificationService

_USER_ID = "default_user"


class NotificationItemModel(BaseModel):
    id: int
    kind: str
    dedupe_key: str
    title: str
    body: str
    payload: dict
    status: str
    created_at_ms: int
    read_at_ms: Optional[int] = None


class ListResponse(BaseModel):
    items: list[NotificationItemModel]
    unread_count: int


class MarkReadRequest(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class ResolveConflictRequest(BaseModel):
    action: Literal["confirm", "reject"]


class ResolveConflictResponse(BaseModel):
    status: str
    action: str
    resolved: bool


def build_default_notifications_router(
    *,
    service_dep: Callable[[], NotificationService],
    unified_memory_dep: "Callable[[], object] | None" = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/notifications", response_model=ListResponse)
    async def list_notifications() -> ListResponse:
        svc = service_dep()
        result = svc.list(_USER_ID)
        items = [
            NotificationItemModel(
                id=r.id, kind=r.kind, dedupe_key=r.dedupe_key, title=r.title, body=r.body,
                payload=json.loads(r.payload_json or "{}"), status=r.status,
                created_at_ms=r.created_at_ms, read_at_ms=r.read_at_ms,
            )
            for r in result["items"]
        ]
        return ListResponse(items=items, unread_count=result["unread_count"])

    @router.post("/notifications/mark-read")
    async def mark_read(req: MarkReadRequest) -> dict:
        svc = service_dep()
        if req.all:
            svc.mark_read_all(_USER_ID)
        elif req.ids:
            svc.mark_read(req.ids)
        return {"ok": True}

    @router.post("/notifications/dismiss-all")
    async def dismiss_all() -> dict:
        dismissed = service_dep().dismiss_all(_USER_ID, "explicit")
        return {"ok": True, "dismissed": dismissed}

    @router.post("/notifications/{notification_id}/dismiss")
    async def dismiss(notification_id: int) -> dict:
        service_dep().dismiss(notification_id, "explicit")
        return {"ok": True}

    @router.post("/notifications/{notification_id}/action")
    async def action(notification_id: int) -> dict:
        service_dep().action(notification_id)
        return {"ok": True}

    @router.post(
        "/notifications/{notification_id}/resolve-conflict",
        response_model=ResolveConflictResponse,
    )
    async def resolve_conflict(
        notification_id: int,
        body: ResolveConflictRequest,
    ) -> ResolveConflictResponse:
        """Resolve a profile-conflict notification by confirming or rejecting the shadow assertion.

        action="confirm" promotes the inferred shadow to the authoritative value.
        action="reject"  discards the shadow; the existing authoritative value is kept.
        """
        svc = service_dep()

        # 1. Load the notification; 404 if absent.
        row = svc._store.get(notification_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        # 2. Parse payload and verify it is a profile_conflict notification.
        try:
            payload = json.loads(row.payload_json or "{}")
        except (ValueError, TypeError):
            payload = {}

        if payload.get("conflict_type") != "profile_conflict" or not payload.get("shadow_id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Notification is not a resolvable profile-conflict notification",
            )

        shadow_id: str = payload["shadow_id"]

        # 3. Resolve via the L2 store.
        _get_unified_memory = (
            unified_memory_dep if unified_memory_dep is not None else _default_unified_memory_dep
        )
        unified_memory = _get_unified_memory()
        if unified_memory is None or unified_memory.l2 is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Memory system not available",
            )

        result = await unified_memory.l2.resolve_shadow_conflict(
            shadow_id=shadow_id,
            action=body.action,
        )

        # 4. Mark the notification as actioned regardless of whether the shadow
        #    was already resolved (idempotency: shadow may be gone on retry).
        svc.action(notification_id)

        return ResolveConflictResponse(
            status="resolved",
            action=body.action,
            resolved=result is not None,
        )

    return router


def _default_service() -> NotificationService:
    from magi.notifications.store import get_notification_store
    from magi.system_suggestions.dismissals import record_dismissal
    return NotificationService(store=get_notification_store(), record_dismissal=record_dismissal)


def _default_unified_memory_dep():
    try:
        from magi.memory.provider import get_unified_memory
        return get_unified_memory()
    except RuntimeError:
        return None


def _build_production_notifications_router() -> APIRouter:
    return build_default_notifications_router(
        service_dep=_default_service,
        unified_memory_dep=_default_unified_memory_dep,
    )


notifications_router: APIRouter = _build_production_notifications_router()

__all__ = ["build_default_notifications_router", "notifications_router"]
