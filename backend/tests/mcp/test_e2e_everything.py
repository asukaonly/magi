"""Optional integration with @modelcontextprotocol/server-everything@2026.8.31.

Install that exact package separately and set MAGI_MCP_EVERYTHING_ROOT to its
package directory (the directory containing package.json). Tests never install
packages or use the network to resolve dependencies. Missing explicit setup is
the only skip; a configured but broken package or handshake fails the test.
"""

import json
import os
from pathlib import Path
import shutil

import pytest

from magi.mcp.config import MCPServerConfig
from magi.mcp.manager import MCPManager
from magi.tools.registry import ToolRegistry


@pytest.fixture
def everything_server():
    configured = os.environ.get("MAGI_MCP_EVERYTHING_ROOT")
    if not configured:
        pytest.skip("Set MAGI_MCP_EVERYTHING_ROOT to installed server-everything@2026.8.31")
    root = Path(configured)
    manifest = json.loads((root / "package.json").read_text())
    assert manifest["name"] == "@modelcontextprotocol/server-everything"
    assert manifest["version"] == "2026.8.31"
    entry = root / "dist" / "index.js"
    assert entry.is_file()
    node = shutil.which("node")
    assert node is not None, "Configured integration requires Node.js"
    return root, node, entry


@pytest.mark.asyncio
async def test_server_everything_round_trip(everything_server):
    root, node, entry = everything_server
    config = MCPServerConfig.model_validate(
        {
            "server": {"id": "everything", "name": "Everything", "autostart": False},
            "transport": {"kind": "stdio", "command": node, "args": [str(entry), "stdio"]},
            "runtime": {"init_timeout_ms": 10000, "call_timeout_ms": 10000},
        }
    )
    registry = ToolRegistry()
    manager = MCPManager(registry=registry)
    manager.add_config(config)
    try:
        await manager.start_server("everything")
        assert {
            "mcp__everything__echo",
            "mcp__everything__get-sum",
            "mcp__everything__get-tiny-image",
        } <= set(registry.list_tools())
        echo = registry.get_tool("mcp__everything__echo")
        assert echo is not None
        assert {p.name for p in echo.get_schema().parameters if p.required} == {"message"}
        result = await echo.execute({"message": "magi-e2e"}, context=None)
        assert result.success is True
        assert result.data["content"] == [{"type": "text", "text": "Echo: magi-e2e"}]
        assert result.metadata["output"] == "Echo: magi-e2e"
        uri = "demo://resource/static/document/instructions.md"
        resources = await manager.list_resources()
        assert any(
            resource["server_id"] == "everything" and resource["uri"] == uri
            for resource in resources
        )
        document = await manager.read_resource("everything", uri)
        assert document["contents"] == [
            {
                "uri": uri,
                "mimeType": "text/markdown",
                "text": (root / "dist" / "docs" / "instructions.md").read_text(),
            }
        ]
    finally:
        await manager.stop_all()
    assert manager.is_running("everything") is False
    assert not any(name.startswith("mcp__everything__") for name in registry.list_tools())
