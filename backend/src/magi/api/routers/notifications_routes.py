"""HTTP API for the notification center (durable user_notifications)."""
from __future__ import annotations

import json
from typing import Callable, Optional

from fastapi import APIRouter
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


def build_default_notifications_router(*, service_dep: Callable[[], NotificationService]) -> APIRouter:
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

    return router


def _default_service() -> NotificationService:
    from magi.notifications.store import get_notification_store
    from magi.system_suggestions.dismissals import record_dismissal
    return NotificationService(store=get_notification_store(), record_dismissal=record_dismissal)


def _build_production_notifications_router() -> APIRouter:
    return build_default_notifications_router(service_dep=_default_service)


notifications_router: APIRouter = _build_production_notifications_router()

__all__ = ["build_default_notifications_router", "notifications_router"]
