def test_trace_port_wired_in_builder():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.trace is not None
    assert hasattr(caps.trace, "get_trace_snapshot")
    assert hasattr(caps.trace, "get_turn_activity_map")
    reset_tool_capabilities()
