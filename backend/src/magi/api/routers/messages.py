"""
Messages API router.

Provides user message send, dialogue history, and related endpoints.

Architecture flow:
    HTTP Request → MessageBus (USER_MESSAGE event) → Agent processing →
    MessageBus (AI_RESPONSE event) → WebSocketBridge → WebSocket clients

This router is transport-pure: it only handles HTTP input/output and event publishing.
All WebSocket communication is handled by the WebSocketBridge lifecycle module,
which subscribes to MessageBus events and broadcasts to connected clients.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import time
import asyncio
import uuid

from dependency_injector.wiring import inject, Provide

from ...awareness.sensors import UserMessageSensor
from ..services import get_chat_read_service
from ...events.service_access import (
    get_message_bus as _get_message_bus_service,
    set_message_bus as _set_message_bus_service,
)
from ...utils.agent_logger import get_agent_logger
from ...events.events import Event, EventTypes, EventLevel
from ...core.logger import get_logger
from ...core.container import Container

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


def set_message_bus(message_bus):
    """Compatibility wrapper for shared message bus service."""
    _set_message_bus_service(message_bus)


def get_message_bus():
    """Compatibility wrapper for shared message bus service."""
    return _get_message_bus_service()


# ============ Global user message sensor ============

# Global user message sensor instance (singleton)
_user_message_sensor: Optional[UserMessageSensor] = None


def get_user_message_sensor() -> UserMessageSensor:
    """Get or create the global user message sensor instance."""
    global _user_message_sensor
    # Try container first
    try:
        from ...core.container import get_container
        container = get_container()
        instance = container.user_message_sensor()
        if instance is not None and type(instance).__name__ != "object":
            return instance
    except Exception:
        pass
    # Fallback to creating one
    if _user_message_sensor is None:
        _user_message_sensor = UserMessageSensor()
        logger.info("UserMessageSensor created")
    return _user_message_sensor


# ============ Dialogue history storage ============

# In-memory dialogue history storage: {user_id: [messages]}
_conversation_history = {}


# ============ API Endpoints ============


@user_messages_router.post("/send", response_model=MessageResponse)
@inject
async def send_user_message(
    request: UserMessageRequest,
    message_bus = Depends(Provide[Container.message_bus]),
):
    """
    Send user message to the message bus.

    The message is published as an event; subscribers (e.g. perception sensors) receive and process it.

    Args:
        request: User message request.
        message_bus: Injected message bus (via DI container).

    Returns:
        Acknowledgment response.
    """
    try:
        # check runtime is initialized
        from ...agent import get_agent_runtime
        try:
            get_agent_runtime()
        except RuntimeError:
            # Agent not initialized (e.g. API key not set)
            # Return error via HTTP response - frontend should handle display
            # WebSocket broadcast is handled by WebSocketBridge, not here
            agent_logger.warning(f"AgentRuntime not initialized when user {request.user_id} sent message")

            return MessageResponse(
                success=False,
                message="AgentRuntime not initialized. Please complete onboarding or check the saved configuration.",
                data={
                    "user_id": request.user_id,
                    "error": "AgentRuntime not initialized",
                    "error_code": "RUNTIME_NOT_INITIALIZED",
                }
            )

        # Fallback to global if injection didn't provide a valid instance
        if message_bus is None or type(message_bus).__name__ == "object":
            message_bus = get_message_bus()

        # Resolve session_id (use current session if not provided)
        read_service = get_chat_read_service()
        session_id = request.session_id or read_service.get_current_session_id(request.user_id)

        # Build message payload
        message_data = {
            "message": request.message,
            "user_id": request.user_id,
            "session_id": session_id,
            "turn_id": request.client_turn_id or f"turn_{uuid.uuid4().hex[:12]}",
            "metadata": request.metadata,
            "timestamp": time.time(),
        }

        # Publish event via message bus when available
        if message_bus:
            event = Event(
                type=EventTypes.USER_MESSAGE,
                data=message_data,
                source="api",
                level=EventLevel.INFO,
            )
            published = await message_bus.publish(event)
            if not published:
                logger.error("Message bus publish failed")
                return MessageResponse(
                    success=False,
                    message="Message bus publish failed",
                    data={
                        "user_id": request.user_id,
                        "session_id": session_id,
                    },
                )

            queue_size = "unknown"
            stats = await message_bus.get_stats()
            if stats:
                queue_size = stats.get("queue_size", 0)

            logger.info(f"Message from {request.user_id} published to message bus | Queue size: {queue_size}")
        else:
            logger.error("Message bus not initialized")
            return MessageResponse(
                success=False,
                message="Message bus not initialized",
                data={"user_id": request.user_id, "session_id": session_id},
            )

        agent_logger.info(f"📥 Message received | User: {request.user_id} | Content: '{request.message[:50]}{'...' if len(request.message) > 50 else ''}' | Length: {len(request.message)}")

        return MessageResponse(
            success=True,
            message="Message queued for processing",
            data={
                "user_id": request.user_id,
                "session_id": session_id,
                "turn_id": message_data["turn_id"],
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
        messages = []
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": int(msg.get("timestamp", time.time())),
                "turn_id": msg.get("turn_id"),
                "kind": msg.get("kind"),
                "trace_summary": msg.get("trace_summary"),
                "trace_available": bool(msg.get("trace_available")),
            })

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
            "sessions": sessions,
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
    sensor = get_user_message_sensor()

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
    sensor = get_user_message_sensor()
    sensor.enable()
    return {"success": True, "message": "Sensor enabled"}


@user_messages_router.post("/sensor/disable")
async def disable_sensor():
    """Disable the sensor."""
    sensor = get_user_message_sensor()
    sensor.disable()
    return {"success": True, "message": "Sensor disabled"}
