"""
Native WebSocket router registration for the transport layer.
"""
from __future__ import annotations

import json
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ..core.logger import get_logger
from ..api.middleware import get_required_desktop_session_token
from .connection_manager import ConnectionManager, manager
from .handlers import WebSocketContext, handler_registry

logger = get_logger(__name__)


async def websocket_endpoint(websocket: WebSocket, manager: ConnectionManager) -> None:
    """Main WebSocket endpoint handler."""
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
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                logger.info("WebSocket disconnect message received", sid=sid)
                break

            if message["type"] != "websocket.receive":
                continue

            text_data = message.get("text")
            if text_data is None:
                bytes_data = message.get("bytes")
                if bytes_data:
                    text_data = bytes_data.decode("utf-8")
                else:
                    logger.warning("Received empty message", sid=sid)
                    continue

            try:
                data = json.loads(text_data)
                logger.debug("Received WebSocket message", sid=sid, data=data)
            except json.JSONDecodeError:
                logger.error("Invalid JSON format", sid=sid, text=text_data[:100])
                continue

            ctx = WebSocketContext(sid=sid, websocket=websocket, manager=manager)
            response = await handler_registry.dispatch(ctx, data)

            if response is not None:
                await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected (WebSocketDisconnect)", sid=sid)
    except Exception as exc:
        logger.error("WebSocket error", sid=sid, error=str(exc), exc_info=True)
    finally:
        manager.disconnect(sid)


def register_websocket(app: FastAPI, manager: ConnectionManager = manager, path: str = "/ws") -> None:
    """Register the WebSocket endpoint with a FastAPI app."""

    @app.websocket(path)
    async def websocket_route(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket, manager)
