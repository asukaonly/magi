from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.tools.function_calling import FunctionCallingExecutor
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
