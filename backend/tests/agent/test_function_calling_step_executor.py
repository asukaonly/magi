from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agent.agent_run_helpers import run_agent
from agent.permission_helpers import AllowAllPermissionGateway

from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall, ToolCallResult
from magi.llm.model_context import ModelContextProfile, ResolvedModel
from magi.tools.builtin.memory_query_tool import MemoryQueryTool
from magi.agent.turn_input import UserTurnInput
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY


class _FakeToolRegistry:
    def is_skill(self, _tool_name: str) -> bool:
        return False

    def get_tool_info(self, _tool_name: str):  # type: ignore[no-untyped-def]
        return None

    def get_tool(self, tool_name: str):  # type: ignore[no-untyped-def]
        schema = SimpleNamespace(
            name=tool_name,
            effect_class="read_only",
            effect_replay_policy="read_only",
            dangerous=False,
            requires_auth=False,
            metadata={},
        )
        return SimpleNamespace(get_schema=lambda: schema)


class _MemoryToolRegistry(_FakeToolRegistry):
    def get_tool_info(self, tool_name: str):  # type: ignore[no-untyped-def]
        if tool_name != "memory_query":
            return None
        return MemoryQueryTool().get_info()


def _build_orchestrator() -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
        permission_gateway=AllowAllPermissionGateway(),
    )


def test_build_step_state_does_not_duplicate_latest_user_message_from_history() -> None:
    orchestrator = _build_orchestrator()

    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Inspect the repository.", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[{"role": "user", "content": "Inspect the repository."}],
    )

    assert step_state.messages == [{"role": "user", "content": "Inspect the repository."}]


def test_build_step_state_materializes_turn_context_before_current_user() -> None:
    orchestrator = _build_orchestrator()

    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="current", attachments=[], user_id=None, session_id=None),
        system_prompt=(
            f"stable head\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\n"
            "dynamic memory and runtime state"
        ),
        selected_tools=[],
        conversation_history=[
            {"role": "user", "content": "older"},
            {"role": "assistant", "content": "answer"},
        ],
    )

    assert step_state.effective_system_prompt == (
        f"stable head\n{SYSTEM_PROMPT_CACHE_BOUNDARY}"
    )
    turn_context = step_state.messages[-2]
    assert turn_context["role"] == "user"
    assert str(turn_context["content"]).startswith("<turn_context>\n")
    assert "dynamic memory and runtime state" in str(turn_context["content"])
    assert "Tool recovery rules:" in str(turn_context["content"])
    assert str(turn_context["content"]).endswith("\n</turn_context>")
    assert step_state.messages[-1] == {"role": "user", "content": "current"}


def test_prompt_history_preserves_assistant_tool_calls() -> None:
    orchestrator = _build_orchestrator()
    tool_call_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read", "arguments": "{}"},
            }
        ],
    }

    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="continue", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=[],
        conversation_history=[
            {"role": "user", "content": "inspect"},
            tool_call_message,
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
        ],
    )

    assert step_state.messages[1] == tool_call_message
    assert step_state.messages[2]["tool_call_id"] == "call-1"


def test_build_step_state_keeps_complete_raw_tail_before_compaction() -> None:
    adapter = SimpleNamespace(model_name="small-model", provider_name="fake-provider")
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=_FakeToolRegistry(),
        active_model_provider=lambda: ResolvedModel(
            adapter=adapter,
            context=ModelContextProfile(
                provider_id="fake-provider",
                model_id="small-model",
                context_window=1_000,
                max_output_tokens=100,
            ),
        ),
    )
    old_question = "old question " + "x" * 1_800
    old_answer = "old answer " + "y" * 700

    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="current question", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=[],
        conversation_history=[
            {"role": "user", "content": old_question},
            {"role": "assistant", "content": old_answer},
            {"role": "user", "content": "recent question"},
            {"role": "assistant", "content": "recent answer"},
        ],
        session_summary="summary before the raw tail",
        session_origin="session origin",
    )

    assert any(message.get("content") == old_question for message in step_state.messages)
    assert any(message.get("content") == old_answer for message in step_state.messages)
    assert step_state.messages[-1] == {"role": "user", "content": "current question"}


def test_build_tools_parameter_includes_array_items_schema_for_openai_tools() -> None:
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=_MemoryToolRegistry(),
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
    )

    tools = orchestrator._build_tools_parameter(["memory_query"])

    assert tools[0]["function"]["name"] == "memory_query"
    # ``summary_categories`` is one of the array-typed parameters MemoryQueryTool
    # still exposes — verify the OpenAI schema includes a string-typed `items`
    # entry plus a non-empty description.
    summary_categories_schema = tools[0]["function"]["parameters"]["properties"][
        "summary_categories"
    ]
    assert summary_categories_schema["type"] == "array"
    assert summary_categories_schema["items"] == {"type": "string"}
    assert isinstance(summary_categories_schema.get("description"), str)
    assert summary_categories_schema["description"]


