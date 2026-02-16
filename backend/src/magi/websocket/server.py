"""
WebSocketservice器

ImplementationSocket.I/Oservice器andconnection管理
"""
import socketio
import asyncio
from typing import Dict, Set
from aiohttp import web
import logging

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    WebSocketconnection管理器

    管理clientconnectionandsubscribe
    """

    def __init__(self):
        # Socket.I/Oasynchronotttusservice器
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins='*',
            logger=False,
            engineio_logger=False,
        )

        # connection的client {sid: {rooms: set}}
        self.clients: Dict[str, Dict[str, Set[str]]] = {}

        # registereventprocess器
        self._register_handlers()

    def _register_handlers(self):
        """registerSocket.I/Oeventprocess器"""

        @self.sio.event
        async def connect(sid, environ):
            """clientconnection"""
            logger.info(f"Client connected: {sid}")
            self.clients[sid] = {"rooms": set()}

        @self.sio.event
        async def disconnect(sid):
            """clientdisconnect"""
            logger.info(f"Client disconnected: {sid}")
            if sid in self.clients:
                # 离开all房间
                for room in self.clients[sid]["rooms"]:
                    await self.sio.leave_room(sid, room)
                del self.clients[sid]

        @self.sio.event
        async def subscribe(sid, data):
            """
            subscribe频道

            Args:
                sid: clientid
                data: {channel: str} subscribe的频道
            """
            channel = data.get("channel")
            if not channel:
                return

            logger.info(f"Client {sid} subscribed to {channel}")
            await self.sio.enter_room(sid, channel)

            if sid in self.clients:
                self.clients[sid]["rooms"].add(channel)

            # send确认
            await self.sio.emit(
                "subscribed",
                {"channel": channel},
                to=sid
            )

        @self.sio.event
        async def unsubscribe(sid, data):
            """
            cancelsubscribe频道

            Args:
                sid: clientid
                data: {channel: str} cancelsubscribe的频道
            """
            channel = data.get("channel")
            if not channel:
                return

            logger.info(f"Client {sid} unsubscribed from {channel}")
            await self.sio.leave_room(sid, channel)

            if sid in self.clients:
                self.clients[sid]["rooms"].discard(channel)

            # send确认
            await self.sio.emit(
                "unsubscribed",
                {"channel": channel},
                to=sid
            )

        @self.sio.event
        async def ping(sid):
            """心跳检测"""
            await self.sio.emit("pong", to=sid)

    async def broadcast(self, event: str, data: dict, room: str = None):
        """
        广播message

        Args:
            event: event名
            data: data
            room: 房间名（optional，不指定则广播给allclient）
        """
        if room:
            await self.sio.emit(event, data, to=room, skip_sid=None)
        else:
            await self.sio.emit(event, data)

    def get_client_count(self) -> int:
        """getconnection的clientquantity"""
        return len(self.clients)

    def get_clients_in_room(self, room: str) -> int:
        """get房间内的clientquantity"""
        count = 0
        for client in self.clients.values():
            if room in client["rooms"]:
                count += 1
        return count


# globalWebSocket管理器Instance
ws_manager = WebSocketManager()


def create_socketio_app(app):
    """
    createSocket.I/O应用并挂载到aiohttp应用

    Args:
        app: aiohttp应用Instance

    Returns:
        Socket.I/O应用
    """
    # 将Socket.I/O附加到aiohttp应用
    sio_app = socketio.asGIApp(ws_manager.sio)
    app['/ws'] = sio_app

    # addWebSocket端点route
    async def websocket_handler(request):
        """WebSocketprocess"""
        return await ws_manager.sio.handle_request(request)

    app.router.add_get('/ws/socket.io', websocket_handler)
    app.router.add_post('/ws/socket.io', websocket_handler)

    logger.info("WebSocket server initialized on /ws")

    return ws_manager
