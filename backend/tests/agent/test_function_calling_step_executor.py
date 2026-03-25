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
        disable_thinking=True,
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
            data={"memory_context": "用户喜欢下雨天", "meta": {}},
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
        disable_thinking=True,
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
    assert json.loads(tool_message["content"])["data"]["memory_context"] == "用户喜欢下雨天"


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
        disable_thinking=True,
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
        disable_thinking=True,
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
