"""Chat session management routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Dict

from fastapi import APIRouter, HTTPException, Query

from ...core.chat_cleanup import ChatSurfaceCleanupPendingError
from ...core.runtime_bindings import (
    require_chat_forgetting_service,
    require_chat_read_service,
)
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from .messages_common import get_default_chat_workspace_path
from .messages_models import (
    DeleteSessionResponse,
    RenameSessionRequest,
    UpdateSessionWorkspaceRequest,
)

message_sessions_router = APIRouter()


@message_sessions_router.post("/session/new", response_model=Dict[str, Any])
async def create_new_session(
    user_id: str = DEFAULT_USER_ID,
    idempotency_key: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ] = None,
):
    """Create a new chat session row for the given user."""
    try:
        read_service = require_chat_read_service()
        workspace_path = get_default_chat_workspace_path()
        session_id = await read_service.acreate_new_session(
            user_id,
            workspace_path,
            idempotency_key,
        )
        return {
            "success": True,
            "user_id": user_id,
            "session_id": session_id,
            "workspace_path": workspace_path,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError:
        return {
            "success": False,
            "user_id": user_id,
            "session_id": None,
            "workspace_path": None,
        }


@message_sessions_router.patch("/session/{session_id}", response_model=Dict[str, Any])
async def rename_session(session_id: str, request: RenameSessionRequest):
    """Rename a session and persist the title override."""
    try:
        read_service = require_chat_read_service()
        session = await read_service.arename_session(request.user_id, session_id, request.title)
        return {
            "success": True,
            "user_id": request.user_id,
            "session": session.to_dict(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@message_sessions_router.patch("/session/{session_id}/workspace", response_model=Dict[str, Any])
async def update_session_workspace(session_id: str, request: UpdateSessionWorkspaceRequest):
    """Update the persisted workspace path for a chat session."""
    try:
        read_service = require_chat_read_service()
        session = await read_service.aupdate_session_workspace(
            request.user_id,
            session_id,
            request.workspace_path,
        )
        return {
            "success": True,
            "user_id": request.user_id,
            "session": asdict(session),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@message_sessions_router.delete(
    "/session/{session_id}",
    response_model=DeleteSessionResponse,
)
async def delete_session(session_id: str, user_id: str = DEFAULT_USER_ID):
    """Delete one session and its related chat data."""
    cleanup_pending = False
    try:
        deleted = await require_chat_forgetting_service().delete_session(
            user_id=user_id,
            session_id=session_id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "success": True,
            "user_id": user_id,
            "deleted_session_id": session_id,
            "cleanup_pending": cleanup_pending,
        }
    except ChatSurfaceCleanupPendingError as exc:
        if exc.session_id != session_id:
            raise
        return {
            "success": True,
            "user_id": user_id,
            "deleted_session_id": session_id,
            "cleanup_pending": True,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@message_sessions_router.get("/sessions", response_model=Dict[str, Any])
async def list_sessions(
    user_id: str = DEFAULT_USER_ID,
    limit: int = Query(default=30, ge=1, le=200),
):
    """List recent chat sessions for the given user."""
    try:
        read_service = require_chat_read_service()
        sessions = await read_service.alist_sessions(user_id=user_id, limit=limit)
        return {
            "user_id": user_id,
            "sessions": [session.to_dict() for session in sessions],
            "count": len(sessions),
        }
    except RuntimeError:
        return {
            "user_id": user_id,
            "sessions": [],
            "count": 0,
        }


__all__ = [
    "create_new_session",
    "delete_session",
    "list_sessions",
    "message_sessions_router",
    "rename_session",
    "update_session_workspace",
]
