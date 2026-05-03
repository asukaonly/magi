from __future__ import annotations

import asyncio
import enum
import itertools
import logging
from typing import Any, Callable

from .protocol import (
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    Message,
)

logger = logging.getLogger(__name__)


class ConnectionState(str, enum.Enum):
    INIT = "init"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class MCPConnection:
    def __init__(self) -> None:
        self.state = ConnectionState.INIT
        self._id_seq = itertools.count(1)
        self._pending: dict[int | str, asyncio.Future] = {}
        self._handlers: dict[str, list[Callable[[Any], None]]] = {}

    async def start(self) -> None:
        self.state = ConnectionState.CONNECTING
        await self._start_transport()

    async def stop(self) -> None:
        await self._stop_transport()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("connection closed"))
        self._pending.clear()

    async def request(self, method: str, params: Any, *, timeout: float) -> Any:
        rid = next(self._id_seq)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        await self._send_raw(JsonRpcRequest(id=rid, method=method, params=params))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: Any = None) -> None:
        await self._send_raw(JsonRpcNotification(method=method, params=params))

    def on_notification(
        self, method: str, handler: Callable[[Any], None]
    ) -> None:
        self._handlers.setdefault(method, []).append(handler)

    async def _start_transport(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _stop_transport(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _send_raw(self, msg: Message) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _dispatch(self, msg: Message) -> None:
        if isinstance(msg, JsonRpcResponse):
            fut = self._pending.get(msg.id)
            if fut is None:
                logger.warning("MCP response for unknown id=%s", msg.id)
                return
            if msg.error is not None:
                fut.set_exception(
                    RuntimeError(
                        f"MCP error {msg.error.code}: {msg.error.message}"
                    )
                )
            else:
                fut.set_result(msg.result)
        elif isinstance(msg, JsonRpcNotification):
            for h in self._handlers.get(msg.method, []):
                try:
                    h(msg.params)
                except Exception:
                    logger.exception(
                        "notification handler error: method=%s", msg.method
                    )
        else:
            logger.warning(
                "server-initiated request not supported yet: %s", msg.method
            )
