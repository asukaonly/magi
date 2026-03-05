from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.llm.provider_bridge import ProviderResponse
from magi.tools.function_calling import FunctionCallingExecutor
from magi.tools.schema import ToolResult


class _DummyLLMAdapter(LLMAdapter):
    def __init__(self) -> None:
        self._model = "dummy-model"

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


def test_parse_legacy_tool_call_content_with_type_coercion() -> None:
    registry = _RecordingToolRegistry()
    executor = FunctionCallingExecutor(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=registry,  # type: ignore[arg-type]
    )

    content = (
        "<tool_call>agent"
        "<arg_key>timeout_seconds</arg_key><arg_value>30</arg_value>"
        "<arg_key>run_in_background</arg_key><arg_value>false</arg_value>"
        "<arg_key>description</arg_key><arg_value>analyze repo</arg_value>"
        "</tool_call>"
    )
    parsed = executor._parse_tool_calls_from_content(content)

    assert len(parsed) == 1
    assert parsed[0].name == "agent"
    assert parsed[0].arguments["timeout_seconds"] == 30
    assert parsed[0].arguments["run_in_background"] is False
    assert parsed[0].arguments["description"] == "analyze repo"


@pytest.mark.asyncio
async def test_execute_with_tools_runs_legacy_tool_call_blocks() -> None:
    registry = _RecordingToolRegistry()
    executor = FunctionCallingExecutor(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=registry,  # type: ignore[arg-type]
    )

    responses = [
        ProviderResponse(
            content=(
                "<tool_call>bash"
                "<arg_key>command</arg_key><arg_value>echo one</arg_value>"
                "</tool_call>"
                "<tool_call>agent"
                "<arg_key>timeout_seconds</arg_key><arg_value>5</arg_value>"
                "</tool_call>"
            )
        ),
        ProviderResponse(content="final answer"),
    ]

    async def _fake_chat_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return responses.pop(0)

    executor.provider_bridge.chat_with_tools = _fake_chat_with_tools  # type: ignore[method-assign]

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

