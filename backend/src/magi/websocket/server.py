"""
WebSocket server.

Implements Socket.IO server and connection management.
"""
import socketio
import asyncio
from typing import Dict, Set
from aiohttp import web
import logging

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    WebSocket connection manager.

    Manages client connections and room subscriptions.
    """

    def __init__(self):
        # Socket.IO async server
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins='*',
            logger=False,
            engineio_logger=False,
        )

        # Connected clients: {sid: {rooms: set}}
        self.clients: Dict[str, Dict[str, Set[str]]] = {}

        # Register event handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self.sio.event
        async def connect(sid, environ):
            """Handle client connection."""
            logger.info(f"Client connected: {sid}")
            self.clients[sid] = {"rooms": set()}

        @self.sio.event
        async def disconnect(sid):
            """Handle client disconnection."""
            logger.info(f"Client disconnected: {sid}")
            if sid in self.clients:
                # Leave all rooms
                for room in self.clients[sid]["rooms"]:
                    await self.sio.leave_room(sid, room)
                del self.clients[sid]

        @self.sio.event
        async def subscribe(sid, data):
            """
            Subscribe to a channel.

            Args:
                sid: Client session ID.
                data: {channel: str} Channel to subscribe to.
            """
            channel = data.get("channel")
            if not channel:
                return

            logger.info(f"Client {sid} subscribed to {channel}")
            await self.sio.enter_room(sid, channel)

            if sid in self.clients:
                self.clients[sid]["rooms"].add(channel)

            # Send confirmation
            await self.sio.emit(
                "subscribed",
                {"channel": channel},
                to=sid
            )

        @self.sio.event
        async def unsubscribe(sid, data):
            """
            Unsubscribe from a channel.

            Args:
                sid: Client session ID.
                data: {channel: str} Channel to unsubscribe from.
            """
            channel = data.get("channel")
            if not channel:
                return

            logger.info(f"Client {sid} unsubscribed from {channel}")
            await self.sio.leave_room(sid, channel)

            if sid in self.clients:
                self.clients[sid]["rooms"].discard(channel)

            # Send confirmation
            await self.sio.emit(
                "unsubscribed",
                {"channel": channel},
                to=sid
            )

        @self.sio.event
        async def ping(sid):
            """Handle heartbeat ping."""
            await self.sio.emit("pong", to=sid)

    async def broadcast(self, event: str, data: dict, room: str = None):
        """
        Broadcast message to clients.

        Args:
            event: Event name.
            data: Event payload.
            room: Room name (optional; if omitted, broadcast to all clients).
        """
        if room:
            await self.sio.emit(event, data, to=room, skip_sid=None)
        else:
            await self.sio.emit(event, data)

    def get_client_count(self) -> int:
        """Get count of connected clients."""
        return len(self.clients)

    def get_clients_in_room(self, room: str) -> int:
        """Get count of clients in a room."""
        count = 0
        for client in self.clients.values():
            if room in client["rooms"]:
                count += 1
        return count


# Global WebSocket manager instance
ws_manager = WebSocketManager()


def create_socketio_app(app):
    """
    Create Socket.IO application and mount it to the aiohttp app.

    Args:
        app: aiohttp application instance.

    Returns:
        WebSocket manager instance.
    """
    # Attach Socket.IO to aiohttp app
    sio_app = socketio.ASGIApp(ws_manager.sio)
    app['/ws'] = sio_app

    # Add WebSocket endpoint routes
    async def websocket_handler(request):
        """Handle WebSocket requests."""
        return await ws_manager.sio.handle_request(request)

    app.router.add_get('/ws/socket.io', websocket_handler)
    app.router.add_post('/ws/socket.io', websocket_handler)

    logger.info("WebSocket server initialized on /ws")

    return ws_manager
