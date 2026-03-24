"""Messages API router."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import time

from ..services import dispatch_user_message, get_chat_trace_read_service
from ...chat import SessionWorkspaceUpdateResult, get_chat_read_service
from ...utils.agent_logger import get_agent_logger
from ...core.logger import get_logger
from ...runtime_defaults import DEFAULT_RUNTIME_NAMESPACE, DEFAULT_USER_ID

logger = get_logger(__name__)
agent_logger = get_agent_logger('api')

user_messages_router = APIRouter()

# ============ data Models ============

class UserMessageRequest(BaseModel):
    """User message request."""
    message: str = Field(..., description="User message content")
    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    client_turn_id: Optional[str] = Field(None, description="Optional client-generated turn id")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="metadata")


class MessageResponse(BaseModel):
    """Message response."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class RenameSessionRequest(BaseModel):
    """Session rename request."""
    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    title: str = Field(..., description="New session title")


class UpdateSessionWorkspaceRequest(BaseModel):
    """Session workspace update request."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    workspace_path: Optional[str] = Field(default=None, description="Workspace path for the session")


# ============ API Endpoints ============


def _require_session_id(session_id: str | None) -> str:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Session ID is required")
    return normalized


def _get_default_chat_workspace_path() -> str | None:
    from .config import _build_system_config

    config = _build_system_config()
    normalized_workspace_path = str(config.preferences.default_chat_workspace_path or "").strip()
    return normalized_workspace_path or None


@user_messages_router.post("/send", response_model=MessageResponse)
async def send_user_message(
    request: UserMessageRequest,
):
    try:
        outcome = await dispatch_user_message(
            source="api",
            user_id=request.user_id,
            message=request.message,
            session_id=request.session_id,
            client_turn_id=request.client_turn_id,
            metadata=request.metadata or {},
            runtime_namespace=str((request.metadata or {}).get("runtime_namespace") or DEFAULT_RUNTIME_NAMESPACE),
        )
        if not outcome.success:
            agent_logger.warning(
                f"Message dispatch rejected | User: {request.user_id} | code: {outcome.error_code}"
            )
            return MessageResponse(
                success=False,
                message=outcome.error_message or "Failed to queue message",
                data={
                    "user_id": request.user_id,
                    "session_id": outcome.session_id,
                    "error": outcome.error_message,
                    "error_code": outcome.error_code,
                },
            )

        logger.info(
            "Message from %s published to message bus | Queue size: %s",
            request.user_id,
            outcome.queue_size if outcome.queue_size is not None else "unknown",
        )

        agent_logger.info(f"📥 Message received | User: {request.user_id} | Content: '{request.message[:50]}{'...' if len(request.message) > 50 else ''}' | Length: {len(request.message)}")

        return MessageResponse(
            success=True,
            message="Message queued for processing",
            data={
                "user_id": request.user_id,
                "session_id": outcome.session_id,
                "turn_id": outcome.turn_id,
                "message_length": len(request.message),
                "timestamp": time.time(),
            }
        )
    except Exception as e:
        logger.error(f"Failed to queue message: {e}")
        agent_logger.error(f"❌ Queue failed | User: {request.user_id} | error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@user_messages_router.get("/history", response_model=Dict[str, Any])
async def get_conversation_history(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
):
    """
    Get conversation history.

    Args:
        user_id: User ID.

    Returns:
        Dialogue history for the session.
    """
    try:
        read_service = get_chat_read_service()
        resolved_session_id = _require_session_id(session_id)
        history = await read_service.aget_display_history(user_id, resolved_session_id)

        # Convert to format expected by frontend
        messages = [msg.to_dict() for msg in history]

        return {
            "user_id": user_id,
            "session_id": resolved_session_id,
            "messages": messages,
            "count": len(messages)
        }
    except RuntimeError:
        # Agent not initialized; return empty history
        return {
            "user_id": user_id,
            "session_id": session_id,
            "messages": [],
            "count": 0
        }


@user_messages_router.get("/trace", response_model=Dict[str, Any])
async def get_execution_trace(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
    turn_id: str = Query(..., description="Turn ID for the target user message"),
):
    """Get structured execution trace for one chat turn."""
    read_service = get_chat_read_service()
    resolved_session_id = _require_session_id(session_id)
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


@user_messages_router.post("/history/clear")
async def clear_conversation_history(
    user_id: str = DEFAULT_USER_ID,
    session_id: Optional[str] = Query(default=None, description="Session ID"),
):
    """
    Clear conversation history.

    Args:
        user_id: User ID.

    Returns:
        Operation result.
    """
    try:
        read_service = get_chat_read_service()
        resolved_session_id = _require_session_id(session_id)
        await read_service.aclear_conversation_history(user_id, resolved_session_id)

        return {
            "success": True,
            "message": "Conversation history cleared",
            "user_id": user_id,
            "session_id": resolved_session_id,
        }
    except RuntimeError:
        # Agent not initialized
        return {
            "success": True,
            "message": "Conversation history cleared (agent not initialized)",
            "user_id": user_id,
            "session_id": session_id,
        }


@user_messages_router.post("/session/new", response_model=Dict[str, Any])
async def create_new_session(user_id: str = DEFAULT_USER_ID):
    """Create a new chat session row for the given user."""
    try:
        read_service = get_chat_read_service()
        workspace_path = _get_default_chat_workspace_path()
        session_id = await read_service.acreate_new_session(user_id, workspace_path)
        return {
            "success": True,
            "user_id": user_id,
            "session_id": session_id,
            "workspace_path": workspace_path,
        }
    except RuntimeError:
        return {
            "success": False,
            "user_id": user_id,
            "session_id": None,
            "workspace_path": None,
        }


@user_messages_router.patch("/session/{session_id}", response_model=Dict[str, Any])
async def rename_session(session_id: str, request: RenameSessionRequest):
    """Rename a session and persist the title override."""
    try:
        read_service = get_chat_read_service()
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


@user_messages_router.patch("/session/{session_id}/workspace", response_model=Dict[str, Any])
async def update_session_workspace(session_id: str, request: UpdateSessionWorkspaceRequest):
    """Update the persisted workspace path for a chat session."""
    try:
        read_service = get_chat_read_service()
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


@user_messages_router.delete("/session/{session_id}", response_model=Dict[str, Any])
async def delete_session(session_id: str, user_id: str = DEFAULT_USER_ID):
    """Delete one session and its related chat data."""
    try:
        read_service = get_chat_read_service()
        await read_service.adelete_session(user_id, session_id)
        return {
            "success": True,
            "user_id": user_id,
            "deleted_session_id": session_id,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@user_messages_router.get("/sessions", response_model=Dict[str, Any])
async def list_sessions(
    user_id: str = DEFAULT_USER_ID,
    limit: int = Query(default=30, ge=1, le=200),
):
    """List recent chat sessions for the given user."""
    try:
        read_service = get_chat_read_service()
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
