from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import ProviderResponse, ProviderToolCall
from magi.agent.execution.function_calling_postprocessor import FunctionCallingPostprocessor
from magi.agent.execution import function_calling as function_calling_module
from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall, ToolCallResult
from magi.config.models import ThinkingDepth
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


class _SequencedToolRegistry:
    def __init__(self, results: Dict[str, List[ToolResult]]) -> None:
        self._results = {name: list(items) for name, items in results.items()}
        self.calls: List[tuple[str, Dict[str, Any]]] = []

    def is_skill(self, name: str) -> bool:
        _ = name
        return False

    def get_tool_info(self, name: str) -> Dict[str, Any] | None:
        return {
            "name": name,
            "description": name,
            "parameters": [],
            "dangerous": False,
        }

    async def execute(self, name: str, arguments: Dict[str, Any], context: Any) -> ToolResult:
        _ = context
        self.calls.append((name, dict(arguments)))
        queue = self._results.get(name, [])
        if queue:
            return queue.pop(0)
        return ToolResult(success=False, error="unexpected tool call", error_code="EXECUTION_ERROR")


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
    executor = FunctionCallingOrchestrator(
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


def test_build_tool_message_payload_keeps_structured_worker_result() -> None:
    postprocessor = FunctionCallingPostprocessor()
    payload = postprocessor.build_tool_message_payload(
        tool_name="agent",
        result=ToolCallResult(
            tool_call_id="a1",
            tool_name="agent",
            success=True,
            data={
                "worker_id": "worker_1",
                "status": "completed",
                "subagent_type": "Explore",
                "description": "scan backend",
                "result": {
                    "summary": "backend analyzed",
                    "findings": [{"title": "backend", "detail": "runtime path"}],
                    "evidence": [{"path": "/tmp/backend.py", "detail": "entrypoint"}],
                    "gaps": [],
                    "next_steps": ["aggregate"],
                },
            },
            error=None,
        ),
    )

    assert payload["success"] is True
    assert payload["data"]["worker_result"]["summary"] == "backend analyzed"
    assert payload["data"]["worker_id"] == "worker_1"


def test_build_tool_message_payload_includes_recovery_guidance_for_ambiguous_scope() -> None:
    postprocessor = FunctionCallingPostprocessor()
    payload = postprocessor.build_tool_message_payload(
        tool_name="glob",
        result=ToolCallResult(
            tool_call_id="g1",
            tool_name="glob",
            success=False,
            data=None,
            error="File scan guardrail: glob and grep must stay within the active workspace.",
            error_code="AMBIGUOUS_SCOPE",
        ),
    )

    assert payload["error_code"] == "AMBIGUOUS_SCOPE"
    assert "Ask the user for an explicit path or use web-search" in payload["recovery_guidance"]


@pytest.mark.asyncio
async def test_max_iterations_fallback_executes_legacy_tool_call_once() -> None:
    registry = _RecordingToolRegistry()
    executor = FunctionCallingOrchestrator(
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


@pytest.mark.asyncio
async def test_max_iterations_fallback_forces_plain_text_after_repeated_legacy_tool_calls() -> None:
    registry = _RecordingToolRegistry()
    executor = FunctionCallingOrchestrator(
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

    captured_calls: list[dict[str, Any]] = []

    async def _fake_call_llm_without_tools(**kwargs):  # type: ignore[no-untyped-def]
        captured_calls.append(kwargs)
        call_index = len(captured_calls)
        if call_index == 1:
            return {
                "content": "",
                "tool_calls": [ToolCall(id="legacy_call_1", name="agent", arguments={"timeout_seconds": 5})],
            }
        if call_index == 2:
            return {
                "content": "",
                "tool_calls": [ToolCall(id="legacy_call_2", name="grep", arguments={"pattern": "x", "path": "."})],
            }
        return {"content": "final explanation"}

    executor._call_llm_with_tools = _fake_call_llm_with_tools  # type: ignore[method-assign]
    executor._call_llm_without_tools = _fake_call_llm_without_tools  # type: ignore[method-assign]

    result = await executor.execute_with_tools(
        user_message="run tools",
        system_prompt="sys\n# Tool Information\nuse tools",
        selected_tools=["bash", "agent", "grep"],
        user_id="u1",
        max_iterations=1,
    )

    assert result.status == "completed"
    assert result.content == "final explanation"
    assert len(captured_calls) == 3
    assert "Tool Information" not in captured_calls[0]["system_prompt"]
    assert "Do not emit tool calls" in captured_calls[0]["system_prompt"]
    assert captured_calls[2]["thinking_depth"] == ThinkingDepth.NONE
    assert "This is the final retry" in captured_calls[2]["messages"][-1]["content"]
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
                "target_task_agent_id": "local_user",
                "result": "Found auth flow entry points in backend/src/...",
            },
            error=None,
        ),
    )

    assert payload["data"]["worker_id"] == "worker_123"
    assert payload["data"]["worker_result"] is None
    assert "created_at" not in payload["data"]
    assert "target_task_agent_id" not in payload["data"]


