"""Integration test for IPC server — Unix socket round-trip."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

import pytest
from fastapi import FastAPI

from magi.ipc import handlers
from magi.ipc import server as server_module
from magi.ipc.server import IpcServer

TEST_IPC_AUTH_TOKEN = "test-internal-ipc-auth-token"


async def authenticate_ipc_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    token: str = TEST_IPC_AUTH_TOKEN,
) -> dict[str, object]:
    request = (
        json.dumps(
            {
                "id": "auth-1",
                "method": "ipc.authenticate",
                "params": {"token": token},
            }
        )
        + "\n"
    )
    writer.write(request.encode("utf-8"))
    await writer.drain()
    raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
    return json.loads(raw.decode("utf-8"))


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_ping_round_trip() -> None:
    """Start IPC server, connect a raw client, send ping, verify pong."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        try:
            server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
            await server.start()

            # Connect raw client
            reader, writer = await asyncio.open_unix_connection(sock_path)
            auth_response = await authenticate_ipc_client(reader, writer)
            assert auth_response["result"] == {"authenticated": True}

            # Send ping request
            req = json.dumps({"id": "test-1", "method": "ping", "params": None}) + "\n"
            writer.write(req.encode("utf-8"))
            await writer.drain()

            # Read response
            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
            resp = json.loads(raw.decode("utf-8"))

            assert resp["id"] == "test-1"
            assert resp["result"] == {"status": "pong"}

            # Send unknown method
            req2 = json.dumps({"id": "test-2", "method": "nonexistent"}) + "\n"
            writer.write(req2.encode("utf-8"))
            await writer.drain()

            raw2 = await asyncio.wait_for(reader.readline(), timeout=2.0)
            resp2 = json.loads(raw2.decode("utf-8"))
            assert resp2["id"] == "test-2"
            assert "error" in resp2
            assert resp2["error"]["code"] == -1

            writer.close()
            await writer.wait_closed()
            await server.stop()
        finally:
            os.environ.pop("MAGI_IPC_SOCKET", None)


@pytest.mark.asyncio
async def test_ipc_parse_error_omits_input_when_full_content_logging_is_disabled(
    monkeypatch,
) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        server_module,
        "full_content_logging_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        server_module.logger,
        "warning",
        lambda event, **fields: warnings.append((event, fields)),
    )
    line = "IPC-CONTENT-CANARY-not-json"

    await IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)._process_line(  # type: ignore[arg-type]
        line,
        object(),
        asyncio.Lock(),
    )

    assert warnings == [("ipc_parse_error", {"line_chars": len(line)})]
    assert "IPC-CONTENT-CANARY" not in str(warnings)


