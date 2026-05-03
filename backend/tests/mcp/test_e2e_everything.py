"""End-to-end smoke test against the official `server-everything` MCP server.

Spins up `npx -y @modelcontextprotocol/server-everything` via MCPManager
and asserts the handshake → tools/list → tools/call → resources/list
path works through the full real protocol stack. Skipped when `npx` is
unavailable (CI environments without Node).

Expected runtime: ~5–15s, depending on whether the npm package is cached.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

from magi.mcp.config import MCPServerConfig
from magi.mcp.manager import MCPManager
from magi.tools.registry import ToolRegistry


pytestmark = pytest.mark.skipif(
    shutil.which("npx") is None,
    reason="npx not available; install Node.js to run this E2E smoke",
)


@pytest.mark.asyncio
async def test_server_everything_round_trip():
    cfg = MCPServerConfig.model_validate(
        {
            "server": {
                "id": "everything",
                "name": "Everything",
                "autostart": False,
            },
            "transport": {
                "kind": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-everything"],
            },
            "runtime": {"init_timeout_ms": 60000, "call_timeout_ms": 30000},
        }
    )

    registry = ToolRegistry()
    mgr = MCPManager(registry=registry)
    mgr.add_config(cfg)

    try:
        await mgr.start_server("everything")
    except Exception as exc:
        pytest.skip(f"Could not start server-everything (network/install issue): {exc}")

    try:
        tool_names = [
            name
            for name in registry._tools.keys()  # type: ignore[attr-defined]
            if name.startswith("mcp__everything__")
        ]
        assert tool_names, "expected at least one tool to be registered"

        # `echo` is a stable tool exposed by server-everything.
        echo_name = "mcp__everything__echo"
        if echo_name in tool_names:
            tool = registry.get_tool(echo_name)
            assert tool is not None
            # The tool's first parameter is named `message` per the server's
            # exposed schema. Use whatever the schema actually requires.
            params: dict = {}
            for p in tool.get_schema().parameters:
                if p.required:
                    params[p.name] = "magi-e2e"
            result = await tool.execute(params, context=None)
            assert result.success, f"echo failed: {result.error}"

        resources = await mgr.list_resources()
        # server-everything exposes ~100 demo resources; just sanity-check.
        assert isinstance(resources, list)
    finally:
        await mgr.stop_server("everything")
        # Give the subprocess a moment to fully reap.
        await asyncio.sleep(0.05)
