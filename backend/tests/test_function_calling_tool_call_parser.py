from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.agent.execution.function_calling_postprocessor import FunctionCallingPostprocessor
from magi.agent.execution.function_calling import FunctionCallingExecutor, ToolCall, ToolCallResult
from magi.tools.schema import ToolResult


class _DummyLLMAdapter(LLMAdapter):
    def __init__(self, client: Any = None) -> None:
        self._model = "dummy-model"
        self._client = client

    async def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        _ = (prompt, max_tokens, temperature, kwargs)
        return ""

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        _ = (prompt, max_tokens, temperature, kwargs)
        if False:
            yield ""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        _ = (messages, max_tokens, temperature, kwargs)
        return ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        _ = (messages, max_tokens, temperature, kwargs)
        if False:
            yield ""

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"


class _RecordingToolRegistry:
    def __init__(self) -> None:
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    def is_skill(self, name: str) -> bool:
        _ = name
        return False

    def get_tool_info(self, name: str) -> Dict[str, Any] | None:
        if name in {"bash", "agent"}:
            return {
                "name": name,
                "description": name,
                "parameters": [],
                "dangerous": False,
            }
        return None

    async def execute(self, name: str, arguments: Dict[str, Any], context: Any) -> ToolResult:
        _ = context
        self.calls.append((name, dict(arguments)))
        return ToolResult(success=True, data={"ok": True, "tool": name, "arguments": arguments})


class _PlannerRegistry(_RecordingToolRegistry):
    async def execute(self, name: str, arguments: Dict[str, Any], context: Any) -> ToolResult:
        _ = context
        self.calls.append((name, dict(arguments)))
        if name != "agent":
            return ToolResult(success=False, error="unsupported")
        if arguments.get("subagent_type") == "Plan":
            return ToolResult(
                success=True,
                data={
                    "worker_id": "worker_plan_1",
                    "status": "completed",
                    "subagent_type": "Plan",
                    "description": arguments.get("description"),
                    "result": (
                        '{"summary":"Repo architecture split into focused scans.",'
                        '"subtasks":[{"description":"scan backend","subagent_type":"Explore","prompt":"Inspect backend layout","parallel_group":"g1"},'
                        '{"description":"scan frontend","subagent_type":"Explore","prompt":"Inspect frontend layout","parallel_group":"g1"}]}'
                    ),
                },
            )
        workers = arguments.get("workers", [])
        return ToolResult(
            success=True,
            data={
                "workers": [
                    {
                        "worker_id": f"worker_{idx}",
                        "status": "completed",
                        "subagent_type": worker.get("subagent_type"),
                        "description": worker.get("description"),
                        "result": f"completed {worker.get('description')}",
                    }
                    for idx, worker in enumerate(workers, start=1)
                ]
            },
        )


