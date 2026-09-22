"""Chat session management routes."""

from __future__ import annotations

from dataclasses import asdict
import sqlite3
from typing import Annotated, Any, Dict

from fastapi import APIRouter, HTTPException, Query

from ...core.chat_cleanup import ChatSurfaceCleanupPendingError
from ...core.runtime_bindings import (
    require_chat_forgetting_service,
    require_chat_read_service,
)
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from ...chat.read.models import ChatSessionSummary
from .messages_common import get_default_chat_workspace_path, require_session_id
from .messages_models import (
    DeleteSessionResponse,
    RenameSessionRequest,
    UpdateSessionWorkspaceRequest,
    SessionPageResponse,
)
from ...chat.read.pagination import InvalidPageCursor, StalePageCursor

message_sessions_router = APIRouter()


@message_sessions_router.get("/session/{session_id}", response_model=ChatSessionSummary)
async def get_session(
    session_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """Read one owned active session independently of the recent-session page."""
    try:
        summary = await require_chat_read_service().aget_session_summary(
            user_id, require_session_id(session_id)
        )
    except (RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="Conversation session unavailable") from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return summary.to_dict()


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


@message_sessions_router.get("/sessions", response_model=SessionPageResponse)
async def list_sessions(
    user_id: str = DEFAULT_USER_ID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    known_revision: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
):
    """List recent chat sessions for the given user."""
    try:
        read_service = require_chat_read_service()
        return await read_service.alist_session_page(user_id, limit, before, known_revision)
    except StalePageCursor as exc:
        raise HTTPException(status_code=409, detail={"code": "stale_page_cursor", "message": str(exc)}) from exc
    except InvalidPageCursor as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_page_cursor", "message": str(exc)}) from exc
    except (RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="Conversation sessions unavailable") from exc


__all__ = [
    "create_new_session",
    "delete_session",
    "list_sessions",
    "get_session",
    "message_sessions_router",
    "rename_session",
    "update_session_workspace",
]
