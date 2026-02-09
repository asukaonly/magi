"""
用户消息API路由

接收和处理用户消息
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter()


# 全局用户消息传感器实例
_user_message_sensor = None


class UserMessageRequest(BaseModel):
    """用户消息请求"""
    message: str = Field(..., description="用户消息内容", min_length=1)
    user_id: Optional[str] = Field(default="anonymous", description="用户ID")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="额外元数据")


class MessageResponse(BaseModel):
    """消息响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


def get_user_message_sensor():
    """获取全局用户消息传感器实例"""
    global _user_message_sensor
    if _user_message_sensor is None:
        from magi.awareness.sensors import UserMessageSensor
        _user_message_sensor = UserMessageSensor()
        logger.info("Created global UserMessageSensor instance")
    return _user_message_sensor


@router.post("/send", response_model=MessageResponse)
async def send_user_message(request: UserMessageRequest):
    """
    发送用户消息

    接收用户消息并转发给感知系统

    Args:
        request: 用户消息请求

    Returns:
        消息响应
    """
    try:
        sensor = get_user_message_sensor()

        # 构建完整消息
        full_message = {
            "content": request.message,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "metadata": request.metadata or {},
        }

        # 发送到传感器
        await sensor.send_message(request.message)

        logger.info(f"Received user message from {request.user_id}: {request.message[:50]}...")

        return MessageResponse(
            success=True,
            message="Message received successfully",
            data={
                "user_id": request.user_id,
                "message_length": len(request.message),
                "timestamp": asyncio.get_event_loop().time(),
            }
        )

    except Exception as e:
        logger.exception(f"Error processing user message: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process message: {str(e)}")


@router.get("/sensor/status", response_model=Dict[str, Any])
async def get_sensor_status():
    """
    获取传感器状态

    Returns:
        传感器状态信息
    """
    sensor = get_user_message_sensor()

    return {
        "sensor_type": "UserMessageSensor",
        "enabled": sensor.enabled,
        "perception_type": sensor.perception_type.value,
        "trigger_mode": sensor.trigger_mode.value,
        "queue_size": sensor.get_queue().qsize(),
    }


@router.post("/sensor/enable")
async def enable_sensor():
    """启用传感器"""
    sensor = get_user_message_sensor()
    sensor.enable()
    logger.info("UserMessageSensor enabled")

    return {"success": True, "message": "Sensor enabled"}


@router.post("/sensor/disable")
async def disable_sensor():
    """禁用传感器"""
    sensor = get_user_message_sensor()
    sensor.disable()
    logger.info("UserMessageSensor disabled")

    return {"success": True, "message": "Sensor disabled"}


# 导出路由器
user_messages_router = router
