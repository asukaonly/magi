"""Tests for unified parent and child run guardrails."""
from __future__ import annotations

import os
import getpass
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall
from magi.llm.base import LLMAdapter
from magi.llm.model_context import ModelContextProfile, ResolvedModel
from magi.skills.schema import SkillResult
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


class _DummyToolRegistry:
    def is_skill(self, name: str) -> bool:
        _ = name
        return False

    def get_tool_info(self, _name: str) -> dict[str, Any]:
        return {"dangerous": False}

    async def execute(self, tool_name: str, arguments: dict[str, Any], _context) -> ToolResult:
        return ToolResult(success=True, data={"tool_name": tool_name, "arguments": arguments})


class _RecordingLLMPool:
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter
        self.requested = 0

    def resolve(self) -> ResolvedModel:
        self.requested += 1
        return ResolvedModel(
            adapter=self._adapter,
            context=ModelContextProfile(
                provider_id="openai",
                model_id="dummy-model",
                context_window=200_000,
                max_output_tokens=8_000,
            ),
        )


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


async def test_function_calling_orchestrator_uses_injected_active_model() -> None:
    pool = _RecordingLLMPool(_DummyLLMAdapter())
    executor = FunctionCallingOrchestrator(
        active_model_provider=pool.resolve,
        tool_registry=_DummyToolRegistry(),  # type: ignore[arg-type]
    )

    result = await executor._call_llm_without_tools(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result["content"] == ""
    assert pool.requested == 1
    assert executor._context_compactor.effective_window == 200_000


def test_child_guardrail_rewrites_broad_glob_to_safe_scan() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="child_read_only",
        tool_name="glob",
        arguments={"pattern": "*", "path": "~/code/magi"},
    )

    assert error is None
    assert guarded_args["pattern"] == "*"
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200
    assert "node_modules" in guarded_args["exclude"]


def test_child_guardrail_injects_safe_defaults_for_glob() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="child_read_only",
        tool_name="glob",
        arguments={"pattern": "frontend/*.tsx"},
    )

    assert error is None
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200
    assert "node_modules" in guarded_args["exclude"]


def test_child_guardrail_rewrites_recursive_wildcard_glob() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="child_read_only",
        tool_name="glob",
        arguments={"pattern": "**/*", "recursive": True},
    )

    assert error is None
    assert guarded_args["pattern"] == "*"
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200


def test_child_guardrail_clamps_max_results_for_grep() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="child_read_only",
        tool_name="grep",
        arguments={"pattern": "TODO", "glob": "backend/**/*.py", "max_results": 5000},
    )

    assert error is None
    assert guarded_args["max_results"] == 200
    assert guarded_args["recursive"] is True
    assert "dist" in guarded_args["exclude"]


def test_workspace_write_child_guardrail_rewrites_root_recursive_glob() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="child_workspace_write",
        tool_name="glob",
        arguments={"pattern": "**/*", "path": "/tmp/repo", "recursive": True, "max_results": 5000},
        execution_workspace="/tmp/repo",
    )

    assert error is None
    assert guarded_args["pattern"] == "*"
    assert guarded_args["recursive"] is False
    assert guarded_args["max_results"] == 200
    assert "node_modules" in guarded_args["exclude"]


def test_workspace_write_child_guardrail_blocks_root_wide_grep() -> None:
    executor = _executor()
    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="child_workspace_write",
        tool_name="grep",
        arguments={"pattern": "TODO", "glob": "**/*", "path": "~/repo"},
        execution_workspace=os.path.expanduser("~/repo"),
    )

    assert guarded_args == {}
    assert error == (
        "Workspace Write child guardrail: root-wide grep is blocked. "
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


def test_chat_guardrail_blocks_scan_outside_active_workspace(tmp_path) -> None:
    executor = _executor()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="chat",
        tool_name="glob",
        arguments={"pattern": "**/*.py", "path": str(outside)},
        execution_workspace=str(workspace),
    )

    assert guarded_args == {}
    assert error == (
        "File scan guardrail: glob and grep must stay within the active workspace. "
        f"Requested path resolves to {outside.resolve()} while workspace is {workspace.resolve()}. "
        "If the user explicitly asked to scan an external path, retry with "
        "outside_workspace_allowed=true; otherwise ask the user for an explicit "
        "path or use web-search first."
    )


def test_chat_guardrail_allows_scan_within_active_workspace(tmp_path) -> None:
    executor = _executor()
    workspace = tmp_path / "workspace"
    nested = workspace / "backend"
    nested.mkdir(parents=True)

    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="chat",
        tool_name="grep",
        arguments={"pattern": "todo", "path": str(nested), "glob": "*.py"},
        execution_workspace=str(workspace),
    )

    assert error is None
    assert guarded_args == {
        "pattern": "todo",
        "path": str(nested),
        "glob": "*.py",
    }


def test_chat_guardrail_outside_workspace_allowed_flag_unblocks_and_strips(tmp_path) -> None:
    executor = _executor()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    guarded_args, error = executor._apply_execution_guardrails(
        execution_preset="chat",
        tool_name="glob",
        arguments={
            "pattern": "**/*.py",
            "path": str(outside),
            "outside_workspace_allowed": True,
        },
        execution_workspace=str(workspace),
    )

    assert error is None
    # Hint must be consumed by the guardrail and not forwarded to the tool.
    assert "outside_workspace_allowed" not in guarded_args
    assert guarded_args["path"] == str(outside)


@pytest.mark.asyncio
async def test_execute_tool_call_marks_ambiguous_scope_for_workspace_escape(tmp_path) -> None:
    executor = _executor()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    result = await executor._execute_tool_call(
        tool_call=ToolCall(id="call-1", name="glob", arguments={"pattern": "**/*.json", "path": str(outside)}),
        user_message="帮我看看 AnotherProject 是怎么做的",
        user_id="u",
        session_id="s",
        turn_id="t",
        execution_preset="chat",
        execution_agent_id="a",
        execution_workspace=str(workspace),
    )

    assert result.success is False
    assert result.error_code == "AMBIGUOUS_SCOPE"


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
