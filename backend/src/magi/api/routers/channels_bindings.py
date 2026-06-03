"""Channel bindings REST endpoints — Phase H+2.

Two endpoints behind ``/api/channels``:

* ``GET /bindings`` — list every (channel, external_user) binding the
  host has seen, joined with its auto-approve flag. Used by the
  Settings → Channels UI to render the "外部渠道免审批" toggles.
* ``PUT /bindings/{channel_type}/{external_user_id}/auto-approve``
  — flip the toggle. Body ``{enabled: bool}``.

Reads ``binding_settings_store`` + ``session_mapper`` off the
ChannelsModule parked on the bootstrap context. If ChannelsModule
isn't initialized yet (very early in app boot), GET returns an empty
list and PUT returns 503 so the UI can retry.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...core.container import get_container


__all__ = ["channels_bindings_router"]


channels_bindings_router = APIRouter()


class _BindingView(BaseModel):
    channel_type: str
    external_user_id: str
    display_name: str = ""
    magi_session_id: str
    auto_approve: bool = False
    last_active_at_ms: int = 0
    updated_at_ms: int = 0


class _BindingsListResponse(BaseModel):
    bindings: list[_BindingView] = Field(default_factory=list)


class _SetAutoApproveRequest(BaseModel):
    enabled: bool


class _SetAutoApproveResponse(BaseModel):
    channel_type: str
    external_user_id: str
    auto_approve: bool
    updated_at_ms: int


def _resolve_channels_module() -> Any:
    """Look up ChannelsModule on the bootstrap context. Returns None
    when channels haven't initialized yet (early boot)."""
    try:
        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    if context is None:
        return None
    return getattr(context.channels, "module", None)


def _extract_external_user_id(metadata_json: str) -> str:
    try:
        meta = json.loads(metadata_json) if metadata_json else {}
    except (json.JSONDecodeError, TypeError):
        return ""
    raw = meta.get("external_user_id") or ""
    return str(raw)


def _extract_display_name(metadata_json: str) -> str:
    try:
        meta = json.loads(metadata_json) if metadata_json else {}
    except (json.JSONDecodeError, TypeError):
        return ""
    raw = meta.get("display_name") or ""
    return str(raw)


@channels_bindings_router.get(
    "/bindings", response_model=_BindingsListResponse,
)
async def list_bindings() -> _BindingsListResponse:
    """List every (channel, external_user) binding + its auto-approve
    flag. De-duplicates across multiple chats for the same external
    user — auto-approve is keyed by (channel_type, external_user_id)
    so a user with two Telegram chats shows up once."""
    module = _resolve_channels_module()
    if module is None:
        return _BindingsListResponse(bindings=[])
    session_mapper = getattr(module, "session_mapper", None)
    settings_store = getattr(module, "binding_settings_store", None)
    if session_mapper is None or settings_store is None:
        return _BindingsListResponse(bindings=[])

    mappings = await session_mapper.list_all()
    # Dedup by (channel_type, external_user_id). Keep the most
    # recently active row (mappings come back ORDER BY last_active DESC,
    # so the first occurrence wins).
    seen: dict[tuple[str, str], dict] = {}
    for m in mappings:
        external_user_id = _extract_external_user_id(m.metadata_json)
        if not external_user_id:
            continue
        key = (m.channel_type, external_user_id)
        if key in seen:
            continue
        seen[key] = {
            "channel_type": m.channel_type,
            "external_user_id": external_user_id,
            "display_name": _extract_display_name(m.metadata_json),
            "magi_session_id": m.magi_session_id,
            "last_active_at_ms": m.last_active_at_ms,
        }

    # Augment with auto-approve settings.
    views: list[_BindingView] = []
    for entry in seen.values():
        settings = await settings_store.get(
            channel_type=entry["channel_type"],
            external_user_id=entry["external_user_id"],
        )
        views.append(_BindingView(
            channel_type=entry["channel_type"],
            external_user_id=entry["external_user_id"],
            display_name=entry["display_name"],
            magi_session_id=entry["magi_session_id"],
            auto_approve=settings.auto_approve,
            last_active_at_ms=entry["last_active_at_ms"],
            updated_at_ms=settings.updated_at_ms,
        ))
    return _BindingsListResponse(bindings=views)


@channels_bindings_router.put(
    "/bindings/{channel_type}/{external_user_id}/auto-approve",
    response_model=_SetAutoApproveResponse,
)
async def set_auto_approve(
    channel_type: str,
    external_user_id: str,
    payload: _SetAutoApproveRequest,
) -> _SetAutoApproveResponse:
    """Flip the auto-approve toggle for one binding. Idempotent —
    setting the same value twice still bumps updated_at_ms for
    audit. Returns the resulting state."""
    module = _resolve_channels_module()
    settings_store = (
        getattr(module, "binding_settings_store", None)
        if module is not None
        else None
    )
    if settings_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channels module not yet initialized — retry later",
        )
    # Light input validation; the store rejects empties too.
    if not channel_type.strip() or not external_user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel_type and external_user_id must be non-empty",
        )

    result = await settings_store.set_auto_approve(
        channel_type=channel_type,
        external_user_id=external_user_id,
        auto_approve=payload.enabled,
    )
    return _SetAutoApproveResponse(
        channel_type=result.channel_type,
        external_user_id=result.external_user_id,
        auto_approve=result.auto_approve,
        updated_at_ms=result.updated_at_ms,
    )
