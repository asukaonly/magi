from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
from magi.config.models import LLMScenario
from magi.tools.context_decider import ContextDecider


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
    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        return [{"name": "agent", "description": "worker launch", "type": "tool"}]

    def list_tools(self) -> List[str]:
        return ["agent"]

    def is_skill(self, name: str) -> bool:
        _ = name
        return False


class _ResearchToolRegistry:
    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        return [
            {"name": "web-search", "description": "Search the web", "type": "tool"},
            {"name": "web-fetch", "description": "Fetch web pages", "type": "tool"},
        ]

    def list_tools(self) -> List[str]:
        return ["web-search", "web-fetch"]

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

    async def _fake_chat(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok","orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'

    decider.provider_bridge.chat = _fake_chat  # type: ignore[method-assign]

    await decider.decide("hello", {"os": "Darwin"})

    assert seen["disable_thinking"] is True


@pytest.mark.asyncio
async def test_context_decider_requests_context_scenario_from_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _RecordingLLMPool(_DummyLLMAdapter())
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_pool=pool)  # type: ignore[arg-type]

    class _FakeBridge:
        async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok","orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'

    monkeypatch.setattr(decider, "provider_bridge", _FakeBridge())

    await decider.decide("hello")

    assert pool.requested
    assert all(item == LLMScenario.CONTEXT_DECIDER for item in pool.requested)


@pytest.mark.asyncio
async def test_context_decider_ignores_context_toggle_and_keeps_disable_thinking_true() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]
    seen: Dict[str, Any] = {}

    async def _fake_chat(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok","orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'

    decider.provider_bridge.chat = _fake_chat  # type: ignore[method-assign]

    await decider.decide("hello", {"disable_thinking": False, "deep_thinking": True})

    assert seen["disable_thinking"] is True


def test_context_decider_parses_decompose_orchestration_strategy() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    decision = decider._parse_response(
        '{"intent":"planning","tools":["agent"],"deep_thinking":true,"reasoning":"repo architecture","orchestration_strategy":{"mode":"decompose","planner":"task_agent","default_leaf_type":"Explore","allow_parallel":true}}'
    )

    assert decision.orchestration_strategy["mode"] == "decompose"
    assert decision.orchestration_strategy["planner"] == "task_agent"
    assert decision.orchestration_strategy["default_leaf_type"] == "Explore"
    assert decision.orchestration_strategy["allow_parallel"] is True


def test_context_decider_prompt_includes_recent_tool_error_config_path() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    prompt = decider._build_prompt(
        "要配什么key",
        [{"name": "weather", "description": "Weather tool", "type": "tool"}],
        {
            "os": "Darwin",
            "recent_tool_errors": [
                {
                    "tool_name": "weather",
                    "error_code": "PROVIDER_NOT_CONFIGURED",
                    "error_message": "Missing API key",
                    "config_path": "tool.weather.providers.qweather.api_key",
                    "next_action": "configure_qweather_api_key",
                }
            ],
        },
    )

    assert "config_path=tool.weather.providers.qweather.api_key" in prompt
    assert "next_action=configure_qweather_api_key" in prompt


def test_context_decider_rule_fallback_routes_complex_news_to_generic_decompose() -> None:
    decider = ContextDecider(tool_registry=_ResearchToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    decision = decider._rule_based_fallback("搜一下最近7天杭州有什么重要的新闻，给我来10条并附上链接")

    assert decision.intent == "planning"
    assert decision.tools == ["web-search"]
    assert decision.deep_thinking is True
    assert decision.orchestration_strategy["mode"] == "decompose"
    assert decision.orchestration_strategy["default_leaf_type"] == "general-purpose"
    assert decision.orchestration_strategy["allow_parallel"] is True


@pytest.mark.asyncio
async def test_context_decider_overrides_llm_direct_news_with_research_guardrail() -> None:
    decider = ContextDecider(tool_registry=_ResearchToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    async def _fake_chat(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return (
            '{"intent":"realtime_query","tools":["web-search"],"deep_thinking":false,'
            '"reasoning":"simple search","orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
        )

    decider.provider_bridge.chat = _fake_chat  # type: ignore[method-assign]

    decision = await decider.decide("搜一下最近7天杭州有什么重要的新闻，给我来10条并附上链接", {"os": "Darwin"})

    assert decision.intent == "planning"
    assert decision.deep_thinking is True
    assert decision.orchestration_strategy["mode"] == "decompose"
    assert decision.orchestration_strategy["default_leaf_type"] == "general-purpose"
