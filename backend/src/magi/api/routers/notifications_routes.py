"""HTTP API for the notification center (durable user_notifications)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
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
    total: int


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
    profile_conflict_suppression_dep: "Callable[[], Awaitable[bool]] | None" = None,
) -> APIRouter:
    router = APIRouter()
    router.add_api_route(
        "/notifications",
        _list_notifications_endpoint(
            service_dep,
            profile_conflict_suppression_dep,
        ),
        methods=["GET"],
        response_model=ListResponse,
    )
    router.add_api_route(
        "/notifications/mark-read",
        _mark_read_endpoint(service_dep),
        methods=["POST"],
    )
    router.add_api_route(
        "/notifications/dismiss-all",
        _dismiss_all_endpoint(service_dep),
        methods=["POST"],
    )
    router.add_api_route(
        "/notifications/{notification_id}/dismiss",
        _dismiss_endpoint(service_dep),
        methods=["POST"],
    )
    router.add_api_route(
        "/notifications/{notification_id}/action",
        _action_endpoint(service_dep),
        methods=["POST"],
    )
    router.add_api_route(
        "/notifications/{notification_id}/resolve-conflict",
        _resolve_conflict_endpoint(service_dep, unified_memory_dep),
        methods=["POST"],
        response_model=ResolveConflictResponse,
    )
    return router


def _list_notifications_endpoint(
    service_dep: Callable[[], NotificationService],
    profile_conflict_suppression_dep: "Callable[[], Awaitable[bool]] | None",
):
    async def list_notifications(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        profile_conflicts_only: bool = Query(default=False),
    ) -> ListResponse:
        suppress_profile_conflicts = (
            await profile_conflict_suppression_dep()
            if profile_conflict_suppression_dep is not None
            else False
        )
        result = service_dep().list(
            _USER_ID,
            exclude_profile_conflicts=suppress_profile_conflicts,
            limit=limit, offset=offset, profile_conflicts_only=profile_conflicts_only,
        )
        items = [_notification_item_model(row) for row in result["items"]]
        return ListResponse(items=items, unread_count=result["unread_count"], total=result["total"])

    return list_notifications


def _notification_item_model(row) -> NotificationItemModel:
    return NotificationItemModel(
        id=row.id,
        kind=row.kind,
        dedupe_key=row.dedupe_key,
        title=row.title,
        body=row.body,
        payload=json.loads(row.payload_json or "{}"),
        status=row.status,
        created_at_ms=row.created_at_ms,
        read_at_ms=row.read_at_ms,
    )


def _mark_read_endpoint(service_dep: Callable[[], NotificationService]):
    async def mark_read(req: MarkReadRequest) -> dict:
        svc = service_dep()
        if req.all:
            svc.mark_read_all(_USER_ID)
        elif req.ids:
            svc.mark_read(req.ids)
        return {"ok": True}

    return mark_read


def _dismiss_all_endpoint(service_dep: Callable[[], NotificationService]):
    async def dismiss_all() -> dict:
        dismissed = service_dep().dismiss_all(_USER_ID, "explicit")
        return {"ok": True, "dismissed": dismissed}

    return dismiss_all


def _dismiss_endpoint(service_dep: Callable[[], NotificationService]):
    async def dismiss(notification_id: int) -> dict:
        service_dep().dismiss(notification_id, "explicit")
        return {"ok": True}

    return dismiss


def _action_endpoint(service_dep: Callable[[], NotificationService]):
    async def action(notification_id: int) -> dict:
        service_dep().action(notification_id)
        return {"ok": True}

    return action


def _resolve_conflict_endpoint(
    service_dep: Callable[[], NotificationService],
    unified_memory_dep: "Callable[[], object] | None",
):
    async def resolve_conflict(
        notification_id: int,
        body: ResolveConflictRequest,
    ) -> ResolveConflictResponse:
        return await _resolve_profile_conflict_notification(
            notification_id=notification_id,
            body=body,
            service_dep=service_dep,
            unified_memory_dep=unified_memory_dep,
        )

    return resolve_conflict


async def _resolve_profile_conflict_notification(
    *,
    notification_id: int,
    body: ResolveConflictRequest,
    service_dep: Callable[[], NotificationService],
    unified_memory_dep: "Callable[[], object] | None",
) -> ResolveConflictResponse:
    svc = service_dep()
    payload = _load_notification_payload(svc, notification_id)
    shadow_id = _profile_conflict_shadow_id(payload)
    unified_memory = _resolve_unified_memory(unified_memory_dep)
    result = await unified_memory.l2.resolve_shadow_conflict(
        shadow_id=shadow_id,
        action=body.action,
    )
    svc.action(notification_id)
    return ResolveConflictResponse(
        status="resolved",
        action=body.action,
        resolved=result is not None,
    )


def _load_notification_payload(svc: NotificationService, notification_id: int) -> dict:
    row = svc._store.get(notification_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    try:
        return json.loads(row.payload_json or "{}")
    except (ValueError, TypeError):
        return {}


def _profile_conflict_shadow_id(payload: dict) -> str:
    shadow_id = payload.get("shadow_id")
    if payload.get("conflict_type") == "profile_conflict" and shadow_id:
        return str(shadow_id)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Notification is not a resolvable profile-conflict notification",
    )


def _resolve_unified_memory(unified_memory_dep: "Callable[[], object] | None"):
    get_unified_memory = (
        unified_memory_dep if unified_memory_dep is not None else _default_unified_memory_dep
    )
    unified_memory = get_unified_memory()
    if unified_memory is None or unified_memory.l2 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not available",
        )
    return unified_memory


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


async def _default_profile_conflict_suppression_dep() -> bool:
    from magi.core.runtime_bindings import require_chat_read_service

    try:
        pending_count = (
            await require_chat_read_service().aget_interrupted_global_clear_count()
        )
    except RuntimeError:
        return False
    return pending_count is not None


def _build_production_notifications_router() -> APIRouter:
    return build_default_notifications_router(
        service_dep=_default_service,
        unified_memory_dep=_default_unified_memory_dep,
        profile_conflict_suppression_dep=_default_profile_conflict_suppression_dep,
    )


notifications_router: APIRouter = _build_production_notifications_router()

__all__ = ["build_default_notifications_router", "notifications_router"]