def test_compact_message_history_preserves_protocol_for_multi_tool_blocks() -> None:
    executor = FunctionCallingOrchestrator(
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


def test_build_final_response_system_prompt_removes_tool_guidance() -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    system_prompt = (
        "# System Information\n"
        "* Time: now\n"
        "# Tool Information\n"
        "## Selected Tools\n"
        "* grep\n"
        "Tool recovery rules:\n"
        "- use tools\n"
    )

    final_prompt = executor._build_final_response_system_prompt(system_prompt, strict_plain_text=True)

    assert "# Tool Information" not in final_prompt
    assert "Tool recovery rules" not in final_prompt
    assert "Tools are no longer available in this step." in final_prompt
    assert "Do not emit tool calls" in final_prompt
    assert "This is the final retry" not in final_prompt


def test_build_final_response_system_prompt_prioritizes_memory_query_results() -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    system_prompt = (
        "# System Information\n"
        "* Time: now\n"
        "# Memory Query Guidance\n"
        "Use `memory_query` before answering.\n"
        "# Tool Information\n"
        "## Selected Tools\n"
        "* memory_query\n"
    )

    final_prompt = executor._build_final_response_system_prompt(system_prompt, strict_plain_text=True)

    assert "memory_query results as the source of truth" in final_prompt
    assert "Do not replace missing recall results with implicit memory" in final_prompt


def test_postprocessor_marks_memory_query_results_as_source_of_truth() -> None:
    postprocessor = FunctionCallingPostprocessor()
    result = type(
        "Result",
        (),
        {
            "success": True,
            "data": {
                "historical_recall": {
                    "status": "found",
                    "summary": "Yesterday browsing happened.",
                    "findings": [],
                    "insufficient_evidence": False,
                    "answering_hints": {},
                    "provenance": {"primary_count": 1, "source_layers": ["L1"]},
                },
                "debug": {"retrieval_trace": {"query_mode": "detail"}},
            },
            "error": None,
        },
    )()

    payload = postprocessor.build_tool_message_payload("memory_query", result)

    assert payload["source_of_truth_for_turn"] is True
    assert payload["context_role"] == "historical_recall_result"
    assert "implicit memory" in payload["usage_guidance"]


def test_build_tool_message_payload_keeps_only_projected_historical_recall_for_memory_query() -> None:
    postprocessor = FunctionCallingPostprocessor(max_items=2, max_text_chars=80)
    result = type(
        "Result",
        (),
        {
            "success": True,
            "data": {
                "historical_recall": {
                    "status": "found",
                    "query_mode": "detail",
                    "summary": "You like rainy weather.",
                    "findings": [
                        {
                            "kind": "relationship",
                            "statement": "user:u1 LIKES weather_state:rainy",
                            "source_layer": "L2",
                            "confidence": 0.94,
                            "status": "active",
                            "occurred_at": None,
                            "updated_at": 1773999236.11,
                            "evidence_ref_ids": ["triple-1"],
                        }
                    ],
                    "insufficient_evidence": False,
                    "answering_hints": {
                        "must_not_guess_when_empty": True,
                        "prefer_direct_findings": True,
                    },
                    "provenance": {
                        "primary_count": 1,
                        "source_layers": ["L2"],
                    },
                },
                "debug": {
                    "retrieval_trace": {
                        "intent_source": "llm",
                        "l2_query_trace": {"resolved_entities": [{"entity_id": "user:u1"}]},
                    }
                },
            },
            "error": None,
        },
    )()

    payload = postprocessor.build_tool_message_payload("memory_query", result)

    assert payload["data"] == {
        "historical_recall": {
            "status": "found",
            "query_mode": "detail",
            "summary": "You like rainy weather.",
            "findings": [
                {
                    "kind": "relationship",
                    "statement": "user:u1 LIKES weather_state:rainy",
                    "source_layer": "L2",
                    "confidence": 0.94,
                    "status": "active",
                    "occurred_at": None,
                    "updated_at": 1773999236.11,
                    "evidence_ref_ids": ["triple-1"],
                }
            ],
            "insufficient_evidence": False,
            "answering_hints": {
                "must_not_guess_when_empty": True,
                "prefer_direct_findings": True,
            },
            "provenance": {
                "primary_count": 1,
                "source_layers": ["L2"],
            },
        }
    }


def test_postprocessor_uses_registered_tool_context_formatter() -> None:
    from magi.agent.execution.tool_context_formatters import ToolContextFormatterRegistry

    registry = ToolContextFormatterRegistry()
    registry.register("demo", lambda data: {"custom": data.get("value")})
    postprocessor = FunctionCallingPostprocessor(formatter_registry=registry)

    payload = postprocessor.build_tool_message_payload(
        tool_name="demo",
        result=ToolCallResult(
            tool_call_id="d1",
            tool_name="demo",
            success=True,
            data={"value": 42, "ignored": "x"},
            error=None,
        ),
    )

    assert payload["data"] == {"custom": 42}


@pytest.mark.asyncio
async def test_agent_launch_uses_orchestration_default_leaf_type() -> None:
    registry = _RecordingToolRegistry()
    executor = FunctionCallingOrchestrator(
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
        turn_id="turn_1",
        intent="planning",
        execution_agent_id="chat_agent",
        execution_workspace="/tmp",
        orchestration_strategy={
            "mode": "decompose",
            "planner": "task_agent",
            "default_leaf_type": "Explore",
            "allow_parallel": True,
        },
    )

    assert result.success is True
    assert registry.calls == [
        (
            "agent",
            {
                "action": "launch",
                "description": "Analyze repo architecture",
                "prompt": "Analyze the repo and split work.",
                "run_in_background": True,
                "subagent_type": "Explore",
            },
        )
    ]


@pytest.mark.asyncio
async def test_execute_with_tools_replans_after_recoverable_tool_failure() -> None:
    registry = _SequencedToolRegistry(
        results={
            "grep": [
                ToolResult(
                    success=False,
                    error="Explore worker guardrail: root-wide grep is blocked.",
                    error_code="INVALID_PARAMETERS",
                )
            ],
            "glob": [
                ToolResult(
                    success=True,
                    data={"matches": [{"path": "/tmp/backend/app.py"}], "count": 1},
                )
            ],
        }
    )
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=registry,  # type: ignore[arg-type]
    )

    llm_calls: list[dict[str, Any]] = []

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        llm_calls.append(kwargs)
        call_index = len(llm_calls)
        if call_index == 1:
            return {
                "content": "",
                "assistant_message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_grep",
                            "type": "function",
                            "function": {"name": "grep", "arguments": "{}"},
                        }
                    ],
                },
                "tool_calls": [ToolCall(id="call_grep", name="grep", arguments={"pattern": "TODO", "glob": "**/*"})],
            }
        if call_index == 2:
            return {
                "content": "",
                "assistant_message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_glob",
                            "type": "function",
                            "function": {"name": "glob", "arguments": "{}"},
                        }
                    ],
                },
                "tool_calls": [ToolCall(id="call_glob", name="glob", arguments={"pattern": "backend/**/*.py"})],
            }
        return {
            "content": "Recovered with a narrower scan.",
            "assistant_message": {"role": "assistant", "content": "Recovered with a narrower scan."},
            "tool_calls": [],
        }

    executor._call_llm_with_tools = _fake_call_llm_with_tools  # type: ignore[method-assign]

    result = await executor.execute_with_tools(
        user_message="inspect backend",
        system_prompt="sys",
        selected_tools=["grep", "glob"],
        user_id="u1",
        max_iterations=4,
    )

    assert result.status == "completed"
    assert result.content == "Recovered with a narrower scan."
    assert [call[0] for call in registry.calls] == ["grep", "glob"]
    assert len(llm_calls) == 3
    assert "Tool recovery rules:" in llm_calls[0]["system_prompt"]
    assert result.tool_failures[0]["error_code"] == "INVALID_PARAMETERS"


