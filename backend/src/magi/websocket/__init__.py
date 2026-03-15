"""
WebSocket real-time communication module (DEPRECATED).

This Socket.IO-based module is superseded by the FastAPI WebSocket
implementation in ``magi.api.connection_manager`` and ``magi.api.websocket``.
No external code imports from this package. It is retained only for
reference and will be removed in a future cleanup pass.
"""

import warnings as _warnings

_warnings.warn(
    "magi.websocket is deprecated; use magi.api.connection_manager and magi.api.websocket instead",
    DeprecationWarning,
    stacklevel=2,
)

from .server import WebSocketManager, create_socketio_app
from .events import (
    broadcast_agent_state,
    broadcast_task_state,
    broadcast_metrics,
    broadcast_log,
)

__all__ = [
    "WebSocketManager",
    "create_socketio_app",
    "broadcast_agent_state",
    "broadcast_task_state",
    "broadcast_metrics",
    "broadcast_log",
]
