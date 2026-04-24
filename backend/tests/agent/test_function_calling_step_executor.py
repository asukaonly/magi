from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall, ToolCallResult
from magi.tools.builtin.memory_query_tool import MemoryQueryTool


class _FakeToolRegistry:
    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str):  # type: ignore[no-untyped-def]
        return None


class _MemoryToolRegistry(_FakeToolRegistry):
    def get_tool_info(self, tool_name: str):  # type: ignore[no-untyped-def]
        if tool_name != "memory_query":
            return None
        return MemoryQueryTool().get_info()


def _build_orchestrator() -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
    )


def test_build_step_state_does_not_duplicate_latest_user_message_from_history() -> None:
    orchestrator = _build_orchestrator()

    step_state = orchestrator.build_step_state(
        user_message="Inspect the repository.",
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[{"role": "user", "content": "Inspect the repository."}],
    )

    assert step_state.messages == [{"role": "user", "content": "Inspect the repository."}]


def test_build_tools_parameter_includes_array_items_schema_for_openai_tools() -> None:
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=_MemoryToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
    )

    tools = orchestrator._build_tools_parameter(["memory_query"])

    assert tools[0]["function"]["name"] == "memory_query"
    assert tools[0]["function"]["parameters"]["properties"]["sources"] == {
        "type": "array",
        "description": "Optional source filters such as ['chat', 'timeline', 'worker'].",
        "items": {"type": "string"},
    }


@pytest.mark.asyncio
async def test_step_executor_executes_one_llm_decision_and_one_tool_batch(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        user_message="Inspect the repository.",
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[],
    )
    llm_calls: list[dict[str, object]] = []
    tool_calls: list[str] = []

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        llm_calls.append(kwargs)
        return {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "memory_query", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_1", name="memory_query", arguments={})],
            "llm_trace": {"model": "fake-model"},
        }

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        tool_calls.append(tool_call.name)
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={"items": ["memory hit"]},
            execution_time=0.01,
        )

    async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)
    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)

    outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="Inspect the repository.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-1",
        intent="repo_analysis",
        execution_agent_id="chat:s-chat",
        orchestration_strategy=None,
    )

    assert outcome.status == "continue"
    assert outcome.iteration == 1
    assert len(llm_calls) == 1
    assert tool_calls == ["memory_query"]
    assert step_state.iteration == 1
    assert [message["role"] for message in step_state.messages] == ["user", "assistant", "tool"]


@pytest.mark.asyncio
async def test_step_executor_serializes_tool_messages_without_ascii_escaping(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        user_message="我喜欢什么天气？",
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[],
    )

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_zh",
                        "type": "function",
                        "function": {"name": "memory_query", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_zh", name="memory_query", arguments={})],
            "llm_trace": {"model": "fake-model"},
        }

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={
                "historical_recall": {
                    "status": "found",
                    "summary": "用户喜欢下雨天",
                    "findings": [],
                    "insufficient_evidence": False,
                    "answering_hints": {},
                    "provenance": {"primary_count": 1, "source_layers": ["L2"]},
                },
                "debug": {"retrieval_trace": {"query_mode": "detail"}},
            },
            execution_time=0.01,
        )

    async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)
    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)

    outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="我喜欢什么天气？",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-zh",
        intent="chat",
        execution_agent_id="chat:s-chat",
        orchestration_strategy=None,
    )

    assert outcome.status == "continue"
    tool_message = step_state.messages[-1]
    assert tool_message["role"] == "tool"
    assert "用户喜欢下雨天" in tool_message["content"]
    assert "\\u7528\\u6237" not in tool_message["content"]
    payload = json.loads(tool_message["content"])
    assert payload["data"]["historical_recall"]["summary"] == "用户喜欢下雨天"
    assert "debug" not in payload["data"]


@pytest.mark.asyncio
async def test_step_executor_collects_chat_attachments_from_tool_results(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        user_message="Send the selected photos.",
        system_prompt="system prompt",
        selected_tools=["prepare_chat_attachments"],
        conversation_history=[],
    )

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_attach",
                        "type": "function",
                        "function": {"name": "prepare_chat_attachments", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_attach", name="prepare_chat_attachments", arguments={})],
            "llm_trace": {"model": "fake-model"},
        }

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={
                "chat_attachments": [
                    {"attachment_id": "att-1", "kind": "image", "original_name": "one.jpg"}
                ]
            },
            execution_time=0.01,
        )

    async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)
    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)

    outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="Send the selected photos.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-attach",
        intent="chat",
        execution_agent_id="chat:s-chat",
        orchestration_strategy=None,
    )

    assert outcome.status == "continue"
    assert step_state.chat_attachments == [
        {"attachment_id": "att-1", "kind": "image", "original_name": "one.jpg"}
    ]


