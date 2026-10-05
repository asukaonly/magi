

def test_host_capability_bundle_is_cached_until_reset():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
    from magi.core.tool_capabilities import ToolCapabilities

    bare = ToolCapabilities()
    assert bare.trace is None
    assert not hasattr(bare, "session_cache")
    reset_tool_capabilities()
    try:
        first = build_tool_capabilities()
        assert isinstance(first, ToolCapabilities)
        assert build_tool_capabilities() is first
        reset_tool_capabilities()
        second = build_tool_capabilities()
        assert second is not first
        assert build_tool_capabilities() is second
    finally:
        reset_tool_capabilities()


def test_detach_port_requests_only_the_active_run_signal():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
    from magi.control.run_control import DetachSignal, DetachRequested, bind_detach_signal

    reset_tool_capabilities()
    try:
        port = build_tool_capabilities().detach
        assert port.is_available() is False
        port.request(reason="outside-run")
        assert port.is_requested() is False
        signal = DetachSignal()
        with bind_detach_signal(signal):
            assert port.is_available() is True
            assert port.is_requested() is False
            port.request(reason="long-running", requested_by="user", note="continue later")
            assert port.is_requested() is True
            assert signal.payload == DetachRequested(
                reason="long-running", requested_by="user", note="continue later"
            )
        assert port.is_available() is False
        with bind_detach_signal(DetachSignal()):
            assert port.is_requested() is False
    finally:
        reset_tool_capabilities()
