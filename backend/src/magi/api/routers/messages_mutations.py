"""Message label and visibility mutation routes."""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ...runtime_defaults import DEFAULT_USER_ID
from .messages_common import legacy_messages_module
from .messages_models import MessageLabelRequest

message_mutations_router = APIRouter()


@message_mutations_router.post("/session/{session_id}/message/{message_id}/label", response_model=Dict[str, Any])
async def set_message_label(
    session_id: str,
    message_id: str,
    request: MessageLabelRequest,
):
    """Persist one compact label on an existing chat message."""
    legacy = legacy_messages_module()
    try:
        chat_store = legacy.get_chat_store()
        created_at_ms = int(request.created_at_ms or int(time.time() * 1000))
        label = {
            "kind": str(request.kind).strip(),
            "text": str(request.text).strip(),
            "applied_by": str(request.applied_by).strip(),
            "source": str(request.source).strip(),
            "created_at_ms": created_at_ms,
        }
        message = await chat_store.update_message_label(
            session_id=session_id,
            message_id=message_id,
            label=label,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    from ...transport.chat_events import broadcast_chat_message_upsert

    await broadcast_chat_message_upsert(
        user_id=request.user_id,
        session_id=session_id,
        message_id=message_id,
    )

    return {
        "success": True,
        "message": "Message label updated",
        "data": {
            "user_id": request.user_id,
            "session_id": session_id,
            "message_id": message_id,
            "label": label,
        },
    }


@message_mutations_router.delete("/session/{session_id}/message/{message_id}", response_model=Dict[str, Any])
async def delete_message(session_id: str, message_id: str, user_id: str = DEFAULT_USER_ID):
    """Soft-delete one chat message from the visible transcript."""
    legacy = legacy_messages_module()
    try:
        chat_store = legacy.get_chat_store()
        message = await chat_store.hide_message(
            session_id=session_id,
            message_id=message_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    from ...transport.chat_events import broadcast_chat_message_hidden

    await broadcast_chat_message_hidden(
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
    )

    return {
        "success": True,
        "user_id": user_id,
        "session_id": session_id,
        "deleted_message_id": message_id,
    }


__all__ = ["delete_message", "message_mutations_router", "set_message_label"]