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


def test_detach_port_is_wired():
    """build_tool_capabilities().detach is a non-None DetachPort-compatible object."""
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    d = caps.detach
    assert d is not None, "caps.detach must be wired"
    assert hasattr(d, "is_available"), "DetachPort must have is_available"
    assert hasattr(d, "is_requested"), "DetachPort must have is_requested"
    assert hasattr(d, "request"), "DetachPort must have request"
    # Without an active detach signal the port reports not available.
    assert d.is_available() is False
    assert d.is_requested() is False
