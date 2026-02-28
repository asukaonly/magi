"""
WebSocket router with endpoint registration.

Provides the main WebSocket endpoint and registration function.
"""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ...core.logger import get_logger
from ..connection_manager import ConnectionManager, manager
from .handlers import WebSocketContext, handler_registry

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


async def websocket_endpoint(websocket: WebSocket, manager: ConnectionManager) -> None:
    """
    Main WebSocket endpoint handler.

    Args:
        websocket: The WebSocket connection
        manager: The connection manager instance
    """
    sid = str(uuid.uuid4())
    logger.info("New WebSocket connection attempt", sid=sid)

    await manager.connect(sid, websocket)
    logger.info("WebSocket connection established", sid=sid)

    try:
        while True:
            # Receive client message
            try:
                data = await websocket.receive_json()
                logger.debug("Received WebSocket message", sid=sid, data=data)
            except Exception as e:
                logger.warning("Failed to receive JSON", sid=sid, error=str(e))
                # Try to receive text and parse
                try:
                    text_data = await websocket.receive_text()
                    logger.debug("Received text", sid=sid, text=text_data)
                    try:
                        data = json.loads(text_data)
                    except json.JSONDecodeError:
                        logger.error("Invalid JSON format", sid=sid)
                        continue
                except Exception as text_error:
                    logger.error("Failed to receive text", sid=sid, error=str(text_error))
                    continue

            # Create context and dispatch to handler
            ctx = WebSocketContext(sid=sid, websocket=websocket, manager=manager)
            response = await handler_registry.dispatch(ctx, data)

            # Send response if provided
            if response is not None:
                await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (WebSocketDisconnect)", sid=sid)
        manager.disconnect(sid)
    except Exception as e:
        logger.error("WebSocket error", sid=sid, error=str(e), exc_info=True)
        manager.disconnect(sid)


def register_websocket(app: FastAPI, manager: ConnectionManager = manager, path: str = "/ws") -> None:
    """
    Register WebSocket endpoint with the FastAPI application.

    Args:
        app: FastAPI application instance
        manager: Connection manager instance (defaults to global manager)
        path: WebSocket endpoint path (defaults to "/ws")
    """

    @app.websocket(path)
    async def websocket_route(websocket: WebSocket):
        await websocket_endpoint(websocket, manager)
