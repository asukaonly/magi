"""Tests for worker inherit_context feature."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from magi.agent.execution.function_calling import (
    ExecutionOutcome,
    FunctionCallingOrchestrator,
)
from magi.tools.schema import ToolExecutionContext


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLLMAdapter:
    model_name = "fake-model"
    provider_name = "fake-provider"


class _FakeToolRegistry:
    def list_tools(self):
        return ["glob", "grep", "file_read", "bash", "agent"]

    def is_skill(self, _name: str) -> bool:
        return False

    def get_tool_info(self, _name: str):
        return None


# ---------------------------------------------------------------------------
# _build_parent_context_summary
# ---------------------------------------------------------------------------


class TestBuildParentContextSummary:
    def _make_orchestrator(self) -> FunctionCallingOrchestrator:
        return FunctionCallingOrchestrator(
            llm_adapter=_FakeLLMAdapter(),
            tool_registry=_FakeToolRegistry(),
        )

    def test_empty_messages(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = []
        assert orch._build_parent_context_summary() == ""

    def test_basic_messages(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = [
            {"role": "user", "content": "hello world"},
            {"role": "assistant", "content": "hi there"},
        ]
        summary = orch._build_parent_context_summary()
        assert "hello world" in summary
        assert "hi there" in summary

    def test_truncates_long_context(self) -> None:
        orch = self._make_orchestrator()
        # Build messages that exceed _PARENT_CONTEXT_MAX_CHARS
        orch._current_messages = [
            {"role": "user", "content": "x" * 2000}
            for _ in range(20)
        ]
        summary = orch._build_parent_context_summary()
        assert len(summary) <= orch._PARENT_CONTEXT_MAX_CHARS

    def test_respects_max_messages(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = [
            {"role": "user", "content": f"message {i}"}
            for i in range(40)
        ]
        summary = orch._build_parent_context_summary()
        # Should contain recent messages, not the earliest ones
        assert "message 39" in summary
        # First messages should be omitted (we only keep last 20)
        assert "message 0" not in summary


# ---------------------------------------------------------------------------
# _normalize_agent_launch_arguments
# ---------------------------------------------------------------------------


class TestNormalizeAgentLaunchArguments:
    def _make_orchestrator(self) -> FunctionCallingOrchestrator:
        return FunctionCallingOrchestrator(
            llm_adapter=_FakeLLMAdapter(),
            tool_registry=_FakeToolRegistry(),
        )

    def test_inherit_context_false_no_summary(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = [
            {"role": "user", "content": "some context"},
            {"role": "assistant", "content": "got it"},
        ]
        result = orch._normalize_agent_launch_arguments(
            arguments={"subagent_type": "Explore", "inherit_context": False},
            orchestration_strategy=None,
        )
        assert "parent_context_summary" not in result
        assert "inherit_context" not in result

    def test_inherit_context_true_produces_summary(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = [
            {"role": "user", "content": "find the auth module"},
            {"role": "assistant", "content": "I found it in src/auth/"},
        ]
        result = orch._normalize_agent_launch_arguments(
            arguments={"subagent_type": "Explore", "inherit_context": True},
            orchestration_strategy=None,
        )
        assert "parent_context_summary" in result
        assert "auth module" in result["parent_context_summary"]
        # inherit_context should be popped from normalized args
        assert "inherit_context" not in result

    def test_inherit_context_missing_defaults_to_false(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = [{"role": "user", "content": "hi"}]
        result = orch._normalize_agent_launch_arguments(
            arguments={"subagent_type": "Explore"},
            orchestration_strategy=None,
        )
        assert "parent_context_summary" not in result

    def test_inherit_context_true_but_empty_messages(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = []
        result = orch._normalize_agent_launch_arguments(
            arguments={"subagent_type": "Explore", "inherit_context": True},
            orchestration_strategy=None,
        )
        # Empty messages → no summary injected
        assert "parent_context_summary" not in result


# ---------------------------------------------------------------------------
# WorkerAgentManager: parent_context_summary → system prompt
# ---------------------------------------------------------------------------


class TestWorkerContextInjection:
    @pytest.mark.asyncio
    async def test_parent_context_injected_into_system_prompt(self, monkeypatch) -> None:
        from magi.agent.workers import worker_manager as wm_mod
        from magi.agent.workers.worker_manager import WorkerAgentManager

        captured_prompts: list[str] = []

        class _CapturingOrchestrator:
            def __init__(self, **kwargs):
                pass

            async def execute_with_tools(self, *, system_prompt, **kwargs):
                captured_prompts.append(system_prompt)
                return ExecutionOutcome(
                    status="completed",
                    content=(
                        '{"result_status":"success","summary":"done",'
                        '"findings":[{"title":"f","detail":"d","path":"/x","why_it_matters":"y"}],'
                        '"evidence":[{"path":"/x","detail":"d"}],'
                        '"gaps":[],"next_steps":[],"failure_reason":null}'
                    ),
                    iterations=1,
                )

        monkeypatch.setattr(wm_mod, "FunctionCallingOrchestrator", _CapturingOrchestrator)

        mgr = WorkerAgentManager()
        mgr.configure(
            llm_adapter=_FakeLLMAdapter(),
            tool_registry_instance=_FakeToolRegistry(),
        )
        monkeypatch.setattr(mgr, "_publish_worker_fact", _noop_publish)

        result = await mgr.execute(
            parameters={
                "action": "launch",
                "subagent_type": "Explore",
                "description": "test inherited",
                "prompt": "do something",
                "run_in_background": False,
                "parent_context_summary": "user asked about auth module in src/auth/",
            },
            context=ToolExecutionContext(
                agent_id="chat:test",
                workspace="/tmp",
                env_vars={"user_id": "u1", "session_id": "s1"},
            ),
        )

        assert result.success
        assert len(captured_prompts) == 1
        assert "PARENT CONVERSATION CONTEXT" in captured_prompts[0]
        assert "auth module" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_no_context_when_summary_empty(self, monkeypatch) -> None:
        from magi.agent.workers import worker_manager as wm_mod
        from magi.agent.workers.worker_manager import WorkerAgentManager

        captured_prompts: list[str] = []

        class _CapturingOrchestrator:
            def __init__(self, **kwargs):
                pass

            async def execute_with_tools(self, *, system_prompt, **kwargs):
                captured_prompts.append(system_prompt)
                return ExecutionOutcome(
                    status="completed",
                    content=(
                        '{"result_status":"success","summary":"done",'
                        '"findings":[{"title":"f","detail":"d","path":"/x","why_it_matters":"y"}],'
                        '"evidence":[{"path":"/x","detail":"d"}],'
                        '"gaps":[],"next_steps":[],"failure_reason":null}'
                    ),
                    iterations=1,
                )

        monkeypatch.setattr(wm_mod, "FunctionCallingOrchestrator", _CapturingOrchestrator)

        mgr = WorkerAgentManager()
        mgr.configure(
            llm_adapter=_FakeLLMAdapter(),
            tool_registry_instance=_FakeToolRegistry(),
        )
        monkeypatch.setattr(mgr, "_publish_worker_fact", _noop_publish)

        result = await mgr.execute(
            parameters={
                "action": "launch",
                "subagent_type": "Explore",
                "description": "test no context",
                "prompt": "do something",
                "run_in_background": False,
            },
            context=ToolExecutionContext(
                agent_id="chat:test",
                workspace="/tmp",
                env_vars={"user_id": "u1", "session_id": "s1"},
            ),
        )

        assert result.success
        assert len(captured_prompts) == 1
        assert "PARENT CONVERSATION CONTEXT" not in captured_prompts[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_publish(run_state, event_type, internal_payload, public_payload=None):
    pass
