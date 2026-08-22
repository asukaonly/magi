from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.agent.execution.task_budget import (
    TaskBudgetExceeded,
    task_execution_budget_scope,
)
from magi.llm.base import LLMAdapter
from magi.config.models import LLMScenario
from magi.tools.context_decider import ContextDecider
from magi.tools.context_decider_context import ContextDeciderContext


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


class _DummyToolRegistry:
    _skills: Dict[str, Any] = {}

    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        return [{"name": "agent", "description": "worker launch", "type": "tool"}]

    def list_tools(self) -> List[str]:
        return ["agent"]

    def is_skill(self, name: str) -> bool:
        _ = name
        return False


class _RecordingLLMPool:
    def __init__(self, adapter: LLMAdapter | None) -> None:
        self.adapter = adapter
        self.requested: list[LLMScenario] = []

    def get(self, scenario: LLMScenario) -> LLMAdapter | None:
        self.requested.append(scenario)
        return self.adapter


@pytest.mark.asyncio
async def test_context_decider_always_disables_thinking() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]
    seen: Dict[str, Any] = {}

    async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return SimpleNamespace(
            content='{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok"}',
            metadata={},
        )

    decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

    await decider.decide(
        "hello",
        ContextDeciderContext(
            os_name="Darwin",
            os_version="25.0.0",
            current_datetime="2026-03-25T12:00:00+08:00",
            timezone="Asia/Shanghai",
        ),
    )

    assert seen["disable_thinking"] is True


@pytest.mark.asyncio
async def test_context_decider_charges_one_logical_call_per_provider_request() -> None:
    decider = ContextDecider(
        tool_registry=_DummyToolRegistry(),
        llm_adapter=_DummyLLMAdapter(),
    )  # type: ignore[arg-type]
    provider_calls = 0

    async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal provider_calls
        _ = kwargs
        provider_calls += 1
        return SimpleNamespace(content="{}", metadata={})

    decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

    async with task_execution_budget_scope(max_llm_calls=1) as budget:
        await decider._call_provider("request-1", "route this")
        with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
            await decider._call_provider("request-2", "route this too")

    assert provider_calls == 1
    assert budget.llm_calls == 1


@pytest.mark.asyncio
async def test_context_decider_requests_context_scenario_from_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _RecordingLLMPool(_DummyLLMAdapter())
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_pool=pool)  # type: ignore[arg-type]

    class _FakeBridge:
        async def chat_response(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content='{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok"}',
                metadata={},
            )

    monkeypatch.setattr(decider, "provider_bridge", _FakeBridge())

    await decider.decide("hello")

    assert pool.requested
    assert all(item == LLMScenario.CONTEXT_DECIDER for item in pool.requested)


@pytest.mark.asyncio
async def test_context_decider_ignores_context_toggle_and_keeps_disable_thinking_true() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]
    seen: Dict[str, Any] = {}

    async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return SimpleNamespace(
            content='{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok"}',
            metadata={},
        )

    decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

    await decider.decide(
        "hello",
        ContextDeciderContext(
            os_name="Darwin",
            os_version="25.0.0",
            current_datetime="2026-03-25T12:00:00+08:00",
            timezone="Asia/Shanghai",
        ),
    )

    assert seen["disable_thinking"] is True


def test_context_decider_prompt_includes_recent_tool_error_config_path() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    prompt = decider._build_prompt(
        "要配什么key",
        [{"name": "weather", "description": "Weather tool", "type": "tool"}],
        ContextDeciderContext(
            os_name="Darwin",
            os_version="25.0.0",
            current_datetime="2026-03-25T12:00:00+08:00",
            timezone="Asia/Shanghai",
            recent_tool_errors=[
                {
                    "tool_name": "weather",
                    "error_code": "PROVIDER_NOT_CONFIGURED",
                    "error_message": "Missing API key",
                    "config_path": "tool.weather.providers.qweather.api_key",
                    "next_action": "configure_qweather_api_key",
                }
            ],
        ),
    )

    assert "config_path=tool.weather.providers.qweather.api_key" in prompt
    assert "next_action=configure_qweather_api_key" in prompt
    assert "- OS: Darwin 25.0.0" in prompt
    assert "- Current datetime: 2026-03-25T12:00:00+08:00" in prompt
    assert "- Timezone: Asia/Shanghai" in prompt


def test_context_decider_prompt_excludes_latest_user_message_from_recent_conversation() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    prompt = decider._build_prompt(
        "你是谁啊",
        [{"name": "agent", "description": "worker launch", "type": "tool"}],
        ContextDeciderContext(
            os_name="Darwin",
            os_version="25.0.0",
            current_datetime="2026-03-25T12:00:00+08:00",
            timezone="Asia/Shanghai",
            recent_messages=[
                {"role": "user", "content": "你是谁啊"},
            ],
        ),
    )

    assert prompt.count("- user: 你是谁啊") == 0
    assert "## User Request\n\n你是谁啊" in prompt


def test_context_decider_prompt_includes_routing_environment_fields() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    prompt = decider._build_prompt(
        "hello",
        [{"name": "agent", "description": "worker launch", "type": "tool"}],
        ContextDeciderContext(
            os_name="Darwin",
            os_version="25.0.0",
            current_datetime="2026-03-25T12:00:00+08:00",
            timezone="Asia/Shanghai",
            workspace_path="/tmp/workspace",
            home_dir="/Users/example",
        ),
    )

    assert "- OS: Darwin 25.0.0" in prompt
    assert "- Current datetime: 2026-03-25T12:00:00+08:00" in prompt
    assert "- Timezone: Asia/Shanghai" in prompt
    assert "- Workspace path: /tmp/workspace" in prompt
    assert "- Home directory: /Users/example" in prompt


def test_context_decider_system_prompt_keeps_core_routing_guardrails() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    system_prompt = decider.system_PROMPT

    assert "Respond with a SINGLE valid JSON object" in system_prompt
    assert "Prefer `memory_query` for stored user preferences" in system_prompt
    assert "Prefer `trace_query` when the user asks about exact recent tool calls" in system_prompt
    assert "For code changes, debugging, or repo investigation, prefer `agent`" in system_prompt
    assert "Use these as routing patterns, not literal keyword rules." in system_prompt
    assert "photo_library_resolve_photo_refs" in system_prompt
    assert "prepare_chat_attachments" in system_prompt
    # 8 generic routing examples + 5 persona-routing examples (added with the
    # unified router in P1). Tightened ceiling to catch future prompt creep.
    assert system_prompt.count("User: ") <= 14
