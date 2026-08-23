from __future__ import annotations

import asyncio
import enum
import itertools
import json
import logging
import os
from typing import Any, Callable

from magi_plugin_sdk.subprocess import hidden_process_kwargs

from .config import StdioTransport
from .log_security import (
    redact_mcp_log_text,
    redact_mcp_traceback,
    register_mcp_runtime_secrets,
    register_mcp_transport_secrets,
)
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
                except Exception as exc:
                    logger.error(
                        "notification handler error: method=%s | traceback=%s",
                        msg.method,
                        redact_mcp_traceback(exc),
                    )
        else:
            logger.warning(
                "server-initiated request not supported yet: %s", msg.method
            )


class StdioConnection(MCPConnection):
    def __init__(self, transport: StdioTransport, *, label: str = "mcp.stdio"):
        super().__init__()
        register_mcp_transport_secrets(transport)
        self._t = transport
        # `label` is recorded in the ManagedSubprocess PID registry so
        # backend startup can match orphaned MCP servers back to their
        # configured server.id.
        self._label = label
        self._managed: Any = None  # ManagedSubprocess | None
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_buf: list[str] = []

    @property
    def stderr_tail(self) -> list[str]:
        return [
            redacted
            for item in self._stderr_buf[-500:]
            if (redacted := redact_mcp_log_text(item)) is not None
        ]

    async def _start_transport(self) -> None:
        env = {**os.environ, **self._t.env}
        argv = [self._t.command, *self._t.args]
        try:
            from magi_plugin_sdk.subprocess import ManagedSubprocess
        except ImportError:
            ManagedSubprocess = None  # type: ignore[assignment]

        if ManagedSubprocess is not None:
            self._managed = await ManagedSubprocess.spawn(
                argv,
                label=self._label,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._t.cwd or None,
                env=env,
            )
            self._proc = self._managed.proc
        else:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._t.cwd or None,
                env=env,
                **hidden_process_kwargs(),
            )
        self.state = ConnectionState.CONNECTED
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def _stop_transport(self) -> None:
        if self._proc is None:
            return
        try:
            if self._managed is not None:
                # ManagedSubprocess owns the SIGTERM→SIGKILL escalation
                # and removes the registry entry.
                await self._managed.shutdown(
                    sigterm_grace_seconds=2.0,
                    sigkill_grace_seconds=1.0,
                )
            elif self._proc.returncode is None:
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
                    except Exception as exc:
                        logger.error(
                            "invalid MCP message frame | traceback=%s",
                            redact_mcp_traceback(exc),
                        )
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
                decoded = line.decode("utf-8", errors="replace").rstrip()
                self._stderr_buf.append(redact_mcp_log_text(decoded) or "")
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
        register_mcp_transport_secrets(transport)
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
            register_mcp_runtime_secrets([sid])
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
            except Exception as exc:
                logger.error(
                    "invalid inline JSON response | traceback=%s",
                    redact_mcp_traceback(exc),
                )
        elif ctype.startswith("text/event-stream"):
            async for raw in _iter_sse_data(resp):
                try:
                    await self._dispatch(parse_message(raw))
                except Exception as exc:
                    logger.error(
                        "invalid SSE event | traceback=%s",
                        redact_mcp_traceback(exc),
                    )
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
                    except Exception as exc:
                        logger.error(
                            "invalid SSE listen event | traceback=%s",
                            redact_mcp_traceback(exc),
                        )
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
