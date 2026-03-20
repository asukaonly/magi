"""Messages API router."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import time

from ..services import dispatch_user_message, get_chat_read_service, require_user_message_sensor
from ...utils.agent_logger import get_agent_logger
from ...core.logger import get_logger

logger = get_logger(__name__)
agent_logger = get_agent_logger('api')

user_messages_router = APIRouter()

# ============ data Models ============

class UserMessageRequest(BaseModel):
    """User message request."""
    message: str = Field(..., description="User message content")
    user_id: str = Field(default="web_user", description="User ID")
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
    user_id: str = Field(default="web_user", description="User ID")
    title: str = Field(..., description="New session title")


# ============ API Endpoints ============


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
            runtime_namespace=str((request.metadata or {}).get("runtime_namespace") or "web"),
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
    user_id: str = "web_user",
    session_id: Optional[str] = Query(default=None, description="Session ID; omit to use current session"),
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
        resolved_session_id = session_id or read_service.get_current_session_id(user_id)
        history = read_service.get_display_history(user_id, resolved_session_id)

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


@user_messages_router.get("/worker/{worker_id}", response_model=Dict[str, Any])
async def get_worker_result(worker_id: str, user_id: str = "web_user"):
    """Get the full structured result for one worker."""
    read_service = get_chat_read_service()
    result = read_service.get_worker_result(worker_id)
    return {
        "success": result is not None,
        "worker_id": worker_id,
        "user_id": user_id,
        "result": result,
    }


@user_messages_router.get("/trace", response_model=Dict[str, Any])
async def get_execution_trace(
    user_id: str = "web_user",
    session_id: Optional[str] = Query(default=None, description="Session ID; omit to use current session"),
    turn_id: str = Query(..., description="Turn ID for the target user message"),
):
    """Get structured execution trace for one chat turn."""
    from ..services import get_chat_trace_read_service

    read_service = get_chat_read_service()
    resolved_session_id = session_id or read_service.get_current_session_id(user_id)
    trace_service = get_chat_trace_read_service()
    snapshot = trace_service.get_trace_snapshot(
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
    user_id: str = "web_user",
    session_id: Optional[str] = Query(default=None, description="Session ID; omit to clear current session"),
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
        resolved_session_id = session_id or read_service.get_current_session_id(user_id)
        read_service.clear_conversation_history(user_id, resolved_session_id)

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


@user_messages_router.get("/session/current", response_model=Dict[str, Any])
async def get_current_session(user_id: str = "web_user"):
    """Get current session ID."""
    try:
        read_service = get_chat_read_service()
        session_id = read_service.get_current_session_id(user_id)
        return {"user_id": user_id, "session_id": session_id}
    except RuntimeError:
        return {"user_id": user_id, "session_id": None}


@user_messages_router.post("/session/new", response_model=Dict[str, Any])
async def create_new_session(user_id: str = "web_user"):
    """Create a new session and set it as the current session."""
    try:
        read_service = get_chat_read_service()
        session_id = read_service.create_new_session(user_id)
        return {"success": True, "user_id": user_id, "session_id": session_id}
    except RuntimeError:
        return {"success": False, "user_id": user_id, "session_id": None}


@user_messages_router.patch("/session/{session_id}", response_model=Dict[str, Any])
async def rename_session(session_id: str, request: RenameSessionRequest):
    """Rename a session and persist the title override."""
    try:
        read_service = get_chat_read_service()
        session = read_service.rename_session(request.user_id, session_id, request.title)
        return {
            "success": True,
            "user_id": request.user_id,
            "session": session.to_dict(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@user_messages_router.delete("/session/{session_id}", response_model=Dict[str, Any])
async def delete_session(session_id: str, user_id: str = "web_user"):
    """Delete one session and rotate current session when necessary."""
    try:
        read_service = get_chat_read_service()
        current_session_id = read_service.delete_session(user_id, session_id)
        return {
            "success": True,
            "user_id": user_id,
            "deleted_session_id": session_id,
            "current_session_id": current_session_id,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@user_messages_router.get("/sessions", response_model=Dict[str, Any])
async def list_sessions(
    user_id: str = "web_user",
    limit: int = Query(default=30, ge=1, le=200),
):
    """List recent chat sessions for the given user."""
    try:
        read_service = get_chat_read_service()
        sessions = read_service.list_sessions(user_id=user_id, limit=limit)
        current_session_id = read_service.get_current_session_id(user_id)
        return {
            "user_id": user_id,
            "current_session_id": current_session_id,
            "sessions": [session.to_dict() for session in sessions],
            "count": len(sessions),
        }
    except RuntimeError:
        return {
            "user_id": user_id,
            "current_session_id": None,
            "sessions": [],
            "count": 0,
        }


@user_messages_router.get("/sensor/status")
async def get_sensor_status():
    """
    Get sensor state.

    Returns:
        Sensor state info.
    """
    sensor = require_user_message_sensor()

    return {
        "sensor_type": "user_message",
        "enabled": sensor.enabled,
        "perception_type": sensor.perception_type.value,
        "trigger_mode": sensor.trigger_mode.value,
        "queue_size": sensor.get_queue().qsize(),
    }


@user_messages_router.post("/sensor/enable")
async def enable_sensor():
    """Enable the sensor."""
    sensor = require_user_message_sensor()
    sensor.enable()
    return {"success": True, "message": "Sensor enabled"}


@user_messages_router.post("/sensor/disable")
async def disable_sensor():
    """Disable the sensor."""
    sensor = require_user_message_sensor()
    sensor.disable()
    return {"success": True, "message": "Sensor disabled"}
