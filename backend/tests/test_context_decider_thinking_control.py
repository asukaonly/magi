from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.llm.base import LLMAdapter
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


@pytest.mark.asyncio
async def test_context_decider_always_disables_thinking() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]
    seen: Dict[str, Any] = {}

    async def _fake_chat(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok","worker_strategy":{"preferred_subagent_type":"general-purpose","execution_mode":"single","enforce_subagent_type":false}}'

    decider.provider_bridge.chat = _fake_chat  # type: ignore[method-assign]

    await decider.decide("hello", {"os": "Darwin"})

    assert seen["disable_thinking"] is True


@pytest.mark.asyncio
async def test_context_decider_ignores_context_toggle_and_keeps_disable_thinking_true() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]
    seen: Dict[str, Any] = {}

    async def _fake_chat(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"ok","worker_strategy":{"preferred_subagent_type":"general-purpose","execution_mode":"single","enforce_subagent_type":false}}'

    decider.provider_bridge.chat = _fake_chat  # type: ignore[method-assign]

    await decider.decide("hello", {"disable_thinking": False, "deep_thinking": True})

    assert seen["disable_thinking"] is True


def test_context_decider_parses_plan_worker_strategy() -> None:
    decider = ContextDecider(tool_registry=_DummyToolRegistry(), llm_adapter=_DummyLLMAdapter())  # type: ignore[arg-type]

    decision = decider._parse_response(
        '{"intent":"planning","tools":["agent"],"deep_thinking":true,"reasoning":"repo architecture","worker_strategy":{"preferred_subagent_type":"Plan","execution_mode":"plan_and_decompose","enforce_subagent_type":true}}'
    )

    assert decision.worker_strategy["preferred_subagent_type"] == "Plan"
    assert decision.worker_strategy["execution_mode"] == "plan_and_decompose"
    assert decision.worker_strategy["enforce_subagent_type"] is True
