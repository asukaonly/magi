from __future__ import annotations
from magi.events.domain_payloads import (
    ToolError,
)


def test_tool_error_truncated_default_false():
    err = ToolError(type="ValueError", message="boom")
    assert err.truncated is False