def test_classify_final_failure_returns_ambiguous_scope_for_scope_only_failures() -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    failure = executor._classify_final_failure(
        [
            {
                "tool_call_id": "call_1",
                "tool_name": "glob",
                "error": "workspace boundary blocked",
                "error_code": "AMBIGUOUS_SCOPE",
                "execution_time": 0.01,
            }
        ],
        all_tools_failed=True,
    )

    assert failure == "AMBIGUOUS_SCOPE"


@pytest.mark.asyncio
async def test_execute_with_tools_stops_replanning_for_non_recoverable_tool_failure() -> None:
    registry = _SequencedToolRegistry(
        results={
            "web_search": [
                ToolResult(
                    success=False,
                    error="No providers configured",
                    error_code="NO_PROVIDERS_CONFIGURED",
                )
            ]
        }
    )
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=registry,  # type: ignore[arg-type]
    )

    llm_calls: list[dict[str, Any]] = []

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        llm_calls.append(kwargs)
        return {
            "content": "",
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_search",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [ToolCall(id="call_search", name="web_search", arguments={"query": "magi"})],
        }

    async def _fake_call_llm_without_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return {"content": ""}

    executor._call_llm_with_tools = _fake_call_llm_with_tools  # type: ignore[method-assign]
    executor._call_llm_without_tools = _fake_call_llm_without_tools  # type: ignore[method-assign]

    result = await executor.execute_with_tools(
        user_message="search docs",
        system_prompt="sys",
        selected_tools=["web_search"],
        user_id="u1",
        max_iterations=4,
    )

    assert result.status == "failed"
    assert result.failure_reason == "ALL_TOOLS_FAILED"
    assert len(llm_calls) == 1


