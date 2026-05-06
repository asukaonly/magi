"""Tests for the Coding subagent type."""
from __future__ import annotations

import pytest

# Import order matters: agent_tool transitively imports workers; importing
# AgentTool first lets the workers module finish initializing.
from magi.tools.builtin.agent_tool import AgentTool
from magi.agent.workers import WorkerAgentManager


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
