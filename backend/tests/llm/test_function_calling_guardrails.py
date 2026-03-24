"""
Tests for explore-worker guardrails in function-calling execution.
"""
from __future__ import annotations

import os
import getpass
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.agent.execution.function_calling import FunctionCallingOrchestrator
from magi.config.models import LLMScenario
from magi.llm.base import LLMAdapter
from magi.skills.schema import SkillResult


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


class _RecordingLLMPool:
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter
        self.requested: list[LLMScenario] = []

    def get(self, scenario: LLMScenario) -> LLMAdapter:
        self.requested.append(scenario)
        return self._adapter


def _executor() -> FunctionCallingOrchestrator:
    return FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_DummyToolRegistry(),  # type: ignore[arg-type]
    )


class _RecordingSkillRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(
        self,
        skill_name: str,
        arguments: Optional[list[str]] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> SkillResult:
        self.calls.append(
            {
                "skill_name": skill_name,
                "arguments": list(arguments or []),
                "context": dict(context or {}),
            }
        )
        return SkillResult(success=True, content="ok", metadata={})


async def test_function_calling_orchestrator_uses_core_scenario_from_pool() -> None:
    pool = _RecordingLLMPool(_DummyLLMAdapter())
    executor = FunctionCallingOrchestrator(
        llm_pool=pool,
        tool_registry=_DummyToolRegistry(),  # type: ignore[arg-type]
    )

    result = await executor._call_llm_without_tools(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result["content"] == ""
    assert pool.requested == [LLMScenario.CORE]


def test_explore_guardrail_rewrites_broad_glob_to_safe_scan() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_explore",
        tool_name="glob",
        arguments={"pattern": "*", "path": "~/code/magi"},
    )

    assert error is None
    assert guarded_args["pattern"] == "*"
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200
    assert "node_modules" in guarded_args["exclude"]


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


def test_explore_guardrail_rewrites_recursive_wildcard_glob() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_explore",
        tool_name="glob",
        arguments={"pattern": "**/*", "recursive": True},
    )

    assert error is None
    assert guarded_args["pattern"] == "*"
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200


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


def test_plan_guardrail_rewrites_root_recursive_glob_to_bounded_scan() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_plan",
        tool_name="glob",
        arguments={"pattern": "**/*", "path": "/tmp/repo", "recursive": True, "max_results": 5000},
        execution_workspace="/tmp/repo",
    )

    assert error is None
    assert guarded_args["pattern"] == "*"
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 120
    assert "node_modules" in guarded_args["exclude"]


def test_plan_guardrail_blocks_root_wide_grep_in_workspace() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_worker_explore_guardrails(
        intent="worker_plan",
        tool_name="grep",
        arguments={"pattern": "TODO", "glob": "**/*", "path": "~/repo"},
        execution_workspace=os.path.expanduser("~/repo"),
    )

    assert guarded_args == {}
    assert error == (
        "Plan worker guardrail: root-wide grep is blocked. "
        "Use a scoped glob like frontend/**/*.ts or backend/**/*.py."
    )


def test_workspace_root_path_uses_managed_workspace_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from magi.agent.execution import function_calling as function_calling_module

    fallback_cwd = tmp_path / "cwd"
    managed_workspace = tmp_path / "managed-chat-workspace"
    fallback_cwd.mkdir()
    managed_workspace.mkdir()

    monkeypatch.chdir(fallback_cwd)
    monkeypatch.setattr(
        function_calling_module,
        "get_default_chat_workspace_path",
        lambda: str(managed_workspace),
        raising=False,
    )

    executor = _executor()

    assert executor._is_workspace_root_path(str(managed_workspace), None) is True
    assert executor._is_workspace_root_path(str(fallback_cwd), None) is False


@pytest.mark.asyncio
async def test_execute_skill_passes_execution_workspace_to_skill_runner(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_runner = _RecordingSkillRunner()
    executor = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_DummyToolRegistry(),  # type: ignore[arg-type]
        skill_runner=skill_runner,
    )

    result = await executor._execute_skill(
        skill_name="demo",
        arguments={"path": "src"},
        user_id="user-1",
        execution_workspace=str(workspace),
    )

    assert result.success is True
    assert len(skill_runner.calls) == 1
    recorded_call = skill_runner.calls[0]
    assert recorded_call["skill_name"] == "demo"
    assert recorded_call["arguments"] == ["src"]
    assert recorded_call["context"]["user_id"] == "user-1"
    assert recorded_call["context"]["session_id"] == "session_user-1"
    assert recorded_call["context"]["workspace"] == str(workspace.resolve())
    assert recorded_call["context"]["env_vars"] == {
        "user": getpass.getuser(),
        "HOME": os.path.expanduser("~"),
        "PWD": str(workspace.resolve()),
    }
