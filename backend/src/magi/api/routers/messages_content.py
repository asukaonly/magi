"""Attachment, history, and trace routes for chat messages."""

from __future__ import annotations

import os
import weakref
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ..services import get_chat_trace_read_service
from magi.core.chat_assets.io import (
    aopen_managed_chat_attachment,
    stream_managed_chat_file,
)
from magi.core.chat_assets.paths import normalize_chat_asset_component
from ...core.runtime_bindings import (
    require_chat_forgetting_service,
    require_chat_read_service,
)
from ...i18n import t
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from ...core.chat_cleanup import ChatSurfaceCleanupPendingError
from ...control.provider import resolve_control_session_store
from ...utils.runtime import get_runtime_paths
from .messages_common import get_chat_attachment_ingestion_service, require_session_id
from .messages_models import ClearHistoryResponse

message_content_router = APIRouter()


@message_content_router.post("/session/{session_id}/attachments", response_model=Dict[str, Any])
async def upload_chat_attachment(
    session_id: str,
    user_id: str = Form(default=DEFAULT_USER_ID),
    turn_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload one desktop chat attachment into managed local storage."""
    resolved_session_id = require_session_id(session_id)
    resolved_turn_id = require_session_id(turn_id)
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=400,
            detail=t("chat.attachments.empty_file", fallback="Empty file is not allowed."),
        )

    service = get_chat_attachment_ingestion_service()
    try:
        resolved_session_id = normalize_chat_asset_component(
            resolved_session_id,
            label="session_id",
        )
        resolved_turn_id = normalize_chat_asset_component(
            resolved_turn_id,
            label="turn_id",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=t(
                "chat.attachments.invalid_request",
                fallback="The attachment request is invalid.",
            ),
        ) from exc
    try:
        attachment_payload = await service.ingest_uploaded_attachment(
            user_id=user_id,
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            original_name=file.filename or "",
            content=content,
            mime_type=file.content_type or "application/octet-stream",
        )
        if attachment_payload is None:
            raise HTTPException(
                status_code=404,
                detail=t(
                    "chat.attachments.session_not_found",
                    fallback="Chat session not found.",
                ),
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "message": t("chat.attachments.uploaded", fallback="Attachment uploaded"),
        "data": {
            "user_id": user_id,
            "session_id": resolved_session_id,
            "turn_id": resolved_turn_id,
            "attachment": attachment_payload,
        },
    }


@message_content_router.get("/session/{session_id}/attachments/{attachment_id}/content")
async def get_chat_attachment_content(
    session_id: str,
    attachment_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
):
    """Serve one persisted chat attachment from managed local storage."""
    try:
        resolved_session_id = normalize_chat_asset_component(
            require_session_id(session_id),
            label="session_id",
        )
        resolved_attachment_id = normalize_chat_asset_component(
            require_session_id(attachment_id),
            label="attachment_id",
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=t(
                "chat.attachments.invalid_request",
                fallback="The attachment request is invalid.",
            ),
        )
    read_service = require_chat_read_service()
    attachment = await read_service.aget_attachment_payload(
        user_id,
        resolved_session_id,
        resolved_attachment_id,
    )
    if not isinstance(attachment, dict):
        raise HTTPException(
            status_code=404, detail=t("chat.attachments.not_found", fallback="Attachment not found")
        )

    original_name = str(attachment.get("original_name") or "").strip()
    handle = await aopen_managed_chat_attachment(
        attachment.get("storage_path"),
        session_id=resolved_session_id,
        turn_id=attachment.get("turn_id"),
        attachment_id=resolved_attachment_id,
        original_name=original_name,
        runtime_paths=get_runtime_paths(),
    )
    if handle is None:
        raise HTTPException(
            status_code=404,
            detail=t("chat.attachments.file_not_found", fallback="Attachment file not found"),
        )

    filename = original_name or f"{resolved_attachment_id}.bin"
    encoded_filename = quote(filename, safe="")
    content_disposition = (
        f'attachment; filename="{filename}"'
        if encoded_filename == filename
        else f"attachment; filename*=utf-8''{encoded_filename}"
    )
    try:
        content_length = os.fstat(handle.fileno()).st_size
        response = StreamingResponse(
            stream_managed_chat_file(handle),
            media_type=str(attachment.get("mime_type") or "application/octet-stream").strip()
            or "application/octet-stream",
            headers={
                "content-disposition": content_disposition,
                "content-length": str(content_length),
            },
            background=BackgroundTask(handle.close),
        )
        weakref.finalize(response, handle.close)
        return response
    except BaseException:
        handle.close()
        raise


@message_content_router.get("/history", response_model=Dict[str, Any])
async def get_conversation_history(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
):
    """Get conversation history."""
    try:
        read_service = require_chat_read_service()
        resolved_session_id = require_session_id(session_id)
        history = await read_service.aget_display_history(user_id, resolved_session_id)
        session_summary = await read_service.aget_session_summary(user_id, resolved_session_id)
        context_usage = await read_service.aget_latest_context_usage(
            user_id,
            resolved_session_id,
        )
        messages = [msg.to_dict() for msg in history]

        return {
            "user_id": user_id,
            "session_id": resolved_session_id,
            "messages": messages,
            "count": len(messages),
            "history_version": session_summary.history_version
            if session_summary is not None
            else 0,
            "context_usage": (
                context_usage.to_dict() if context_usage is not None else None
            ),
        }
    except RuntimeError:
        return {
            "user_id": user_id,
            "session_id": session_id,
            "messages": [],
            "count": 0,
            "history_version": 0,
            "context_usage": None,
        }


@message_content_router.get("/trace", response_model=Dict[str, Any])
async def get_execution_trace(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
    turn_id: str = Query(..., description="Turn ID for the target user message"),
):
    """Get structured execution trace for one chat turn."""
    require_chat_read_service()
    resolved_session_id = require_session_id(session_id)
    trace_service = get_chat_trace_read_service()
    snapshot = await trace_service.aget_trace_snapshot(
        user_id=user_id,
        session_id=resolved_session_id,
        turn_id=turn_id,
    )
    return {
        "success": snapshot is not None,
        "user_id": user_id,
        "session_id": resolved_session_id,
        "turn_id": turn_id,
        "trace": snapshot,
    }


@message_content_router.post(
    "/history/clear",
    response_model=ClearHistoryResponse,
)
async def clear_conversation_history(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
):
    """Permanently clear the current immutable conversation snapshot."""
    resolved_session_id = require_session_id(session_id)
    cleanup_pending = False
    try:
        cleared = await require_chat_forgetting_service().clear_history(
            user_id=user_id,
            session_id=resolved_session_id,
        )
    except ChatSurfaceCleanupPendingError as exc:
        if exc.session_id != resolved_session_id:
            raise
        cleared_message_ids = list(exc.message_ids)
        cleared_turn_ids = list(exc.turn_ids)
        cleanup_pending = True
    else:
        if not cleared:
            raise HTTPException(status_code=404, detail="Chat session not found")
        cleared_message_ids = list(cleared.message_ids)
        cleared_turn_ids = list(cleared.turn_ids)
    await resolve_control_session_store().clear_session(resolved_session_id)
    return {
        "success": True,
        "message": t("chat.history.cleared", fallback="Conversation history cleared"),
        "user_id": user_id,
        "session_id": resolved_session_id,
        "cleared_message_ids": cleared_message_ids,
        "cleared_turn_ids": cleared_turn_ids,
        "cleanup_pending": cleanup_pending,
    }


__all__ = [
    "clear_conversation_history",
    "get_chat_attachment_content",
    "get_conversation_history",
    "get_execution_trace",
    "message_content_router",
    "upload_chat_attachment",
]
