"""
WebSocketeventpush

定义各种real-timeevent的pushFunction
"""
import logging
from .server import ws_manager

logger = logging.getLogger(__name__)


async def broadcast_agent_state(agent_id: str, state: str, data: dict = None):
    """
    广播AgentStateupdate

    Args:
        agent_id: Agent id
        state: newState
        data: 额外data
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

    logger.debug(f"broadcasted agent state: {agent_id} -> {state}")


async def broadcast_task_state(task_id: str, state: str, data: dict = None):
    """
    广播任务Stateupdate

    Args:
        task_id: 任务id
        state: newState
        data: 额外data
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

    logger.debug(f"broadcasted task state: {task_id} -> {state}")


async def broadcast_metrics(metrics: dict):
    """
    广播系统metricupdate

    Args:
        metrics: metricdata
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

    logger.debug("broadcasted metrics update")


async def broadcast_log(level: str, message: str, source: str = None):
    """
    广播Logmessage

    Args:
        level: Loglevel（info/warning/error）
        message: Logmessage
        source: Logsource
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

    logger.debug(f"broadcasted log: [{level}] {message}")


async def broadcast_system_event(event_type: str, data: dict):
    """
    广播系统event

    Args:
        event_type: eventtype
        data: eventdata
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

    logger.debug(f"broadcasted system event: {event_type}")


async def send_to_client(sid: str, Event: str, data: dict):
    """
    sendmessage给指定client

    Args:
        sid: clientid
        event: Event名
        data: data
    """
    await ws_manager.sio.emit(event, data, to=sid)
    logger.debug(f"Sent message to client {sid}: {event}")
