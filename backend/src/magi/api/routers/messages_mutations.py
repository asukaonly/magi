"""Message label and visibility mutation routes."""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ... import i18n as core_i18n
from ...chat.forgetting import get_chat_forgetting_service
from ...core.runtime_bindings import require_chat_surface_write_service
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from .messages_models import MessageLabelRequest

message_mutations_router = APIRouter()


@message_mutations_router.post(
    "/session/{session_id}/message/{message_id}/label", response_model=Dict[str, Any]
)
async def set_message_label(
    session_id: str,
    message_id: str,
    request: MessageLabelRequest,
):
    """Persist one compact label on an existing chat message."""
    try:
        created_at_ms = int(request.created_at_ms or int(time.time() * 1000))
        label = {
            "kind": str(request.kind).strip(),
            "text": str(request.text).strip(),
            "applied_by": str(request.applied_by).strip(),
            "source": str(request.source).strip(),
            "created_at_ms": created_at_ms,
        }
        updated = await require_chat_surface_write_service().set_message_label(
            user_id=request.user_id,
            session_id=session_id,
            message_id=message_id,
            label=label,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not updated:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t("chat.messages.not_found", fallback="Message not found"),
        )

    return {
        "success": True,
        "message": core_i18n.t("chat.messages.label_updated", fallback="Message label updated"),
        "data": {
            "user_id": request.user_id,
            "session_id": session_id,
            "message_id": message_id,
            "label": label,
        },
    }


@message_mutations_router.delete(
    "/session/{session_id}/message/{message_id}", response_model=Dict[str, Any]
)
async def delete_message(session_id: str, message_id: str, user_id: str = DEFAULT_USER_ID):
    """Soft-delete one chat message from the visible transcript."""
    try:
        deleted = await get_chat_forgetting_service().delete_message(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t("chat.messages.not_found", fallback="Message not found"),
        )

    return {
        "success": True,
        "user_id": user_id,
        "session_id": session_id,
        "deleted_message_id": message_id,
    }


__all__ = ["delete_message", "message_mutations_router", "set_message_label"]
