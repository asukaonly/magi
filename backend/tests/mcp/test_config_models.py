import pytest
from magi.mcp.config import MCPServerConfig, StdioTransport

@pytest.mark.parametrize(
    "transport",
    [
        {"kind": "stdio", "command": "npx", "args": ["-y", "x"]},
        {"kind": "http", "url": "https://example.com/mcp"},
    ],
)
def test_transport_discriminator_preserves_selected_fields(transport):
    from magi.mcp.config import HttpTransport

    config = MCPServerConfig.model_validate(
        {"server": {"id": "demo", "name": "Demo"}, "transport": transport}
    )
    assert isinstance(
        config.transport, StdioTransport if transport["kind"] == "stdio" else HttpTransport
    )
    serialized = config.transport.model_dump()
    assert {key: serialized[key] for key in transport} == transport
    assert config.runtime.call_timeout_ms == 60000
    assert config.server.enabled is True and config.server.autostart is False
    assert config.tools.include is None


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
