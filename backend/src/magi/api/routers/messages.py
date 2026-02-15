"""
消息API路由

提供用户消息发送、对话历史等功能
使用正确的Agent架构：消息 → MessageBus → 感知器订阅 → PerceptionManager → LoopEngine → Agent处理 → WebSocket推送
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging
import time
import asyncio

from ..websocket import manager as ws_manager
from ...awareness.sensors import UserMessageSensor
from ...utils.agent_logger import get_agent_logger
from ...events.events import Event, EventTypes, EventLevel

logger = logging.getLogger(__name__)
agent_logger = get_agent_logger('api')

user_messages_router = APIRouter()

# ============ 数据模型 ============

class UserMessageRequest(BaseModel):
    """用户消息请求"""
    message: str = Field(..., description="用户消息内容")
    user_id: str = Field(default="web_user", description="用户ID")
    session_id: Optional[str] = Field(None, description="会话ID")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="元数据")


class MessageResponse(BaseModel):
    """消息响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============ 全局消息总线 ============

_message_bus = None


def set_message_bus(message_bus):
    """设置消息总线实例"""
    global _message_bus
    _message_bus = message_bus


def get_message_bus():
    """获取消息总线实例"""
    return _message_bus


# ============ 全局用户消息传感器 ============

# 全局用户消息传感器实例（单例）
_user_message_sensor: Optional[UserMessageSensor] = None


def get_user_message_sensor() -> UserMessageSensor:
    """获取或创建用户消息传感器实例"""
    global _user_message_sensor
    if _user_message_sensor is None:
        _user_message_sensor = UserMessageSensor()
        logger.info("UserMessageSensor created")
    return _user_message_sensor


# ============ 对话历史存储 ============

# 简单的对话历史存储（内存中）
_conversation_history = {}  # {user_id: [messages]}


# ============ API端点 ============

@user_messages_router.post("/send", response_model=MessageResponse)
async def send_user_message(request: UserMessageRequest):
    """
    发送用户消息到消息总线

    消息将被作为事件发布到消息总线，由订阅者（感知器）接收并处理

    Args:
        request: 用户消息请求

    Returns:
        确认响应
    """
    try:
        # 检查 ChatAgent 是否已初始化
        from ...agent import get_chat_agent
        try:
            chat_agent = get_chat_agent()
        except RuntimeError:
            # Agent 未初始化（可能是没有设置 API Key）
            agent_logger.warning(f"⚠️ ChatAgent not initialized when user {request.user_id} sent message")

            # 发送错误提示到 WebSocket
            await ws_manager.broadcast_to_user(request.user_id, {
                "type": "error",
                "content": "AI 服务未初始化。请设置 LLM_API_KEY 环境变量后重启服务。",
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

        # 解析会话ID（未指定时使用当前会话）
        session_id = request.session_id or chat_agent.get_current_session_id(request.user_id)

        # 构建消息数据
        message_data = {
            "message": request.message,
            "user_id": request.user_id,
            "session_id": session_id,
            "metadata": request.metadata,
            "timestamp": time.time(),
        }

        # 如果消息总线可用，通过消息总线发布事件
        if message_bus:
            event = Event(
                type=EventTypes.USER_MESSAGE,
                data=message_data,
                source="api",
                level=EventLevel.INFO,
            )
            await message_bus.publish(event)

            queue_size = "unknown"
            stats = await message_bus.get_stats()
            if stats:
                queue_size = stats.get("queue_size", 0)

            logger.info(f"Message from {request.user_id} published to message bus | Queue size: {queue_size}")
        else:
            # Fallback: 直接使用传感器队列（向后兼容）
            sensor = get_user_message_sensor()
            await sensor.send_message(message_data)
            logger.info(f"Message from {request.user_id} queued to sensor (fallback) | Queue size: {sensor.get_queue().qsize()}")

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
        agent_logger.error(f"❌ Queue failed | User: {request.user_id} | Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@user_messages_router.get("/history", response_model=Dict[str, Any])
async def get_conversation_history(
    user_id: str = "web_user",
    session_id: Optional[str] = Query(default=None, description="会话ID，不传则使用当前会话"),
):
    """
    获取对话历史

    Args:
        user_id: 用户ID

    Returns:
        对话历史
    """
    try:
        from ...agent import get_chat_agent

        agent = get_chat_agent()
        resolved_session_id = agent.get_current_session_id(user_id) if not session_id else session_id
        history = agent.get_conversation_history(user_id, resolved_session_id)

        # 转换为前端期望的格式
        messages = []
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": int(time.time()),  # 使用当前时间，因为历史中没有保存timestamp
            })

        return {
            "user_id": user_id,
            "session_id": resolved_session_id,
            "messages": messages,
            "count": len(messages)
        }
    except RuntimeError:
        # Agent未初始化，返回空历史
        return {
            "user_id": user_id,
            "session_id": session_id,
            "messages": [],
            "count": 0
        }


@user_messages_router.post("/history/clear")
async def clear_conversation_history(
    user_id: str = "web_user",
    session_id: Optional[str] = Query(default=None, description="会话ID，不传则清空当前会话"),
):
    """
    清空对话历史

    Args:
        user_id: 用户ID

    Returns:
        操作结果
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
        # Agent未初始化
        return {
            "success": True,
            "message": "Conversation history cleared (no agent initialized)",
            "user_id": user_id,
            "session_id": session_id,
        }


@user_messages_router.get("/session/current", response_model=Dict[str, Any])
async def get_current_session(user_id: str = "web_user"):
    """获取当前会话ID"""
    try:
        from ...agent import get_chat_agent
        agent = get_chat_agent()
        session_id = agent.get_current_session_id(user_id)
        return {"user_id": user_id, "session_id": session_id}
    except RuntimeError:
        return {"user_id": user_id, "session_id": None}


@user_messages_router.post("/session/new", response_model=Dict[str, Any])
async def create_new_session(user_id: str = "web_user"):
    """创建新会话并切换为当前会话"""
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
    获取传感器状态

    Returns:
        传感器状态信息
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
    """启用传感器"""
    sensor = get_user_message_sensor()
    sensor.enable()
    return {"success": True, "message": "Sensor enabled"}


@user_messages_router.post("/sensor/disable")
async def disable_sensor():
    """禁用传感器"""
    sensor = get_user_message_sensor()
    sensor.disable()
    return {"success": True, "message": "Sensor disabled"}