class _DummyOpenAIClient:
    def __init__(self, contents: List[str]) -> None:
        self._contents = list(contents)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        content = self._contents.pop(0)
        message = SimpleNamespace(content=content, tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.asyncio
async def test_execute_with_tools_runs_legacy_tool_call_blocks() -> None:
    registry = _RecordingToolRegistry()
    llm = _DummyLLMAdapter(
        client=_DummyOpenAIClient(
            contents=[
                (
                    "<tool_call>bash"
                    "<arg_key>command</arg_key><arg_value>echo one</arg_value>"
                    "</tool_call>"
                    "<tool_call>agent"
                    "<arg_key>timeout_seconds</arg_key><arg_value>5</arg_value>"
                    "</tool_call>"
                ),
                "final answer",
            ]
        )
    )
    executor = FunctionCallingExecutor(
        llm_adapter=llm,
        tool_registry=registry,  # type: ignore[arg-type]
    )

    result = await executor.execute_with_tools(
        user_message="run legacy tool calls",
        system_prompt="sys",
        selected_tools=["bash", "agent"],
        user_id="u1",
        max_iterations=3,
    )

    assert result.status == "completed"
    assert result.content == "final answer"
    assert len(registry.calls) == 2
    assert registry.calls[0] == ("bash", {"command": "echo one"})
    assert registry.calls[1] == ("agent", {"timeout_seconds": 5, "run_in_background": True})


def test_build_tool_message_payload_compacts_glob_matches() -> None:
    postprocessor = FunctionCallingPostprocessor()
    matches = [
        {
            "path": f"/tmp/file_{i}.py",
            "name": f"file_{i}.py",
            "is_file": True,
            "is_dir": False,
            "size": i,
            "modified": i,
        }
        for i in range(45)
    ]
    payload = postprocessor.build_tool_message_payload(
        tool_name="glob",
        result=ToolCallResult(
            tool_call_id="t1",
            tool_name="glob",
            success=True,
            data={"pattern": "**/*.py", "base_path": "/tmp", "matches": matches, "count": len(matches)},
            error=None,
        ),
    )

    assert payload["success"] is True
    assert payload["data"]["count"] == 45
    assert payload["data"]["omitted_matches"] == 5
    assert len(payload["data"]["matches"]) == 40
    assert payload["data"]["matches"][0]["path"] == "/tmp/file_0.py"
    assert "size" not in payload["data"]["matches"][0]
    assert "modified" not in payload["data"]["matches"][0]


@pytest.mark.asyncio
async def test_max_iterations_fallback_executes_legacy_tool_call_once() -> None:
    registry = _RecordingToolRegistry()
    executor = FunctionCallingExecutor(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=registry,  # type: ignore[arg-type]
    )

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {
            "content": "",
            "assistant_message": {"role": "assistant", "content": ""},
            "tool_calls": [ToolCall(id="call_1", name="bash", arguments={"command": "echo one"})],
        }

    async def _fake_call_llm_without_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        _fake_call_llm_without_tools.calls += 1
        if _fake_call_llm_without_tools.calls == 1:
            return {
                "content": "",
                "tool_calls": [ToolCall(id="legacy_call_1", name="agent", arguments={"timeout_seconds": 5})],
            }
        return {"content": "final answer"}

    _fake_call_llm_without_tools.calls = 0  # type: ignore[attr-defined]
    executor._call_llm_with_tools = _fake_call_llm_with_tools  # type: ignore[method-assign]
    executor._call_llm_without_tools = _fake_call_llm_without_tools  # type: ignore[method-assign]

    result = await executor.execute_with_tools(
        user_message="run tools",
        system_prompt="sys",
        selected_tools=["bash", "agent"],
        user_id="u1",
        max_iterations=1,
    )

    assert result.status == "completed"
    assert result.content == "final answer"
    assert _fake_call_llm_without_tools.calls == 2  # type: ignore[attr-defined]
    assert registry.calls == [
        ("bash", {"command": "echo one"}),
        ("agent", {"timeout_seconds": 5, "run_in_background": True}),
    ]


def test_build_tool_message_payload_compacts_agent_run_state() -> None:
    postprocessor = FunctionCallingPostprocessor()
    payload = postprocessor.build_tool_message_payload(
        tool_name="agent",
        result=ToolCallResult(
            tool_call_id="t2",
            tool_name="agent",
            success=True,
            data={
                "worker_id": "worker_123",
                "status": "completed",
                "subagent_type": "Explore",
                "description": "scan auth flow",
                "created_at": 1.0,
                "updated_at": 2.0,
                "target_task_agent_id": "web_user",
                "result": "Found auth flow entry points in backend/src/...",
            },
            error=None,
        ),
    )

    assert payload["data"]["worker_id"] == "worker_123"
    assert payload["data"]["result_summary"].startswith("Found auth flow")
    assert "created_at" not in payload["data"]
    assert "target_task_agent_id" not in payload["data"]


def test_compact_message_history_preserves_protocol_for_multi_tool_blocks() -> None:
    executor = FunctionCallingExecutor(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )
    messages: List[Dict[str, Any]] = [{"role": "user", "content": "analyze repo"}]

    for index in range(1, 6):
        tool_name = f"tool_{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{index}",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call_{index}",
                "content": json.dumps({"success": True, "data": {"result_summary": f"ok {index}"}, "error": None}),
            }
        )

    messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_6_a",
                    "type": "function",
                    "function": {"name": "glob", "arguments": "{}"},
                },
                {
                    "id": "call_6_b",
                    "type": "function",
                    "function": {"name": "grep", "arguments": "{}"},
                },
            ],
        }
    )
    messages.append(
        {
            "role": "tool",
            "tool_call_id": "call_6_a",
            "content": json.dumps({"success": True, "data": {"count": 3}, "error": None}),
        }
    )

    executor._compact_message_history(messages)

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"].startswith("Previous tool activity summary:\n")

    seen_tool_block = False
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        previous = messages[index - 1] if index > 0 else {}
        assert previous.get("role") in {"assistant", "tool"}
        if previous.get("role") == "assistant":
            assert previous.get("tool_calls")
            seen_tool_block = True

    assert seen_tool_block is True
    assert messages[-2]["role"] == "assistant"
    assert len(messages[-2]["tool_calls"]) == 2
    assert messages[-1]["role"] == "tool"


@pytest.mark.asyncio
async def test_agent_plan_workflow_orchestrates_subtasks() -> None:
    registry = _PlannerRegistry()
    executor = FunctionCallingExecutor(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=registry,  # type: ignore[arg-type]
    )

    result = await executor._execute_tool_call(
        tool_call=ToolCall(
            id="call_plan",
            name="agent",
            arguments={
                "action": "launch",
                "description": "Analyze repo architecture",
                "prompt": "Analyze the repo and split work.",
            },
        ),
        user_id="u1",
        session_id="s1",
        intent="planning",
        execution_agent_id="chat_agent",
        execution_workspace="/tmp",
        worker_strategy={
            "preferred_subagent_type": "Plan",
            "execution_mode": "plan_and_decompose",
            "enforce_subagent_type": True,
        },
    )

    assert result.success is True
    assert registry.calls[0][1]["subagent_type"] == "Plan"
    assert registry.calls[1][1]["workers"][0]["subagent_type"] == "Explore"
    assert result.data["workers"][0]["result_summary"] == "completed scan backend"
