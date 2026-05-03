from __future__ import annotations

import asyncio
import enum
import itertools
import json
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


class HttpConnection(MCPConnection):
    """Streamable HTTP transport (MCP 2025-03-26).

    Each client message is a POST to the MCP endpoint. The server may answer
    with either an inline `application/json` JSON-RPC response or a
    `text/event-stream` SSE stream eventually carrying the response.
    Notifications/responses receive HTTP 202 with no body.

    A separate GET stream may be opened to receive server-initiated requests
    and notifications.
    """

    def __init__(self, transport):
        super().__init__()
        from .config import HttpTransport

        if not isinstance(transport, HttpTransport):
            raise TypeError("HttpConnection requires HttpTransport")
        self._t = transport
        self._client = None  # type: ignore[assignment]
        self._session_id: str | None = None
        self._listen_task: asyncio.Task | None = None
        self._post_tasks: set[asyncio.Task] = set()

    async def _start_transport(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            headers=self._t.headers, timeout=None
        )
        self.state = ConnectionState.CONNECTED
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def _stop_transport(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
        for t in list(self._post_tasks):
            t.cancel()
        if self._client is not None:
            await self._client.aclose()
        self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg: Message) -> None:
        # The base class invokes _send_raw inside request() and immediately
        # awaits the pending future. Networking must therefore happen in a
        # background task so that request()'s wait_for can observe the result.
        task = asyncio.create_task(self._post(msg))
        self._post_tasks.add(task)
        task.add_done_callback(self._post_tasks.discard)

    async def _post(self, msg: Message) -> None:
        import httpx

        assert self._client is not None
        body = json.loads(encode_message(msg).rstrip(b"\n"))
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            resp = await self._client.post(
                self._t.url, json=body, headers=headers
            )
        except httpx.HTTPError as exc:
            await self._fail_request(msg, exc)
            return

        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid

        if resp.status_code == 202:
            await resp.aread()
            return
        if resp.status_code >= 400:
            text = (await resp.aread()).decode("utf-8", errors="replace")
            await self._fail_request(
                msg, RuntimeError(f"HTTP {resp.status_code}: {text}")
            )
            return

        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("application/json"):
            raw = await resp.aread()
            try:
                await self._dispatch(parse_message(raw))
            except Exception:
                logger.exception("invalid inline JSON response")
        elif ctype.startswith("text/event-stream"):
            async for raw in _iter_sse_data(resp):
                try:
                    await self._dispatch(parse_message(raw))
                except Exception:
                    logger.exception("invalid SSE event")
        else:
            await self._fail_request(
                msg, RuntimeError(f"unexpected content-type: {ctype!r}")
            )

    async def _fail_request(self, msg: Message, exc: BaseException) -> None:
        if isinstance(msg, JsonRpcRequest):
            fut = self._pending.get(msg.id)
            if fut is not None and not fut.done():
                fut.set_exception(exc)

    async def _listen_loop(self) -> None:
        """Open a GET SSE stream for server-initiated messages.

        Best-effort: 405 means the server doesn't support GET listening.
        """
        import httpx

        assert self._client is not None
        try:
            headers = {"Accept": "text/event-stream"}
            if self._session_id is not None:
                headers["Mcp-Session-Id"] = self._session_id
            async with self._client.stream(
                "GET", self._t.url, headers=headers
            ) as r:
                if r.status_code == 405:
                    return
                if r.status_code >= 400:
                    return
                async for raw in _iter_sse_data(r):
                    try:
                        await self._dispatch(parse_message(raw))
                    except Exception:
                        logger.exception("invalid SSE listen event")
        except (asyncio.CancelledError, httpx.HTTPError):
            return


async def _iter_sse_data(resp):
    """Yield raw `data:` payloads (bytes) from an SSE response."""
    buf: list[str] = []
    async for line in resp.aiter_lines():
        if line == "":
            if buf:
                payload = "\n".join(buf).encode("utf-8")
                buf = []
                yield payload
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            chunk = line[5:]
            if chunk.startswith(" "):
                chunk = chunk[1:]
            buf.append(chunk)
    if buf:
        yield "\n".join(buf).encode("utf-8")
