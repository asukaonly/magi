"""
Tests for explore-worker guardrails in function-calling execution.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from magi.llm.base import LLMAdapter
from magi.tools.function_calling import FunctionCallingExecutor


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
    def is_skill(self, name: str) -> bool:
        _ = name
        return False


def _executor() -> FunctionCallingExecutor:
    return FunctionCallingExecutor(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_DummyToolRegistry(),  # type: ignore[arg-type]
    )


def test_explore_guardrail_blocks_root_wide_glob() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_explore",
        tool_name="glob",
        arguments={"pattern": "*", "path": "~/code/magi"},
    )

    assert guarded_args == {}
    assert error is not None
    assert "broad glob patterns are blocked" in error


def test_explore_guardrail_injects_safe_defaults_for_glob() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_explore",
        tool_name="glob",
        arguments={"pattern": "frontend/*.tsx"},
    )

    assert error is None
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200
    assert "node_modules" in guarded_args["exclude"]


def test_explore_guardrail_clamps_max_results_for_grep() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_explore",
        tool_name="grep",
        arguments={"pattern": "TODO", "glob": "backend/**/*.py", "max_results": 5000},
    )

    assert error is None
    assert guarded_args["max_results"] == 200
    assert guarded_args["recursive"] is True
    assert "dist" in guarded_args["exclude"]
