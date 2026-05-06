"""Tests for the Coding subagent type."""
from __future__ import annotations

import pytest

# Import order matters: agent_tool transitively imports workers; importing
# AgentTool first lets the workers module finish initializing.
from magi.tools.builtin.agent_tool import AgentTool
from magi.agent.workers import WorkerAgentManager


class _FakeRegistry:
    """Mirrors the fake registry pattern in tests/tools/test_agent_tool.py."""

    def __init__(self, tools: list[str]) -> None:
        self._tools = list(tools)

    def list_tools(self) -> list[str]:
        return list(self._tools)


_CODING_REGISTRY_TOOLS = [
    "file_read", "file_edit", "file_write", "file_rollback", "file_diff",
    "verify", "glob", "grep", "file_list", "file_info", "bash", "todo_write",
    "agent", "memory_query", "web_search", "web_fetch",  # not in whitelist
]


def _coding_manager() -> WorkerAgentManager:
    mgr = WorkerAgentManager()
    mgr._tool_registry = _FakeRegistry(_CODING_REGISTRY_TOOLS)  # type: ignore[assignment]
    return mgr


def test_worker_manager_exposes_coding_type() -> None:
    assert WorkerAgentManager.TYPE_CODING == "Coding"


@pytest.mark.parametrize("alias", ["coding", "Coding", "code"])
def test_worker_manager_alias_normalizes_to_coding(alias: str) -> None:
    mgr = WorkerAgentManager()
    assert mgr._normalize_subagent_type(alias) == WorkerAgentManager.TYPE_CODING


def test_agent_tool_advertises_coding_in_enum() -> None:
    tool = AgentTool()
    subagent_param = next(p for p in tool.schema.parameters if p.name == "subagent_type")
    assert "Coding" in (subagent_param.enum or [])
    assert "coding" in (subagent_param.enum or [])


def test_agent_tool_constants_match_manager() -> None:
    tool = AgentTool()
    assert tool.TYPE_CODING == WorkerAgentManager.TYPE_CODING
    assert tool._WORKER_TYPE_MAP["coding"] == tool.TYPE_CODING
    assert tool._WORKER_TYPE_MAP["code"] == tool.TYPE_CODING


def test_coding_tool_whitelist_filters_against_registry() -> None:
    mgr = _coding_manager()
    tools = mgr._resolve_tools_for_type(WorkerAgentManager.TYPE_CODING)
    expected_present = {"file_read", "file_edit", "file_write", "file_rollback",
                        "file_diff", "verify", "glob", "grep", "bash"}
    assert expected_present.issubset(set(tools)), (
        f"Coding whitelist missing: {expected_present - set(tools)}"
    )
    excluded = {"agent", "memory_query", "web_search", "web_fetch"}
    assert excluded.isdisjoint(set(tools)), (
        f"Coding whitelist must not include {excluded & set(tools)}"
    )
