from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.tools.function_calling_postprocessor import FunctionCallingPostprocessor
from magi.tools.function_calling import FunctionCallingExecutor, ToolCall, ToolCallResult
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

    assert result == "final answer"
    assert len(registry.calls) == 2
    assert registry.calls[0] == ("bash", {"command": "echo one"})
    assert registry.calls[1] == ("agent", {"timeout_seconds": 5})


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

    assert result == "final answer"
    assert _fake_call_llm_without_tools.calls == 2  # type: ignore[attr-defined]
    assert registry.calls == [
        ("bash", {"command": "echo one"}),
        ("agent", {"timeout_seconds": 5}),
    ]
