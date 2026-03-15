"""
WebSocket event broadcasting.

Defines functions for pushing real-time events to connected clients.
"""
import logging
from .server import ws_manager

logger = logging.getLogger(__name__)


async def broadcast_agent_state(agent_id: str, state: str, data: dict = None):
    """
    Broadcast agent state update to connected clients.

    Args:
        agent_id: Agent ID.
        state: New state value.
        data: Additional payload data.
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
    Broadcast task state update to connected clients.

    Args:
        task_id: Task ID.
        state: New state value.
        data: Additional payload data.
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
    Broadcast system metrics update to connected clients.

    Args:
        metrics: Metrics data.
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
    Broadcast log message to connected clients.

    Args:
        level: Log level (info/warning/error).
        message: Log message content.
        source: Log source identifier.
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
    Broadcast system event to connected clients.

    Args:
        event_type: Event type identifier.
        data: Event payload data.
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


async def send_to_client(sid: str, event: str, data: dict):
    """
    Send a message to a specific client.

    Args:
        sid: Client session ID.
        event: Event name.
        data: Event payload data.
    """
    await ws_manager.sio.emit(event, data, to=sid)
    logger.debug(f"Sent message to client {sid}: {event}")
