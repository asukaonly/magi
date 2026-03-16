"""Connection and transport layer exports."""

from .bridge_lifecycle import WebSocketBridgeLifecycleModule
from .connection_manager import (
    ConnectionManager,
    broadcast_agent_update,
    broadcast_log,
    broadcast_metrics_update,
    broadcast_task_update,
    manager,
)
from .handlers import MessageHandlerRegistry, WebSocketContext, handler_registry
from .http_app import create_transport_app
from .router import register_websocket, websocket_endpoint

__all__ = [
    "ConnectionManager",
    "manager",
    "broadcast_agent_update",
    "broadcast_task_update",
    "broadcast_metrics_update",
    "broadcast_log",
    "MessageHandlerRegistry",
    "WebSocketContext",
    "handler_registry",
    "WebSocketBridgeLifecycleModule",
    "create_transport_app",
    "register_websocket",
    "websocket_endpoint",
]
