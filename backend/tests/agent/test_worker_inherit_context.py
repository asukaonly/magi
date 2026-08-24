"""Tests for worker inherit_context feature."""
from __future__ import annotations

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
)


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
            arguments={"preset": "read_only", "inherit_context": False},
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
            arguments={"preset": "read_only", "inherit_context": True},
        )
        assert "parent_context_summary" in result
        assert "auth module" in result["parent_context_summary"]
        # inherit_context should be popped from normalized args
        assert "inherit_context" not in result

    def test_inherit_context_missing_defaults_to_false(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = [{"role": "user", "content": "hi"}]
        result = orch._normalize_agent_launch_arguments(
            arguments={"preset": "read_only"},
        )
        assert "parent_context_summary" not in result

    def test_inherit_context_true_but_empty_messages(self) -> None:
        orch = self._make_orchestrator()
        orch._current_messages = []
        result = orch._normalize_agent_launch_arguments(
            arguments={"preset": "read_only", "inherit_context": True},
        )
        # Empty messages → no summary injected
        assert "parent_context_summary" not in result


# ---------------------------------------------------------------------------
# WorkerAgentManager: parent_context_summary → system prompt
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_publish(run_state, event_type, internal_payload, public_payload=None):
    pass
