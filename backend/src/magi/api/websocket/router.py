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
from ..middleware import get_required_desktop_session_token
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

    required_token = get_required_desktop_session_token()
    if required_token:
        provided_token = websocket.query_params.get("token", "").strip()
        if provided_token != required_token:
            logger.warning("Rejected WebSocket connection due to invalid desktop token", sid=sid)
            await websocket.close(code=4401, reason="Unauthorized")
            return

    await manager.connect(sid, websocket)
    logger.info("WebSocket connection established", sid=sid)

    try:
        while True:
            # Receive raw message and handle by type
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                logger.info("WebSocket disconnect message received", sid=sid)
                break

            if message["type"] == "websocket.receive":
                # Get text data
                text_data = message.get("text")
                if text_data is None:
                    # Might be bytes, try to decode
                    bytes_data = message.get("bytes")
                    if bytes_data:
                        text_data = bytes_data.decode("utf-8")
                    else:
                        logger.warning("Received empty message", sid=sid)
                        continue

                # Parse JSON
                try:
                    data = json.loads(text_data)
                    logger.debug("Received WebSocket message", sid=sid, data=data)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON format", sid=sid, text=text_data[:100])
                    continue

                # Create context and dispatch to handler
                ctx = WebSocketContext(sid=sid, websocket=websocket, manager=manager)
                response = await handler_registry.dispatch(ctx, data)

                # Send response if provided
                if response is not None:
                    await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (WebSocketDisconnect)", sid=sid)
    except Exception as e:
        logger.error("WebSocket error", sid=sid, error=str(e), exc_info=True)
    finally:
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
