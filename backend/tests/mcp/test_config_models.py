import pytest
from magi.mcp.config import MCPServerConfig, StdioTransport

def test_stdio_minimum_valid():
    cfg = MCPServerConfig.model_validate({
        "server": {"id": "github", "name": "GitHub"},
        "transport": {"kind": "stdio", "command": "npx", "args": ["-y", "x"]},
    })
    assert cfg.server.id == "github"
    assert isinstance(cfg.transport, StdioTransport)
    assert cfg.transport.command == "npx"
    assert cfg.runtime.call_timeout_ms == 60000  # default
    assert cfg.server.enabled is True
    assert cfg.server.autostart is False
    assert cfg.tools.include is None

def test_http_minimum_valid():
    cfg = MCPServerConfig.model_validate({
        "server": {"id": "remote", "name": "Remote"},
        "transport": {"kind": "http", "url": "https://example.com/mcp"},
    })
    assert cfg.transport.kind == "http"
    assert cfg.transport.url == "https://example.com/mcp"

def test_invalid_id_rejected():
    with pytest.raises(ValueError):
        MCPServerConfig.model_validate({
            "server": {"id": "Bad ID!", "name": "x"},
            "transport": {"kind": "stdio", "command": "x"},
        })

def test_stdio_requires_command():
    with pytest.raises(ValueError):
        MCPServerConfig.model_validate({
            "server": {"id": "x", "name": "x"},
            "transport": {"kind": "stdio"},
        })


def test_tool_include_is_normalized_and_deduplicated():
    cfg = MCPServerConfig.model_validate({
        "server": {"id": "x", "name": "x"},
        "transport": {"kind": "stdio", "command": "x"},
        "tools": {"include": [" read ", "write", "read"]},
    })

    assert cfg.tools.include == ["read", "write"]
    assert cfg.tools.allows("read") is True
    assert cfg.tools.allows("delete") is False


def test_empty_tool_include_disables_every_tool():
    cfg = MCPServerConfig.model_validate({
        "server": {"id": "x", "name": "x"},
        "transport": {"kind": "stdio", "command": "x"},
        "tools": {"include": []},
    })

    assert cfg.tools.include == []
    assert cfg.tools.allows("read") is False


def test_blank_tool_include_entry_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        MCPServerConfig.model_validate({
            "server": {"id": "x", "name": "x"},
            "transport": {"kind": "stdio", "command": "x"},
            "tools": {"include": ["read", " "]},
        })
