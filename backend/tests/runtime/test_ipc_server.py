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