@pytest.mark.asyncio
async def test_call_llm_without_tools_logs_provider_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    captured: dict[str, Any] = {}

    async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return ProviderResponse(
            content="",
            metadata={
                "finish_reason": "length",
                "has_content": False,
                "raw_message": {"content": None, "reasoning_content": "partial"},
            },
        )

    def _fake_log_llm_response(logger, request_id, response, success=True, error=None, duration_ms=None, truncate=True, response_max_length=3000, **metadata):  # type: ignore[no-untyped-def]
        _ = (logger, request_id, response, success, error, duration_ms, truncate, response_max_length)
        captured.update(metadata)

    executor.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]
    monkeypatch.setattr(function_calling_module, "log_llm_response", _fake_log_llm_response)

    result = await executor._call_llm_without_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "why"}],
        thinking_depth=ThinkingDepth.HIGH,
    )

    assert result["content"] == ""
    assert captured["fallback_reason"] == "function_calling_final_response_without_tools"
    assert captured["finish_reason"] == "length"
    assert captured["has_content"] is False
    assert captured["raw_message"]["reasoning_content"] == "partial"
    assert result["llm_trace"]["model"] == "dummy-model"
    assert result["llm_trace"]["thinking_enabled"] is True


@pytest.mark.asyncio
async def test_call_llm_with_tools_logs_json_response_without_ascii_escaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    captured: dict[str, Any] = {}

    async def _fake_chat_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return ProviderResponse(
            content="",
            assistant_message={
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "memory_query",
                            "arguments": '{"query":"我喜欢什么天气","note":"用户喜欢下雨天"}',
                        },
                    }
                ],
            },
            tool_calls=[
                ProviderToolCall(
                    id="call_1",
                    name="memory_query",
                    arguments={"query": "我喜欢什么天气", "note": "用户喜欢下雨天"},
                )
            ],
        )

    def _fake_log_llm_response(logger, request_id, response, success=True, error=None, duration_ms=None, truncate=True, response_max_length=3000, **metadata):  # type: ignore[no-untyped-def]
        _ = (logger, request_id, success, error, duration_ms, truncate, response_max_length, metadata)
        captured["response"] = response

    executor.provider_bridge.chat_with_tools = _fake_chat_with_tools  # type: ignore[method-assign]
    monkeypatch.setattr(function_calling_module, "log_llm_response", _fake_log_llm_response)

    await executor._call_llm_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "我喜欢什么天气"}],
        tools=[],
        thinking_depth=ThinkingDepth.NONE,
        timeout_seconds=30.0,
    )

    assert '"assistant_message"' in captured["response"]
    assert '"tool_calls"' in captured["response"]
    assert "用户喜欢下雨天" in captured["response"]
    assert "\\u7528\\u6237" not in captured["response"]


@pytest.mark.asyncio
async def test_call_llm_without_tools_forwards_json_mode_and_timeout() -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    captured: dict[str, Any] = {}

    async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return ProviderResponse(content='{"result_status":"success"}')

    executor.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

    result = await executor._call_llm_without_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "why"}],
        thinking_depth=ThinkingDepth.HIGH,
        json_mode=True,
        timeout_seconds=180.0,
    )

    assert result["content"] == '{"result_status":"success"}'
    assert captured["json_mode"] is True
    assert captured["timeout_seconds"] == 180.0


@pytest.mark.asyncio
async def test_call_llm_with_tools_uses_extended_timeout_when_thinking_enabled() -> None:
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_RecordingToolRegistry(),  # type: ignore[arg-type]
    )

    captured: dict[str, Any] = {}

    async def _fake_chat_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return ProviderResponse(
            content="",
            metadata={
                "trace_metrics": {
                    "provider": "openai",
                    "model": "dummy-model",
                    "input_tokens": 22,
                    "output_tokens": 6,
                    "total_tokens": 28,
                    "thinking_enabled": True,
                    "duration_ms": 1500,
                }
            },
        )

    executor.provider_bridge.chat_with_tools = _fake_chat_with_tools  # type: ignore[method-assign]

    result = await executor._call_llm_with_tools(
        system_prompt="sys",
        messages=[{"role": "user", "content": "plan"}],
        tools=[],
        thinking_depth=ThinkingDepth.HIGH,
    )

    assert captured["timeout_seconds"] == 180.0
    assert result["llm_trace"]["input_tokens"] == 22
    assert result["llm_trace"]["thinking_enabled"] is True
