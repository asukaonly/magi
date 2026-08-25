"""Content-policy coverage for registered tool execution logs."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from magi.agent.execution.function_calling._registered_tool_execution import (
    _RegisteredToolExecutor,
)
from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.agent.execution.function_calling.run_journal import FunctionCallingRunJournal
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.agent.execution.function_calling.types import ExecutionOutcome
from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningState
from magi.agent.turn_input import UserTurnInput
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


@pytest.mark.asyncio
async def test_agent_run_breadcrumbs_omit_prompt_and_message_content(caplog) -> None:
    secret_message = "private user regression message"
    secret_prompt = "private system regression prompt"
    policy = ReasoningPolicy()
    state = FunctionCallingStepState(
        messages=[{"role": "user", "content": secret_message}],
        effective_system_prompt=secret_prompt,
        tools=[],
        selected_tool_names=["memory_query"],
        run_id="run-1",
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
    )
    run_input = AgentRunRequest(
        turn=UserTurnInput(text=secret_message),
        system_prompt=secret_prompt,
        selected_tools=["memory_query"],
        user_id="user-1",
        run_id="run-1",
        session_id="session-1",
        turn_id="turn-1",
        context_sources=(
            {
                "provider": "memory",
                "availability": "available",
                "snapshot": {"content": secret_message},
            },
        ),
        reasoning_policy=policy,
    )
    journal = FunctionCallingRunJournal(
        SimpleNamespace(runtime_trace_store=None, _active_model_context=None)
    )

    with caplog.at_level(logging.INFO):
        await journal.start(state, run_input)
        await journal.record_terminal(
            state,
            ExecutionOutcome(status="completed", content="done", iterations=1),
        )

    rendered = caplog.text
    assert "agent_run.started" in rendered
    assert "agent_run.terminal" in rendered
    assert "memory_query" in rendered
    assert secret_message not in rendered
    assert secret_prompt not in rendered
