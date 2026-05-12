"""Integration test for IPC server — Unix socket round-trip."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile

import pytest

from magi.ipc.server import IpcServer


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_ping_round_trip() -> None:
    """Start IPC server, connect a raw client, send ping, verify pong."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        try:
            server = IpcServer()
            await server.start()

            # Connect raw client
            reader, writer = await asyncio.open_unix_connection(sock_path)

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
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_server_accepts_large_request_lines() -> None:
    """The IPC server should accept requests larger than the asyncio default line limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        os.environ["MAGI_IPC_SOCKET"] = sock_path
        try:
            server = IpcServer()
            await server.start()

            reader, writer = await asyncio.open_unix_connection(sock_path)

            oversized_payload = "x" * (80 * 1024)
            req = json.dumps({"id": "test-large", "method": "ping", "params": {"blob": oversized_payload}}) + "\n"
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
