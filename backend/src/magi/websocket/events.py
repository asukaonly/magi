"""
WebSocket事件推送

定义各种实时事件的推送函数
"""
import logging
from .server import ws_manager

logger = logging.getLogger(__name__)


async def broadcast_agent_state(agent_id: str, state: str, data: dict = None):
    """
    广播Agent状态更新

    Args:
        agent_id: Agent ID
        state: 新状态
        data: 额外数据
    """
    message = {
        "agent_id": agent_id,
        "state": state,
        "timestamp": __import__("time").time(),
    }

    if data:
        message.update(data)

    await ws_manager.broadcast(
        "agent_state_changed",
        message,
        room="agents"
    )

    logger.debug(f"Broadcasted agent state: {agent_id} -> {state}")


async def broadcast_task_state(task_id: str, state: str, data: dict = None):
    """
    广播任务状态更新

    Args:
        task_id: 任务ID
        state: 新状态
        data: 额外数据
    """
    message = {
        "task_id": task_id,
        "state": state,
        "timestamp": __import__("time").time(),
    }

    if data:
        message.update(data)

    await ws_manager.broadcast(
        "task_state_changed",
        message,
        room="tasks"
    )

    logger.debug(f"Broadcasted task state: {task_id} -> {state}")


async def broadcast_metrics(metrics: dict):
    """
    广播系统指标更新

    Args:
        metrics: 指标数据
    """
    message = {
        "metrics": metrics,
        "timestamp": __import__("time").time(),
    }

    await ws_manager.broadcast(
        "metrics_updated",
        message,
        room="metrics"
    )

    logger.debug("Broadcasted metrics update")


async def broadcast_log(level: str, message: str, source: str = None):
    """
    广播日志消息

    Args:
        level: 日志级别（info/warning/error）
        message: 日志消息
        source: 日志来源
    """
    log_entry = {
        "level": level,
        "message": message,
        "source": source,
        "timestamp": __import__("time").time(),
    }

    await ws_manager.broadcast(
        "log",
        log_entry,
        room="logs"
    )

    logger.debug(f"Broadcasted log: [{level}] {message}")


async def broadcast_system_event(event_type: str, data: dict):
    """
    广播系统事件

    Args:
        event_type: 事件类型
        data: 事件数据
    """
    message = {
        "event_type": event_type,
        "data": data,
        "timestamp": __import__("time").time(),
    }

    await ws_manager.broadcast(
        "system_event",
        message
    )

    logger.debug(f"Broadcasted system event: {event_type}")


async def send_to_client(sid: str, event: str, data: dict):
    """
    发送消息给指定客户端

    Args:
        sid: 客户端ID
        event: 事件名
        data: 数据
    """
    await ws_manager.sio.emit(event, data, to=sid)
    logger.debug(f"Sent message to client {sid}: {event}")
