"""
messageAPIroute

提供User messagesend、dialoguehistory等function
使用正确的Agentarchitecture：message → MessageBus → Perception器subscribe → PerceptionManager → LoopEngine → Agentprocess → WebSocketpush
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import time
import asyncio

from ..websocket import manager as ws_manager
from ...awareness.sensors import UserMessageSensor
from ...utils.agent_logger import get_agent_logger
from ...events.events import Event, EventTypes, EventLevel
from ...core.logger import get_logger

logger = get_logger(__name__)
agent_logger = get_agent_logger('api')

user_messages_router = APIRouter()

# ============ data Models ============

class UserMessageRequest(BaseModel):
    """User messagerequest"""
    message: str = Field(..., description="User messageContent")
    user_id: str = Field(default="web_user", description="userid")
    session_id: Optional[str] = Field(None, description="sessionid")
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
    """getmessage busInstance"""
    return _message_bus


# ============ globalUser message传感器 ============

# globalUser message传感器Instance（单例）
_user_message_sensor: Optional[UserMessageSensor] = None


def get_user_message_sensor() -> UserMessageSensor:
    """get或createUser message传感器Instance"""
    global _user_message_sensor
    if _user_message_sensor is None:
        _user_message_sensor = UserMessageSensor()
        logger.info("UserMessageSensor created")
    return _user_message_sensor


# ============ dialoguehistorystorage ============

# simple的dialoguehistorystorage（内存中）
_conversation_history = {}  # {user_id: [messages]}


# ============ API Endpoints ============

@user_messages_router.post("/send", response_model=MessageResponse)
async def send_user_message(request: UserMessageRequest):
    """
    sendUser message到message bus

    message将被作为eventrelease到message bus，由subscribe者（Perception器）receive并process

    Args:
        request: User messagerequest

    Returns:
        确认response
    """
    try:
        # check ChatAgent is not已initialize
        from ...agent import get_chat_agent
        try:
            chat_agent = get_chat_agent()
        except RuntimeError:
            # Agent 未initialize（可能is没有Setting API Key）
            agent_logger.warning(f"⚠️ ChatAgent not initialized when user {request.user_id} sent message")

            # senderror message到 WebSocket
            await ws_manager.broadcast_to_user(request.user_id, {
                "type": "error",
                "content": "AI service未initialize。请Setting LLM_API_KEY 环境Variable后重启service。",
                "timestamp": time.time(),
            })

            return MessageResponse(
                success=False,
                message="ChatAgent not initialized. Please set LLM_API_KEY environment variable.",
                data={
                    "user_id": request.user_id,
                    "error": "ChatAgent not initialized",
                }
            )

        message_bus = get_message_bus()

        # parsesessionid（未指scheduled使用currentsession）
        session_id = request.session_id or chat_agent.get_current_session_id(request.user_id)

        # buildmessagedata
        message_data = {
            "message": request.message,
            "user_id": request.user_id,
            "session_id": session_id,
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
        from ...agent import get_chat_agent

        agent = get_chat_agent()
        resolved_session_id = agent.get_current_session_id(user_id) if not session_id else session_id
        history = agent.get_conversation_history(user_id, resolved_session_id)

        # convert为前端expectation的format
        messages = []
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": int(time.time()),  # 使用current时间，因为history中没有savetimestamp
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
        from ...agent import get_chat_agent

        agent = get_chat_agent()
        resolved_session_id = agent.get_current_session_id(user_id) if not session_id else session_id
        agent.clear_conversation_history(user_id, resolved_session_id)

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
        from ...agent import get_chat_agent
        agent = get_chat_agent()
        session_id = agent.get_current_session_id(user_id)
        return {"user_id": user_id, "session_id": session_id}
    except RuntimeError:
        return {"user_id": user_id, "session_id": None}


@user_messages_router.post("/session/new", response_model=Dict[str, Any])
async def create_new_session(user_id: str = "web_user"):
    """createnewsession并切换为currentsession"""
    try:
        from ...agent import get_chat_agent
        agent = get_chat_agent()
        session_id = agent.create_new_session(user_id)
        return {"success": True, "user_id": user_id, "session_id": session_id}
    except RuntimeError:
        return {"success": False, "user_id": user_id, "session_id": None}


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
