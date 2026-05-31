def test_sdk_exposes_capabilities_container():
    from magi_plugin_sdk.capabilities import ToolCapabilities

    caps = ToolCapabilities()
    assert caps.trace is None
    assert caps.session_cache is None


def test_context_carries_capabilities():
    from magi_plugin_sdk.capabilities import ToolCapabilities
    from magi_plugin_sdk.tools import ToolExecutionContext

    caps = ToolCapabilities()
    ctx = ToolExecutionContext(agent_id="a", capabilities=caps)
    assert ctx.capabilities is caps


def test_context_capabilities_defaults_none():
    from magi_plugin_sdk.tools import ToolExecutionContext

    ctx = ToolExecutionContext(agent_id="a")
    assert ctx.capabilities is None


def test_host_builder_returns_capabilities():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
    from magi_plugin_sdk.capabilities import ToolCapabilities

    reset_tool_capabilities()  # ensure clean state
    caps = build_tool_capabilities()
    assert isinstance(caps, ToolCapabilities)
    assert build_tool_capabilities() is caps  # cached singleton


def test_reset_tool_capabilities_rebuilds():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    first = build_tool_capabilities()
    reset_tool_capabilities()
    assert build_tool_capabilities() is not first
