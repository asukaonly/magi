from __future__ import annotations

import asyncio
import enum
import itertools
import logging
import os
from typing import Any, Callable

from .config import StdioTransport
from .protocol import (
    FrameDecoder,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    Message,
    encode_message,
    parse_message,
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


class StdioConnection(MCPConnection):
    def __init__(self, transport: StdioTransport):
        super().__init__()
        self._t = transport
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_buf: list[str] = []

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_buf[-500:])

    async def _start_transport(self) -> None:
        env = {**os.environ, **self._t.env}
        self._proc = await asyncio.create_subprocess_exec(
            self._t.command,
            *self._t.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._t.cwd or None,
            env=env,
        )
        self.state = ConnectionState.CONNECTED
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def _stop_transport(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
        finally:
            for t in (self._reader_task, self._stderr_task):
                if t is not None:
                    t.cancel()
            self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg: Message) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise ConnectionError("stdio not started")
        self._proc.stdin.write(encode_message(msg))
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        decoder = FrameDecoder()
        try:
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                decoder.feed(chunk)
                while True:
                    raw = decoder.next()
                    if raw is None:
                        break
                    try:
                        msg = parse_message(raw)
                    except Exception:
                        logger.exception("invalid MCP message frame")
                        continue
                    await self._dispatch(msg)
        except asyncio.CancelledError:
            return
        finally:
            self.state = ConnectionState.DISCONNECTED

    async def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                self._stderr_buf.append(
                    line.decode("utf-8", errors="replace").rstrip()
                )
                if len(self._stderr_buf) > 1000:
                    self._stderr_buf = self._stderr_buf[-500:]
        except asyncio.CancelledError:
            return
