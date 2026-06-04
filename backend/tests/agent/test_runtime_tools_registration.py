"""Gate: the composition-root registrar puts the agent tool in the registry.

Phase 5 Task 3 relocated ``agent_tool`` out of the core-tools plugin scope into
``magi.agent.runtime_tools`` (L12) and host-registers it from the composition
root (``magi.bootstrap.runtime_tools``). These tests prove registration works
*without* a full backend startup, so a regression that silently drops the
registrar would fail here rather than in production (where it would break
sub-agent spawning).
"""

from __future__ import annotations

from magi.agent.batch.tools import (
    BATCH_TOOL_CLASSES,
    BatchCreateTool,
    BatchItemUpdateTool,
    BatchReviewTool,
)
from magi.agent.runtime_tools import AGENT_RUNTIME_TOOL_CLASSES, AgentTool
from magi.bootstrap.runtime_tools import register_runtime_tools
from magi.tools.registry import ToolRegistry


def test_registrar_registers_agent_tool_into_fresh_registry() -> None:
    """register_runtime_tools must place the `agent` tool in a fresh registry."""
    registry = ToolRegistry()

    # Pre-condition: a brand-new registry does not have the agent tool.
    assert registry.get_tool("agent") is None

    registered = register_runtime_tools(registry)

    assert "agent" in registered
    tool = registry.get_tool("agent")
    assert tool is not None
    assert isinstance(tool, AgentTool)


def test_agent_runtime_tool_classes_contains_agent_tool() -> None:
    """The runtime-tool export the registrar iterates includes AgentTool."""
    assert AgentTool in AGENT_RUNTIME_TOOL_CLASSES


def test_agent_tool_schema_name_is_agent() -> None:
    """Guard the registered name the rest of the runtime looks up."""
    assert AgentTool().get_schema().name == "agent"


def test_registrar_registers_batch_tools_into_fresh_registry() -> None:
    """Issue #11: batch tools moved out of the core-tools plugin scope into
    ``magi.agent.batch.tools`` (L12 runtime-control) and are host-registered
    from the composition root. This proves the relocation did NOT de-register
    them — the key risk of the move.
    """
    registry = ToolRegistry()

    for name in ("batch_create", "batch_item_update", "batch_review"):
        assert registry.get_tool(name) is None

    registered = register_runtime_tools(registry)

    for name, cls in (
        ("batch_create", BatchCreateTool),
        ("batch_item_update", BatchItemUpdateTool),
        ("batch_review", BatchReviewTool),
    ):
        assert name in registered
        tool = registry.get_tool(name)
        assert tool is not None
        assert isinstance(tool, cls)


def test_batch_tool_classes_export() -> None:
    """The batch runtime-tool export the registrar iterates includes all three."""
    assert BATCH_TOOL_CLASSES == (
        BatchCreateTool,
        BatchItemUpdateTool,
        BatchReviewTool,
    )
