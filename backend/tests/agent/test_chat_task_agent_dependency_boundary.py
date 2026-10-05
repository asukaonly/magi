"""Boundary tests for chat task-agent runtime assembly."""

from __future__ import annotations

from dataclasses import fields

import pytest

from magi.chat.task_agent.chat_task_agent import _RUNTIME_CONFIG_INIT_FIELDS
from magi.chat.task_agent import runtime_execution_builder
from magi.chat.task_agent.runtime_dependencies import (
    ChatTaskAgentRuntimeConfig,
)


def test_chat_task_agent_runtime_config_init_fields_stay_complete() -> None:
    config_fields = {field.name for field in fields(ChatTaskAgentRuntimeConfig)}

    assert set(_RUNTIME_CONFIG_INIT_FIELDS) == config_fields - {"agent_id", "runtime_key"}


def test_optional_runtime_dependency_requires_explicit_absence() -> None:
    assert runtime_execution_builder._resolve_optional_runtime_dependency(None) is None

    def _broken_resolver() -> object:
        raise ModuleNotFoundError(
            "No module named 'broken.internal'",
            name="broken.internal",
        )

    with pytest.raises(ModuleNotFoundError) as exc_info:
        runtime_execution_builder._resolve_optional_runtime_dependency(
            _broken_resolver,
        )
    assert exc_info.value.name == "broken.internal"


def test_chat_trace_dependency_initialization_failure_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.runtime_trace.chat_trace import read_service

    class _BrokenChatTraceReadService:
        def __init__(self) -> None:
            raise RuntimeError("trace startup failed")

    monkeypatch.setattr(
        read_service,
        "ChatTraceReadService",
        _BrokenChatTraceReadService,
    )

    with pytest.raises(RuntimeError, match="trace startup failed"):
        runtime_execution_builder._build_chat_trace_read_service()