@pytest.mark.asyncio
async def test_step_executor_collects_assistant_message_payload_from_tool_results(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        user_message="Send the selected photos.",
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[],
    )

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_payload",
                        "type": "function",
                        "function": {"name": "memory_query", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_payload", name="memory_query", arguments={})],
            "llm_trace": {"model": "fake-model"},
        }

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={
                "assistant_payload": {
                    "candidate_photo_refs": [
                        {"photo_ref_id": "photo-1", "event_id": "evt-1", "original_name": "hangzhou.jpg"}
                    ]
                }
            },
            execution_time=0.01,
        )

    async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)
    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)

    outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="Send the selected photos.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-payload",
        intent="chat",
        execution_agent_id="chat:s-chat",
        orchestration_strategy=None,
    )

    assert outcome.status == "continue"
    assert step_state.message_payload == {
        "asset_refs": [
            {
                "asset_ref_id": "photo-1",
                "event_id": "evt-1",
                "original_name": "hangzhou.jpg",
                "resolution_state": "candidate",
            }
        ]
    }


@pytest.mark.asyncio
async def test_step_executor_returns_control_after_one_step_until_called_again(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        user_message="Inspect the repository.",
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[],
    )
    llm_responses = [
        {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "memory_query", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_1", name="memory_query", arguments={})],
            "llm_trace": {"model": "fake-model"},
        },
        {
            "content": "Here is the final answer.",
            "llm_trace": {"model": "fake-model"},
        },
    ]

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return llm_responses.pop(0)

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={"items": ["memory hit"]},
            execution_time=0.01,
        )

    async def _noop_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)
    monkeypatch.setattr(orchestrator, "_start_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_complete_iteration_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_loop_event", _noop_async)
    monkeypatch.setattr(orchestrator, "_emit_tool_result", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_llm_trace", _noop_async)
    monkeypatch.setattr(orchestrator, "_persist_tool_trace", _noop_async)

    first_outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="Inspect the repository.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-1",
        intent="repo_analysis",
        execution_agent_id="chat:s-chat",
        orchestration_strategy=None,
    )
    second_outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="Inspect the repository.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-1",
        intent="repo_analysis",
        execution_agent_id="chat:s-chat",
        orchestration_strategy=None,
    )

    assert first_outcome.status == "continue"
    assert second_outcome.status == "completed"
    assert second_outcome.content == "Here is the final answer."
    assert step_state.iteration == 2


def test_replan_allowed_when_untried_tools_remain_despite_non_replan_error() -> None:
    """Config errors should not block replan when the LLM has other tools to try."""
    orchestrator = _build_orchestrator()

    results = [
        ToolCallResult(
            tool_call_id="call_1",
            tool_name="weather",
            success=False,
            error="API key not configured",
            error_code="NO_PROVIDERS_CONFIGURED",
            execution_time=0.01,
        )
    ]
    available_tools = [
        {"type": "function", "function": {"name": "weather"}},
        {"type": "function", "function": {"name": "web-search"}},
    ]

    allowed = orchestrator._should_allow_replan_after_failed_iteration(
        results,
        consecutive_failed_tool_iterations=1,
        available_tools=available_tools,
    )
    assert allowed is True


def test_replan_blocked_when_all_tools_have_non_replan_errors() -> None:
    """When there are NO untried tools, non-replan errors should block replan."""
    orchestrator = _build_orchestrator()

    results = [
        ToolCallResult(
            tool_call_id="call_1",
            tool_name="weather",
            success=False,
            error="API key not configured",
            error_code="NO_PROVIDERS_CONFIGURED",
            execution_time=0.01,
        )
    ]
    # Only one tool available and it's the one that failed
    available_tools = [
        {"type": "function", "function": {"name": "weather"}},
    ]

    allowed = orchestrator._should_allow_replan_after_failed_iteration(
        results,
        consecutive_failed_tool_iterations=1,
        available_tools=available_tools,
    )
    assert allowed is False
