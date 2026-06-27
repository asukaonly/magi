"""Shared helpers for message route modules."""

from __future__ import annotations

from fastapi import HTTPException

from ...core.runtime_bindings import require_chat_attachment_ingestion_service
from ...i18n import t


def require_session_id(session_id: str | None) -> str:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=t("chat.dispatch.errors.session_id_required", fallback="Session ID is required."))
    return normalized


def get_default_chat_workspace_path() -> str | None:
    from .config import _build_system_config

    config = _build_system_config()
    normalized_workspace_path = str(config.preferences.default_chat_workspace_path or "").strip()
    return normalized_workspace_path or None


def get_chat_attachment_ingestion_service():
    return require_chat_attachment_ingestion_service()


__all__ = [
    "get_chat_attachment_ingestion_service",
    "get_default_chat_workspace_path",
    "require_session_id",
]