def test_build_step_state_tracks_selected_tool_names() -> None:
    orchestrator = _build_orchestrator()

    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Inspect the repository.", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=["memory_query", "find-relevant-tools", "memory_query"],
        conversation_history=[],
    )

    assert step_state.selected_tool_names == ["memory_query", "find-relevant-tools"]


@pytest.mark.asyncio
async def test_execute_with_tools_drops_ephemeral_context_after_first_tool_loop(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    llm_message_snapshots: list[str] = []

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        llm_message_snapshots.append(json.dumps(kwargs["messages"], ensure_ascii=False))
        if len(llm_message_snapshots) == 1:
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
        return {"content": "done", "llm_trace": {"model": "fake-model"}}

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

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="Inspect the repository.", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-ephemeral",
        intent="child_read_only",
        execution_agent_id="worker_1",
        ephemeral_context="large parent conversation snapshot",
        max_iterations=3,
    )

    assert outcome.status == "completed"
    assert len(llm_message_snapshots) == 2
    assert "large parent conversation snapshot" in llm_message_snapshots[0]
    assert "large parent conversation snapshot" not in llm_message_snapshots[1]
    assert "Inspect the repository." in llm_message_snapshots[1]


@pytest.mark.asyncio
async def test_step_executor_executes_one_llm_decision_and_one_tool_batch(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Inspect the repository.", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=["memory_query"],
        conversation_history=[],
    )
    llm_calls: list[dict[str, object]] = []
    tool_calls: list[str] = []
    context_commits: list[list[str]] = []

    class _RecordingModelContextPort:
        async def commit(self, **kwargs):  # type: ignore[no-untyped-def]
            context_commits.append(
                [str(message.get("role") or "") for message in kwargs["messages"]]
            )

    step_state.model_context_port = _RecordingModelContextPort()  # type: ignore[assignment]
    step_state.model_context_turn_id = "turn-1"
    step_state.run_id = "run-1"

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
        execution_preset="repo_analysis",
        execution_agent_id="chat:s-chat",
        run_id="run-1",
    )

    assert outcome.status == "continue"
    assert outcome.iteration == 1
    assert len(llm_calls) == 1
    assert tool_calls == ["memory_query"]
    assert step_state.iteration == 1
    assert [message["role"] for message in step_state.messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert "Runtime expression policy" not in str(step_state.messages)
    assert "Execution-phase expression rule" in step_state.effective_system_prompt
    assert context_commits == [
        ["user"],
        ["user", "assistant"],
        ["user", "assistant", "tool"],
    ]


@pytest.mark.asyncio
async def test_step_executor_serializes_tool_messages_without_ascii_escaping(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="我喜欢什么天气？", attachments=[], user_id=None, session_id=None),
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
        execution_preset="chat",
        execution_agent_id="chat:s-chat",
        run_id="run-zh",
    )

    assert outcome.status == "continue"
    tool_message = next(
        message for message in reversed(step_state.messages) if message["role"] == "tool"
    )
    assert tool_message["role"] == "tool"
    assert "用户喜欢下雨天" in tool_message["content"]
    assert "\\u7528\\u6237" not in tool_message["content"]
    payload = json.loads(tool_message["content"])
    assert "用户喜欢下雨天" in payload["data"]["historical_recall"]
    assert "debug" not in payload["data"]


