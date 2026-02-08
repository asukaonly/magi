"""
WebSocket服务器

实现Socket.IO服务器和连接管理
"""
import socketio
import asyncio
from typing import Dict, Set
from aiohttp import web
import logging

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    WebSocket连接管理器

    管理客户端连接和订阅
    """

    def __init__(self):
        # Socket.IO异步服务器
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins='*',
            logger=False,
            engineio_logger=False,
        )

        # 连接的客户端 {sid: {rooms: set}}
        self.clients: Dict[str, Dict[str, Set[str]]] = {}

        # 注册事件处理器
        self._register_handlers()

    def _register_handlers(self):
        """注册Socket.IO事件处理器"""

        @self.sio.event
        async def connect(sid, environ):
            """客户端连接"""
            logger.info(f"Client connected: {sid}")
            self.clients[sid] = {"rooms": set()}

        @self.sio.event
        async def disconnect(sid):
            """客户端断开"""
            logger.info(f"Client disconnected: {sid}")
            if sid in self.clients:
                # 离开所有房间
                for room in self.clients[sid]["rooms"]:
                    await self.sio.leave_room(sid, room)
                del self.clients[sid]

        @self.sio.event
        async def subscribe(sid, data):
            """
            订阅频道

            Args:
                sid: 客户端ID
                data: {channel: str} 订阅的频道
            """
            channel = data.get("channel")
            if not channel:
                return

            logger.info(f"Client {sid} subscribed to {channel}")
            await self.sio.enter_room(sid, channel)

            if sid in self.clients:
                self.clients[sid]["rooms"].add(channel)

            # 发送确认
            await self.sio.emit(
                "subscribed",
                {"channel": channel},
                to=sid
            )

        @self.sio.event
        async def unsubscribe(sid, data):
            """
            取消订阅频道

            Args:
                sid: 客户端ID
                data: {channel: str} 取消订阅的频道
            """
            channel = data.get("channel")
            if not channel:
                return

            logger.info(f"Client {sid} unsubscribed from {channel}")
            await self.sio.leave_room(sid, channel)

            if sid in self.clients:
                self.clients[sid]["rooms"].discard(channel)

            # 发送确认
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
        广播消息

        Args:
            event: 事件名
            data: 数据
            room: 房间名（可选，不指定则广播给所有客户端）
        """
        if room:
            await self.sio.emit(event, data, to=room, skip_sid=None)
        else:
            await self.sio.emit(event, data)

    def get_client_count(self) -> int:
        """获取连接的客户端数量"""
        return len(self.clients)

    def get_clients_in_room(self, room: str) -> int:
        """获取房间内的客户端数量"""
        count = 0
        for client in self.clients.values():
            if room in client["rooms"]:
                count += 1
        return count


# 全局WebSocket管理器实例
ws_manager = WebSocketManager()


def create_socketio_app(app):
    """
    创建Socket.IO应用并挂载到aiohttp应用

    Args:
        app: aiohttp应用实例

    Returns:
        Socket.IO应用
    """
    # 将Socket.IO附加到aiohttp应用
    sio_app = socketio.ASGIApp(ws_manager.sio)
    app['/ws'] = sio_app

    # 添加WebSocket端点路由
    async def websocket_handler(request):
        """WebSocket处理"""
        return await ws_manager.sio.handle_request(request)

    app.router.add_get('/ws/socket.io', websocket_handler)
    app.router.add_post('/ws/socket.io', websocket_handler)

    logger.info("WebSocket server initialized on /ws")

    return ws_manager
