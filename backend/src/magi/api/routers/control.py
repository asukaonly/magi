"""Agent control-plane REST endpoints.

Mounted under ``/api/control`` via :func:`register_api_routes`. All
endpoints operate on process-wide singletons resolved through the DI
container:

* ``ControlSettingsManager`` — global settings + session overrides
* ``PermissionRuleStore``    — permission rules (session + persistent)
* ``InteractionBroker``      — async gate that permission / ask tools
  suspend on
* ``ControlSessionStore``    — plan-mode + todo + ask state per session

Endpoints:

* ``GET    /settings``                    — current global settings
* ``PUT    /settings``                    — update global settings
* ``GET    /sessions/{sid}/settings``     — effective settings for session
* ``PUT    /sessions/{sid}/settings``     — set / clear session override
* ``GET    /rules``                       — list permission rules
* ``DELETE /rules/{rule_id}``             — delete one rule
* ``DELETE /rules``                       — clear all rules in a scope
* ``POST   /permission/{request_id}/respond`` — resolve a pending prompt
* ``POST   /ask/{request_id}/respond``    — answer an ``ask_user_question``
* ``GET    /sessions/{sid}/plan``         — plan-mode state
* ``GET    /sessions/{sid}/todos``        — todo list snapshot
* ``GET    /sessions/{sid}/ask``          — current ask state (if any)
* ``GET    /sessions/{sid}/permissions``  — pending permission prompts
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field

from ... import i18n as core_i18n
from ...control.permission.contracts import (
    PermissionOutcome,
    PermissionScope,
)
from ...control.settings import (
    PermissionMode,
    SessionControlOverride,
    resolve_effective_settings,
)
from ...control.provider import (
    resolve_control_interaction_broker,
    resolve_control_session_store,
    resolve_control_settings_manager,
    resolve_pending_permission_registry,
    resolve_permission_rule_store,
)
from ...control.session_store import TodoItem
from ...runtime_trace.provider import resolve_runtime_trace_store

control_router = APIRouter()


# ---------------------------------------------------------------------------
# DI helpers
# ---------------------------------------------------------------------------


def _settings_manager():
    try:
        return resolve_control_settings_manager()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "control.errors.settings_manager_unavailable",
                fallback="Control settings manager unavailable",
            ),
        ) from exc


def _rule_store():
    try:
        return resolve_permission_rule_store()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "control.errors.permission_rule_store_unavailable",
                fallback="Permission rule store unavailable",
            ),
        ) from exc


def _broker():
    try:
        return resolve_control_interaction_broker()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "control.errors.interaction_broker_unavailable",
                fallback="Interaction broker unavailable",
            ),
        ) from exc


def _session_store():
    try:
        return resolve_control_session_store()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "control.errors.session_store_unavailable",
                fallback="Control session store unavailable",
            ),
        ) from exc


async def _load_latest_control_notification(
    *,
    session_id: str,
    channel: str,
    limit: int = 200,
) -> dict[str, Any] | None:
    try:
        trace_store = resolve_runtime_trace_store()
    except RuntimeError:
        return None

    try:
        latest_id = await trace_store.get_latest_notification_id()
        if latest_id <= 0:
            return None
        after_id = max(0, latest_id - limit)
        notifications = await trace_store.list_notifications(after_id=after_id, limit=limit)
    except Exception:
        return None

    for notification in reversed(notifications):
        if notification.channel != channel:
            continue
        if str(notification.session_id or "").strip() != session_id:
            continue
        try:
            payload = json.loads(notification.payload_json)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    return None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class _SettingsUpdate(BaseModel):
    permission_mode: Optional[PermissionMode] = None
    plan_approval_required: Optional[bool] = None


@control_router.get("/settings")
async def get_settings() -> dict[str, Any]:
    return _settings_manager().get().to_dict()


@control_router.put("/settings")
async def put_settings(payload: _SettingsUpdate) -> dict[str, Any]:
    manager = _settings_manager()
    new = manager.update(
        permission_mode=payload.permission_mode,
        plan_approval_required=payload.plan_approval_required,
    )
    return new.to_dict()


class _SessionSettingsUpdate(BaseModel):
    permission_mode: Optional[PermissionMode] = None
    plan_approval_required: Optional[bool] = None
    clear: bool = False


@control_router.get("/sessions/{session_id}/settings")
async def get_session_settings(session_id: str) -> dict[str, Any]:
    manager = _settings_manager()
    base = manager.get()
    override = manager.get_session_override(session_id)
    effective = resolve_effective_settings(base=base, override=override)
    return {
        "base": base.to_dict(),
        "override": override.to_dict() if override else None,
        "effective": effective.to_dict(),
    }


@control_router.put("/sessions/{session_id}/settings")
async def put_session_settings(session_id: str, payload: _SessionSettingsUpdate) -> dict[str, Any]:
    manager = _settings_manager()
    if payload.clear:
        manager.set_session_override(session_id, None)
    else:
        override = SessionControlOverride(
            permission_mode=payload.permission_mode,
            plan_approval_required=payload.plan_approval_required,
        )
        manager.set_session_override(session_id, override)
    base = manager.get()
    active = manager.get_session_override(session_id)
    effective = resolve_effective_settings(base=base, override=active)
    return {
        "base": base.to_dict(),
        "override": active.to_dict() if active else None,
        "effective": effective.to_dict(),
    }


# ---------------------------------------------------------------------------
# Permission rules
# ---------------------------------------------------------------------------


@control_router.get("/rules")
async def list_rules(
    session_id: Optional[str] = None,
    include_persistent: bool = True,
) -> dict[str, Any]:
    store = _rule_store()
    rules = store.list_rules(session_id=session_id, include_persistent=include_persistent)
    return {"rules": [r.to_dict() for r in rules]}


@control_router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str = Path(...),
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    store = _rule_store()
    removed = await store.remove(rule_id, session_id=session_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "control.errors.rule_not_found",
                fallback="Rule {rule_id!r} not found",
                rule_id=rule_id,
            ),
        )
    return {"deleted": rule_id}


@control_router.delete("/rules")
async def clear_session_rules(session_id: Optional[str] = None) -> dict[str, Any]:
    """Drop every session-scoped rule for ``session_id``.

    Persistent rules require an explicit per-rule delete to avoid
    accidental bulk loss.
    """
    store = _rule_store()
    await store.clear_session(session_id)
    return {"cleared": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Interactive prompts (permission + ask)
# ---------------------------------------------------------------------------


class _PermissionRespondRequest(BaseModel):
    outcome: Literal["allow", "deny"] = Field(
        ..., description="User decision for the pending prompt"
    )
    scope: Literal["one_shot", "session", "persistent_exact", "persistent_pattern"] = "one_shot"
    pattern: Optional[str] = None
    reason: Optional[str] = None


@control_router.post("/permission/{request_id}/respond")
async def respond_permission(request_id: str, payload: _PermissionRespondRequest) -> dict[str, Any]:
    broker = _broker()
    try:
        scope = PermissionScope(payload.scope)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "control.errors.invalid_scope",
                fallback="Invalid scope: {scope}",
                scope=payload.scope,
            ),
        ) from exc
    response = {
        "outcome": (
            PermissionOutcome.ALLOWED.value
            if payload.outcome == "allow"
            else PermissionOutcome.DENIED.value
        ),
        "scope": scope.value,
        "pattern": payload.pattern,
        "reason": payload.reason,
    }
    resolved = await broker.resolve(
        interaction_id=request_id,
        kind="permission",
        response=response,
    )
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "control.errors.permission_request_not_pending",
                fallback="Permission request {request_id!r} is not pending",
                request_id=request_id,
            ),
        )
    return {"resolved": True, "request_id": request_id}


class _AskRespondRequest(BaseModel):
    answer: str = Field(..., description="User's reply to the ask_user_question tool")


@control_router.post("/ask/{request_id}/respond")
async def respond_ask(request_id: str, payload: _AskRespondRequest) -> dict[str, Any]:
    broker = _broker()
    metadata = await broker.get_pending_metadata(
        interaction_id=request_id,
        kind="ask",
    )
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "control.errors.ask_request_not_pending",
                fallback="Ask request {request_id!r} is not pending",
                request_id=request_id,
            ),
        )
    answer = payload.answer.strip()
    options = {
        option
        for option in (
            str(item or "").strip()
            for item in metadata.get("options", [])
        )
        if option
    }
    if metadata.get("allow_free_text", True) is False and answer not in options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "control.errors.ask_response_option_required",
                fallback="Choose one of the available answers.",
            ),
        )
    resolved = await broker.resolve(
        interaction_id=request_id,
        kind="ask",
        response=answer,
    )
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "control.errors.ask_request_not_pending",
                fallback="Ask request {request_id!r} is not pending",
                request_id=request_id,
            ),
        )
    return {"resolved": True, "request_id": request_id}


# ---------------------------------------------------------------------------
# Session snapshots (plan / todos / ask)
# ---------------------------------------------------------------------------


@control_router.get("/sessions/{session_id}/plan")
async def get_plan_state(session_id: str) -> dict[str, Any]:
    state = _session_store().plan_state(session_id).to_dict()
    if bool(state.get("active")) or str(state.get("plan_text") or "").strip():
        return state

    payload = await _load_latest_control_notification(
        session_id=session_id,
        channel="control.plan.updated",
    )
    plan = payload.get("plan") if isinstance(payload, dict) else None
    return plan if isinstance(plan, dict) else state


@control_router.get("/sessions/{session_id}/todos")
async def get_todos(session_id: str) -> dict[str, Any]:
    todos = _session_store().list_todos(session_id)
    if todos:
        return {"items": [t.to_dict() for t in todos]}

    payload = await _load_latest_control_notification(
        session_id=session_id,
        channel="control.todo.updated",
    )
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return {"items": []}

    restored_items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            restored_items.append(TodoItem.from_dict(raw).to_dict())
        except Exception:
            continue
    return {"items": restored_items}


@control_router.get("/sessions/{session_id}/ask")
async def get_ask_state(session_id: str) -> dict[str, Any]:
    ask = _session_store().ask_state(session_id)
    return {"ask": ask.to_dict() if ask is not None else None}


@control_router.get("/sessions/{session_id}/permissions")
async def get_pending_permissions(session_id: str) -> dict[str, Any]:
    """List permission prompts currently waiting on this session.

    The registry is populated by :class:`BrokeredPermissionPrompter`
    whenever the gateway opens a prompt, and cleared when the prompt
    is resolved or times out. Frontends poll this endpoint (or listen
    for future ``control.permission.requested`` events) to discover
    the request-id they need to answer via
    ``POST /api/control/permission/{request_id}/respond``.
    """
    try:
        registry = resolve_pending_permission_registry()
    except RuntimeError:
        return {"items": []}
    items = [req.to_dict() for req in registry.snapshot(session_id=session_id)]
    return {"items": items}


__all__ = ["control_router"]
