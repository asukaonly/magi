"""Attachment, history, and trace routes for chat messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..services import get_chat_trace_read_service
from ...core.runtime_bindings import require_chat_read_service
from ...i18n import t
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from ...chat.forgetting import get_chat_forgetting_service
from .messages_common import get_chat_attachment_ingestion_service, require_session_id

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
        raise HTTPException(status_code=400, detail=t("chat.attachments.empty_file", fallback="Empty file is not allowed."))

    service = get_chat_attachment_ingestion_service()
    try:
        attachment_payload = service.ingest_attachment(
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            original_name=file.filename or "",
            content=content,
            mime_type=file.content_type or "application/octet-stream",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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
    resolved_session_id = require_session_id(session_id)
    resolved_attachment_id = require_session_id(attachment_id)
    read_service = require_chat_read_service()
    attachment = await read_service.aget_attachment_payload(
        user_id,
        resolved_session_id,
        resolved_attachment_id,
    )
    if not isinstance(attachment, dict):
        raise HTTPException(status_code=404, detail=t("chat.attachments.not_found", fallback="Attachment not found"))

    storage_path = Path(str(attachment.get("storage_path") or "").strip())
    if not storage_path.is_file():
        raise HTTPException(status_code=404, detail=t("chat.attachments.file_not_found", fallback="Attachment file not found"))

    return FileResponse(
        path=storage_path,
        media_type=str(attachment.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream",
        filename=str(attachment.get("original_name") or storage_path.name).strip() or storage_path.name,
    )


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
        messages = [msg.to_dict() for msg in history]

        return {
            "user_id": user_id,
            "session_id": resolved_session_id,
            "messages": messages,
            "count": len(messages),
            "history_version": session_summary.history_version if session_summary is not None else 0,
        }
    except RuntimeError:
        return {
            "user_id": user_id,
            "session_id": session_id,
            "messages": [],
            "count": 0,
            "history_version": 0,
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


@message_content_router.post("/history/clear")
async def clear_conversation_history(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
):
    """Clear conversation history."""
    resolved_session_id = require_session_id(session_id)
    cleared = await get_chat_forgetting_service().clear_history(
        user_id=user_id,
        session_id=resolved_session_id,
    )
    if not cleared:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {
        "success": True,
        "message": t("chat.history.cleared", fallback="Conversation history cleared"),
        "user_id": user_id,
        "session_id": resolved_session_id,
    }


__all__ = [
    "clear_conversation_history",
    "get_chat_attachment_content",
    "get_conversation_history",
    "get_execution_trace",
    "message_content_router",
    "upload_chat_attachment",
]
