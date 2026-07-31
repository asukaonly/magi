"""Content-policy coverage for registered tool execution logs."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from magi.agent.execution.function_calling._registered_tool_execution import (
    _RegisteredToolExecutor,
)
from magi.utils.diagnostic_logging import set_full_content_logging_enabled


def test_tool_logs_omit_arguments_and_errors_when_content_logging_is_off(
    caplog,
) -> None:
    secret_argument = "private search phrase"
    secret_error = "private remote error"
    host = SimpleNamespace(
        _FILE_SCAN_TOOLS=set(),
        _SLOW_SCAN_WARNING_SECONDS=10.0,
    )
    executor = _RegisteredToolExecutor(host)
    request = SimpleNamespace(
        tool_name="web_search",
        start_time=0.0,
        tool_call=SimpleNamespace(id="call-1"),
    )
    result = SimpleNamespace(
        success=False,
        data=None,
        error=secret_error,
        error_code="REMOTE_ERROR",
    )

    set_full_content_logging_enabled(False)
    try:
        with caplog.at_level(logging.INFO):
            executor._log_tool_start(request, {"query": secret_argument})
            executor._to_tool_call_result(
                request,
                {"query": secret_argument},
                result,
            )
    finally:
        set_full_content_logging_enabled(True)

    rendered = caplog.text
    assert secret_argument not in rendered
    assert secret_error not in rendered
    assert "argument_names=['query']" in rendered
    assert "error_chars=" in rendered
