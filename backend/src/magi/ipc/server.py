"""Asyncio IPC server — listens on a Unix domain socket and speaks NDJSON."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import structlog

from magi.ipc.dispatcher import Dispatcher, MethodNotFound
from magi.ipc.handlers import handle_ping
from magi.ipc.protocol import IpcError, IpcNotify, IpcRequest, IpcResponse, parse_inbound

logger = structlog.get_logger(__name__)

IPC_STREAM_LIMIT_BYTES = 16 * 1024 * 1024


class IpcServer:
    """NDJSON IPC server that accepts a single persistent connection from the Rust gateway."""

    def __init__(self, *, asgi_app: Any = None) -> None:
        self._dispatcher = Dispatcher()
        self._dispatcher.register("ping", handle_ping)
        self._server: asyncio.AbstractServer | None = None
        self._api_forward = None

        if asgi_app is not None:
            from magi.ipc.handlers import ApiForwardHandler, RuntimeReadyHandler
            self._api_forward = ApiForwardHandler(asgi_app)
            self._dispatcher.register("api.forward", self._api_forward.handle)
            self._dispatcher.register("runtime.ready", RuntimeReadyHandler(asgi_app).handle)

    def register(self, method: str, handler: Any) -> None:
        """Register an additional IPC method handler."""
        self._dispatcher.register(method, handler)

    async def start(self) -> None:
        """Start listening on the path from MAGI_IPC_SOCKET env var."""
        socket_path = os.environ.get("MAGI_IPC_SOCKET")
        if not socket_path:
            logger.info("ipc_server_skipped", reason="MAGI_IPC_SOCKET not set")
            return

        if sys.platform == "win32":
            # Windows: MAGI_IPC_SOCKET is host:port
            host, port_str = socket_path.rsplit(":", 1)
            self._server = await asyncio.start_server(
                self._handle_connection, host, int(port_str), limit=IPC_STREAM_LIMIT_BYTES
            )
            logger.info("ipc_server_started", transport="tcp", addr=socket_path)
        else:
            # Remove stale socket
            try:
                os.unlink(socket_path)
            except FileNotFoundError:
                pass
            self._server = await asyncio.start_unix_server(
                self._handle_connection, path=socket_path, limit=IPC_STREAM_LIMIT_BYTES
            )
            logger.info("ipc_server_started", transport="unix", path=socket_path)

    async def stop(self) -> None:
        if self._api_forward is not None:
            await self._api_forward.close()
            self._api_forward = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("ipc_server_stopped")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername") or "unix"
        logger.info("ipc_client_connected", peer=peer)
        write_lock = asyncio.Lock()
        tasks: set[asyncio.Task] = set()
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                task = asyncio.create_task(self._process_line(line, writer, write_lock))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("ipc_connection_error")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("ipc_client_disconnected", peer=peer)

    async def _process_line(self, line: str, writer: asyncio.StreamWriter, write_lock: asyncio.Lock) -> None:
        try:
            msg = parse_inbound(line)
        except Exception:
            logger.warning("ipc_parse_error", line=line[:200])
            return

        if isinstance(msg, IpcNotify):
            await self._dispatcher.dispatch_notify(msg)
            return

        assert isinstance(msg, IpcRequest)
        try:
            result = await self._dispatcher.dispatch_request(msg)
            response = IpcResponse(id=msg.id, result=result)
        except MethodNotFound as exc:
            response = IpcError(id=msg.id, code=-1, message=str(exc))
        except Exception as exc:
            logger.exception("ipc_handler_error", method=msg.method)
            response = IpcError(id=msg.id, code=-32000, message=str(exc))

        async with write_lock:
            writer.write(response.to_line().encode("utf-8"))
            await writer.drain()