@pytest.mark.asyncio
async def test_step_executor_appends_tools_recommended_by_find_relevant_tools(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    orchestrator.tool_registry = SimpleNamespace(
        get_tool_info=lambda name: {"name": name, "description": f"{name} desc", "category": "test", "parameters": []}
        if name in {"memory_query", "find-relevant-tools", "weather"}
        else None,
        is_skill=lambda _name: False,
    )
    monkeypatch.setattr(
        orchestrator,
        "_build_tools_parameter",
        lambda selected_tools: [  # type: ignore[no-untyped-call]
            {"type": "function", "function": {"name": tool_name}}
            for tool_name in selected_tools
        ],
    )
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="What was the weather there?", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=["memory_query", "find-relevant-tools"],
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
                        "id": "call_find",
                        "type": "function",
                        "function": {"name": "find-relevant-tools", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_find", name="find-relevant-tools", arguments={})],
            "llm_trace": {"model": "fake-model"},
        }

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={
                "recommendations": [{"name": "weather", "type": "tool"}],
                "tool_expansion": {
                    "append_tools": ["weather"],
                    "reason": "Need historical weather lookup after memory recall.",
                },
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
        user_message="What was the weather there?",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-expand",
        execution_preset="chat",
        execution_agent_id="chat:s-chat",
        run_id="run-attach",
    )

    assert outcome.status == "continue"
    assert step_state.selected_tool_names == ["memory_query", "find-relevant-tools", "weather"]
    assert [tool["function"]["name"] for tool in step_state.tools] == [
        "memory_query",
        "find-relevant-tools",
        "weather",
    ]
    assert step_state.tool_expansion_count == 1


@pytest.mark.asyncio
async def test_step_executor_collects_chat_attachments_from_tool_results(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Send the selected photos.", attachments=[], user_id=None, session_id=None),
        system_prompt="system prompt",
        selected_tools=["prepare_chat_attachments"],
        conversation_history=[],
        allow_attachment_grounding=True,
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
        execution_preset="chat",
        execution_agent_id="chat:s-chat",
        run_id="run-payload",
    )

    assert outcome.status == "continue"
    assert step_state.chat_attachments == [
        {"attachment_id": "att-1", "kind": "image", "original_name": "one.jpg"}
    ]
    grounding_message = next(
        message
        for message in step_state.messages
        if "These prepared attachments will be sent with your response."
        in str(message.get("content", ""))
    )
    assert grounding_message["role"] == "user"


@pytest.mark.asyncio
async def test_step_executor_skips_attachment_grounding_when_disabled(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Send the selected photos.", attachments=[], user_id=None, session_id=None),
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
        execution_preset="chat",
        execution_agent_id="chat:s-chat",
        run_id="run-memory-payload",
    )

    assert outcome.status == "continue"
    assert step_state.chat_attachments == [
        {"attachment_id": "att-1", "kind": "image", "original_name": "one.jpg"}
    ]
    assert all(
        "These prepared attachments will be sent with your response." not in str(message.get("content", ""))
        for message in step_state.messages
    )


@pytest.mark.asyncio
async def test_step_executor_collects_assistant_message_payload_from_tool_results(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Send the selected photos.", attachments=[], user_id=None, session_id=None),
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
                    "asset_refs": [
                        {"asset_ref_id": "photo-1", "event_id": "evt-1", "original_name": "hangzhou.jpg"}
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
        execution_preset="chat",
        execution_agent_id="chat:s-chat",
        run_id="run-payload",
    )

    assert outcome.status == "continue"
    assert step_state.message_payload == {
        "asset_refs": [
            {
                "asset_ref_id": "photo-1",
                "event_id": "evt-1",
                "original_name": "hangzhou.jpg",
            }
        ]
    }


@pytest.mark.asyncio
async def test_step_executor_collects_historical_recall_asset_refs_into_message_payload(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Send the recalled photo.", attachments=[], user_id=None, session_id=None),
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
                "historical_recall": {
                    "summary": "2022年9月2号傍晚在杭州拍了一张照片。",
                    "asset_refs": [
                        {
                            "asset_ref_id": "asset-1",
                            "event_id": "evt-1",
                            "original_name": "hangzhou.jpg",
                            "resolver_tool": "photo_library_resolve_photo_refs",
                        }
                    ],
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
        user_message="Send the recalled photo.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-memory-payload",
        execution_preset="chat",
        execution_agent_id="chat:s-chat",
        run_id="run-memory-payload",
    )

    assert outcome.status == "continue"
    assert step_state.message_payload == {
        "asset_refs": [
            {
                "asset_ref_id": "asset-1",
                "event_id": "evt-1",
                "original_name": "hangzhou.jpg",
                "resolver_tool": "photo_library_resolve_photo_refs",
            }
        ]
    }


@pytest.mark.asyncio
async def test_step_executor_returns_control_after_one_step_until_called_again(monkeypatch) -> None:
    orchestrator = _build_orchestrator()
    step_state = orchestrator.build_step_state(
        turn=UserTurnInput(text="Inspect the repository.", attachments=[], user_id=None, session_id=None),
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
        execution_preset="repo_analysis",
        execution_agent_id="chat:s-chat",
        run_id="run-1",
    )
    second_outcome = await orchestrator.step_executor.execute_step(
        state=step_state,
        user_message="Inspect the repository.",
        user_id="u-chat",
        session_id="s-chat",
        turn_id="turn-1",
        execution_preset="repo_analysis",
        execution_agent_id="chat:s-chat",
        run_id="run-1",
    )

    assert first_outcome.status == "continue"
    assert second_outcome.status == "completed"
    assert second_outcome.content == "Here is the final answer."
    assert step_state.iteration == 2


def test_replan_blocked_for_terminal_provider_configuration_error() -> None:
    """Terminal provider errors should stop the loop instead of chasing fallback tools."""
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
    assert allowed is False


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
