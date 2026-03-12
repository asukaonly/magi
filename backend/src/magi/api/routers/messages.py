"""
messageAPIroute

提供User messagesend、dialoguehistory等function
使用正确的Agentarchitecture：message → MessageBus → Perception器subscribe → PerceptionManager → LoopEngine → Agentprocess → WebSocketpush
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import time
import asyncio

from dependency_injector.wiring import inject, Provide

from ..connection_manager import manager as ws_manager
from ...awareness.sensors import UserMessageSensor
from ..services import get_chat_read_service
from ...utils.agent_logger import get_agent_logger
from ...events.events import Event, EventTypes, EventLevel
from ...core.logger import get_logger
from ...core.container import Container

logger = get_logger(__name__)
agent_logger = get_agent_logger('api')

user_messages_router = APIRouter()

# ============ data Models ============

class UserMessageRequest(BaseModel):
    """User messagerequest"""
    message: str = Field(..., description="User messageContent")
    user_id: str = Field(default="web_user", description="userid")
    session_id: Optional[str] = Field(None, description="sessionid")
    client_turn_id: Optional[str] = Field(None, description="Optional client-generated turn id")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="metadata")


class MessageResponse(BaseModel):
    """messageresponse"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============ globalmessage bus ============

_message_bus = None


def set_message_bus(message_bus):
    """Settingmessage busInstance"""
    global _message_bus
    _message_bus = message_bus


def get_message_bus():
    """getmessage busInstance - checks DI container first, falls back to global."""
    # Try container first
    try:
        from ...core.container import get_container
        container = get_container()
        instance = container.message_bus()
        # Check if it's a real instance (not the placeholder object)
        if instance is not None and type(instance).__name__ != "object":
            return instance
    except Exception:
        pass
    # Fallback to global
    return _message_bus


# ============ globalUser message传感器 ============

# globalUser message传感器Instance（单例）
_user_message_sensor: Optional[UserMessageSensor] = None


def get_user_message_sensor() -> UserMessageSensor:
    """get或createUser message传感器Instance"""
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


# ============ dialoguehistorystorage ============

# simple的dialoguehistorystorage（内存中）
_conversation_history = {}  # {user_id: [messages]}


# ============ API Endpoints ============


@user_messages_router.post("/send", response_model=MessageResponse)
@inject
async def send_user_message(
    request: UserMessageRequest,
    message_bus = Depends(Provide[Container.message_bus]),
):
    """
    sendUser message到message bus

    message将被作为eventrelease到message bus，由subscribe者（Perception器）receive并process

    Args:
        request: User messagerequest
        message_bus: Injected message bus (via DI container)

    Returns:
        确认response
    """
    try:
        # check runtime is initialized
        from ...agent import get_agent_runtime
        try:
            get_agent_runtime()
        except RuntimeError:
            # Agent 未initialize（可能is没有Setting API Key）
            agent_logger.warning(f"⚠️ AgentRuntime not initialized when user {request.user_id} sent message")

            # senderror message到 WebSocket
            await ws_manager.broadcast_to_user(request.user_id, {
                "type": "error",
                "content": "AI service 未初始化。请先完成引导配置或检查当前配置后重启服务。",
                "timestamp": time.time(),
            })

            return MessageResponse(
                success=False,
                message="AgentRuntime not initialized. Please complete onboarding or check the saved configuration.",
                data={
                    "user_id": request.user_id,
                    "error": "AgentRuntime not initialized",
                }
            )

        # Fallback to global if injection didn't provide a valid instance
        if message_bus is None or type(message_bus).__name__ == "object":
            message_bus = get_message_bus()

        # parsesessionid（未指scheduled使用currentsession）
        read_service = get_chat_read_service()
        session_id = request.session_id or read_service.get_current_session_id(request.user_id)

        # buildmessagedata
        message_data = {
            "message": request.message,
            "user_id": request.user_id,
            "session_id": session_id,
            "turn_id": request.client_turn_id or f"turn_{uuid.uuid4().hex[:12]}",
            "metadata": request.metadata,
            "timestamp": time.time(),
        }

        # 如果 message bus 可用，通过 message bus 发布事件
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
    session_id: Optional[str] = Query(default=None, description="sessionid，不传则使用currentsession"),
):
    """
    getdialoguehistory

    Args:
        user_id: userid

    Returns:
        dialoguehistory
    """
    try:
        read_service = get_chat_read_service()
        resolved_session_id = session_id or read_service.get_current_session_id(user_id)
        history = read_service.get_display_history(user_id, resolved_session_id)

        # convert为前端expectation的format
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
        # Agent未initialize，Return空history
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
    session_id: Optional[str] = Query(default=None, description="sessionid，不传则使用currentsession"),
    turn_id: str = Query(..., description="turn id for the target user message"),
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
    session_id: Optional[str] = Query(default=None, description="sessionid，不传则clearcurrentsession"),
):
    """
    cleardialoguehistory

    Args:
        user_id: userid

    Returns:
        operationResult
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
        # Agent未initialize
        return {
            "success": True,
            "message": "Conversation history cleared (nottt agent initialized)",
            "user_id": user_id,
            "session_id": session_id,
        }


@user_messages_router.get("/session/current", response_model=Dict[str, Any])
async def get_current_session(user_id: str = "web_user"):
    """getcurrentsessionid"""
    try:
        read_service = get_chat_read_service()
        session_id = read_service.get_current_session_id(user_id)
        return {"user_id": user_id, "session_id": session_id}
    except RuntimeError:
        return {"user_id": user_id, "session_id": None}


@user_messages_router.post("/session/new", response_model=Dict[str, Any])
async def create_new_session(user_id: str = "web_user"):
    """createnewsession并切换为currentsession"""
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
    get传感器State

    Returns:
        传感器Stateinfo
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
    """Enable传感器"""
    sensor = get_user_message_sensor()
    sensor.enable()
    return {"success": True, "message": "Sensor enabled"}


@user_messages_router.post("/sensor/disable")
async def disable_sensor():
    """Disable传感器"""
    sensor = get_user_message_sensor()
    sensor.disable()
    return {"success": True, "message": "Sensor disabled"}
