import sys
from pathlib import Path

import pytest

from magi.mcp.config import StdioTransport
from magi.mcp.connection import StdioConnection

FAKE_SERVER = r"""
import os, sys, json
def write(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("method") == "echo":
        write({"jsonrpc":"2.0","id":msg["id"],"result":msg["params"]})
    elif msg.get("method") == "boom":
        write({"jsonrpc":"2.0","id":msg["id"],"error":{"code":-1,"message":"boom"}})
    elif msg.get("method") == "log_then_echo":
        sys.stderr.write("logging from server\n")
        sys.stderr.flush()
        write({"jsonrpc":"2.0","id":msg["id"],"result":msg.get("params")})
    elif msg.get("method") == "log_secret":
        sys.stderr.write("external tool value=" + os.environ["UNUSUAL_SETTING"] + "\n")
        sys.stderr.flush()
        write({"jsonrpc":"2.0","id":msg["id"],"result":msg.get("params")})
"""


@pytest.fixture
def fake_server_script(tmp_path: Path) -> Path:
    p = tmp_path / "fake.py"
    p.write_text(FAKE_SERVER)
    return p


@pytest.mark.asyncio
async def test_stdio_round_trip(fake_server_script: Path):
    transport = StdioTransport(
        command=sys.executable, args=[str(fake_server_script)]
    )
    conn = StdioConnection(transport)
    await conn.start()
    try:
        result = await conn.request("echo", {"hello": "world"}, timeout=3.0)
        assert result == {"hello": "world"}
    finally:
        await conn.stop()


@pytest.mark.asyncio
async def test_stdio_error_response(fake_server_script: Path):
    transport = StdioTransport(
        command=sys.executable, args=[str(fake_server_script)]
    )
    conn = StdioConnection(transport)
    await conn.start()
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await conn.request("boom", None, timeout=3.0)
    finally:
        await conn.stop()


@pytest.mark.asyncio
async def test_stdio_captures_stderr(fake_server_script: Path):
    transport = StdioTransport(
        command=sys.executable, args=[str(fake_server_script)]
    )
    conn = StdioConnection(transport)
    await conn.start()
    try:
        await conn.request("log_then_echo", {"a": 1}, timeout=3.0)
        # Give the stderr loop a moment to drain.
        import asyncio
        await asyncio.sleep(0.05)
        tail = conn.stderr_tail
        assert any("logging from server" in line for line in tail)
    finally:
        await conn.stop()


@pytest.mark.asyncio
async def test_stdio_redacts_arbitrary_configured_env_values_from_stderr(
    fake_server_script: Path,
):
    secret = "mcp-unusual-env-secret"
    transport = StdioTransport(
        command=sys.executable,
        args=[str(fake_server_script)],
        env={"UNUSUAL_SETTING": secret},
    )
    conn = StdioConnection(transport)
    await conn.start()
    try:
        await conn.request("log_secret", None, timeout=3.0)
        import asyncio

        await asyncio.sleep(0.05)
        rendered = "\n".join(conn.stderr_tail)
        assert secret not in rendered
        assert "[REDACTED]" in rendered
    finally:
        await conn.stop()