@pytest.mark.asyncio
async def test_ipc_authentication_failure_never_logs_the_credential(monkeypatch) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        server_module.logger,
        "warning",
        lambda event, **fields: warnings.append((event, fields)),
    )
    reader = asyncio.StreamReader()
    frame = (
        json.dumps(
            {
                "id": "auth-canary",
                "method": "ipc.authenticate",
                "params": {"token": "IPC-AUTH-CONTENT-CANARY"},
            }
        )
        + "\n"
    )
    reader.feed_data(frame.encode("utf-8"))
    reader.feed_eof()

    auth_request_id = await IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)._read_auth_request(reader)

    assert auth_request_id is None
    assert warnings == [("ipc_authentication_failed", {"reason": "invalid_token"})]
    assert "IPC-AUTH-CONTENT-CANARY" not in str(warnings)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_accepts_large_request_lines() -> None:
    """The IPC server should accept requests larger than the asyncio default line limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        try:
            server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
            await server.start()

            reader, writer = await asyncio.open_unix_connection(sock_path)
            await authenticate_ipc_client(reader, writer)

            oversized_payload = "x" * (80 * 1024)
            req = (
                json.dumps(
                    {"id": "test-large", "method": "ping", "params": {"blob": oversized_payload}}
                )
                + "\n"
            )
            writer.write(req.encode("utf-8"))
            await writer.drain()

            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
            resp = json.loads(raw.decode("utf-8"))
            assert resp["id"] == "test-large"
            assert resp["result"] == {"status": "pong"}

            writer.close()
            await writer.wait_closed()
            await server.stop()
        finally:
            os.environ.pop("MAGI_IPC_SOCKET", None)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_runtime_ready_round_trip(monkeypatch) -> None:
    app = FastAPI()

    async def fake_runtime_status(received_app):
        assert received_app is app
        return {
            "service_ready": True,
            "storage_ready": True,
            "infrastructure_ready": True,
            "capabilities": {},
            "runtime_ready": True,
            "worker_ready": True,
            "llm_ready": True,
            "agent_runtime_ready": True,
            "queue_backlog_healthy": True,
            "status": "ready",
            "runtime_status": "ready",
            "startup_state": "ready",
            "deferred_reason": None,
            "pending_commands": 0,
        }

    monkeypatch.setattr(handlers, "get_runtime_system_status", fake_runtime_status, raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        try:
            server = IpcServer(asgi_app=app, auth_token=TEST_IPC_AUTH_TOKEN)
            await server.start()

            reader, writer = await asyncio.open_unix_connection(sock_path)
            await authenticate_ipc_client(reader, writer)
            req = json.dumps({"id": "ready-1", "method": "runtime.ready", "params": None}) + "\n"
            writer.write(req.encode("utf-8"))
            await writer.drain()

            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
            resp = json.loads(raw.decode("utf-8"))

            assert resp["id"] == "ready-1"
            assert resp["result"]["success"] is True
            assert resp["result"]["data"] == {
                "ready": True,
                "status": "ready",
                "service_ready": True,
                "storage_ready": True,
                "infrastructure_ready": True,
                "capabilities": {},
                "runtime_ready": True,
                "worker_ready": True,
                "llm_ready": True,
                "agent_runtime_ready": True,
                "runtime_status": "ready",
                "startup_state": "ready",
                "deferred_reason": None,
                "queue_backlog_healthy": True,
                "pending_commands": 0,
            }

            writer.close()
            await writer.wait_closed()
            await server.stop()
        finally:
            os.environ.pop("MAGI_IPC_SOCKET", None)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_rejects_business_requests_before_authentication() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
        try:
            await server.start()
            reader, writer = await asyncio.open_unix_connection(sock_path)
            request = json.dumps({"id": "bypass-1", "method": "ping"}) + "\n"
            writer.write(request.encode("utf-8"))
            await writer.drain()

            assert await asyncio.wait_for(reader.readline(), timeout=2.0) == b""
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            os.environ.pop("MAGI_IPC_SOCKET", None)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_rejects_wrong_authentication_token() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
        try:
            await server.start()
            reader, writer = await asyncio.open_unix_connection(sock_path)
            request = (
                json.dumps(
                    {
                        "id": "auth-wrong",
                        "method": "ipc.authenticate",
                        "params": {"token": "wrong-token"},
                    }
                )
                + "\n"
            )
            writer.write(request.encode("utf-8"))
            await writer.drain()

            assert await asyncio.wait_for(reader.readline(), timeout=2.0) == b""
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            os.environ.pop("MAGI_IPC_SOCKET", None)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_allows_only_one_authenticated_connection() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
        try:
            await server.start()
            first_reader, first_writer = await asyncio.open_unix_connection(sock_path)
            await authenticate_ipc_client(first_reader, first_writer)

            second_reader, second_writer = await asyncio.open_unix_connection(sock_path)
            request = (
                json.dumps(
                    {
                        "id": "auth-second",
                        "method": "ipc.authenticate",
                        "params": {"token": TEST_IPC_AUTH_TOKEN},
                    }
                )
                + "\n"
            )
            second_writer.write(request.encode("utf-8"))
            await second_writer.drain()
            assert await asyncio.wait_for(second_reader.readline(), timeout=2.0) == b""

            ping = json.dumps({"id": "still-active", "method": "ping"}) + "\n"
            first_writer.write(ping.encode("utf-8"))
            await first_writer.drain()
            response = json.loads((await first_reader.readline()).decode("utf-8"))
            assert response["result"] == {"status": "pong"}

            second_writer.close()
            first_writer.close()
            await second_writer.wait_closed()
            await first_writer.wait_closed()
        finally:
            await server.stop()
            os.environ.pop("MAGI_IPC_SOCKET", None)


@pytest.mark.asyncio
async def test_ipc_tcp_transport_requires_authentication(monkeypatch, unused_tcp_port: int) -> None:
    socket_address = f"127.0.0.1:{unused_tcp_port}"
    monkeypatch.setattr(server_module.sys, "platform", "win32")
    monkeypatch.setenv("MAGI_IPC_SOCKET", socket_address)
    server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
    try:
        await server.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        auth_response = await authenticate_ipc_client(reader, writer)
        assert auth_response["result"] == {"authenticated": True}

        request = json.dumps({"id": "tcp-ping", "method": "ping"}) + "\n"
        writer.write(request.encode("utf-8"))
        await writer.drain()
        response = json.loads((await reader.readline()).decode("utf-8"))
        assert response["result"] == {"status": "pong"}

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ping_remains_responsive_during_slow_async_work(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "probe.sock")
        monkeypatch.setenv("MAGI_IPC_SOCKET", path)
        server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_work(_params):
            started.set()
            await release.wait()
            return {"done": True}

        server.register("test.slow", slow_work)
        await server.start()
        reader, writer = await asyncio.open_unix_connection(path)
        try:
            await authenticate_ipc_client(reader, writer)
            writer.write(b'{"id":"slow","method":"test.slow"}\n')
            await writer.drain()
            await asyncio.wait_for(started.wait(), 1)
            writer.write(b'{"id":"probe","method":"ping"}\n')
            await writer.drain()
            reply = json.loads(await asyncio.wait_for(reader.readline(), 1))
            assert reply == {"id": "probe", "result": {"status": "pong"}}
            release.set()
            reply = json.loads(await asyncio.wait_for(reader.readline(), 1))
            assert reply["id"] == "slow"
        finally:
            release.set()
            writer.close()
            await writer.wait_closed()
            await server.stop()


class MemoryWriter:
    def __init__(self):
        self.responses = asyncio.Queue()
        self.closed = False

    def get_extra_info(self, name):
        return None

    def write(self, raw):
        self.responses.put_nowait(json.loads(raw))

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed

    async def wait_closed(self):
        pass


def feed(reader, request):
    reader.feed_data((json.dumps(request) + '\n').encode())


async def memory_connection(server):
    reader = asyncio.StreamReader()
    writer = MemoryWriter()
    feed(reader, {"id": "auth", "method": "ipc.authenticate", "params": {"token": TEST_IPC_AUTH_TOKEN}})
    task = asyncio.create_task(server._handle_connection(reader, writer))
    assert (await asyncio.wait_for(writer.responses.get(), 1))["result"]["authenticated"]
    return reader, writer, task


@pytest.mark.asyncio
async def test_business_capacity_is_bounded_and_health_remains_responsive(monkeypatch):
    monkeypatch.setattr(server_module, "IPC_BUSINESS_LIMIT", 2)
    server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
    release = asyncio.Event()
    entered = asyncio.Queue()

    async def blocked(params):
        entered.put_nowait(True)
        await release.wait()
        return {"done": True}

    server.register("work", blocked)
    reader, writer, connection = await memory_connection(server)
    for index in range(2):
        feed(reader, {"id": str(index), "method": "work"})
        await asyncio.wait_for(entered.get(), 1)
    feed(reader, {"id": "overflow", "method": "work"})
    rejected = await asyncio.wait_for(writer.responses.get(), 1)
    assert rejected["error"]["code"] == -32001
    feed(reader, {"id": "health", "method": "ping"})
    assert (await asyncio.wait_for(writer.responses.get(), 1))["result"] == {"status": "pong"}
    reader.feed_eof()
    await connection
    assert len(server._business_tasks) == 2
    # Reconnecting does not reset the process-wide admission budget.
    reader2, writer2, connection2 = await memory_connection(server)
    feed(reader2, {"id": "overflow2", "method": "work"})
    assert (await asyncio.wait_for(writer2.responses.get(), 1))["error"]["code"] == -32001
    release.set()
    await asyncio.gather(*server._business_tasks)
    reader2.feed_eof()
    await connection2
    await server.stop()


@pytest.mark.asyncio
async def test_disconnect_cancels_reads_but_keeps_accepted_writes(monkeypatch):
    server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
    entered = asyncio.Queue()
    finished = asyncio.Queue()
    release = asyncio.Event()

    async def forward(params):
        entered.put_nowait(params["method"])
        try:
            await release.wait()
            return {"status": 200}
        finally:
            finished.put_nowait(params["method"])

    server.register("api.forward", forward)
    reader, writer, connection = await memory_connection(server)
    for method in ["GET", "POST"]:
        feed(reader, {"id": method, "method": "api.forward", "params": {"method": method}})
        await asyncio.wait_for(entered.get(), 1)
    # A forged cancellation for a write is deliberately ignored.
    feed(reader, {"method": "ipc.cancel", "params": {"id": "POST"}})
    reader.feed_eof()
    await connection
    assert await asyncio.wait_for(finished.get(), 1) == "GET"
    assert finished.empty()
    release.set()
    assert await asyncio.wait_for(finished.get(), 1) == "POST"
    await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,code", [("GET", -32002), ("POST", -32003)])
async def test_execution_deadline_cleans_up_handler_and_reports_write_uncertainty(monkeypatch, method, code):
    monkeypatch.setattr(server_module, "IPC_READ_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(server_module, "IPC_WRITE_TIMEOUT_SECONDS", 0.01)
    server = IpcServer(auth_token=TEST_IPC_AUTH_TOKEN)
    cancelled = asyncio.Event()

    async def blocked(params):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    server.register("api.forward", blocked)
    reader, writer, connection = await memory_connection(server)
    feed(reader, {"id": "deadline", "method": "api.forward", "params": {"method": method}})
    response = await asyncio.wait_for(writer.responses.get(), 1)
    assert response["error"]["code"] == code
    assert cancelled.is_set()
    reader.feed_eof()
    await connection
    await server.stop()
