"""Tests for tool feature-gating enforcement."""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from magi.tools.schema import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from magi.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _BaseTool:
    """Minimal tool stub compatible with ToolRegistry."""

    SCHEMA: ToolSchema

    def get_schema(self) -> ToolSchema:
        return self.SCHEMA

    def get_info(self) -> Dict[str, Any]:
        schema = self.get_schema()
        return {
            "name": schema.name,
            "description": schema.description,
            "category": schema.category,
            "dangerous": schema.dangerous,
            "feature_flags": schema.feature_flags,
            "parameters": [],
            "type": "tool",
        }

    async def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, str]:
        return True, ""

    async def execute(self, params: Dict[str, Any], context: Any) -> ToolResult:
        return ToolResult(success=True, data="ok")

    async def after_execution(self, result: ToolResult, context: Any) -> ToolResult:
        return result


class UngatedTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="ungated_tool",
        description="A tool with no feature flags",
        category="test",
    )


class GatedTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="gated_tool",
        description="A tool requiring beta_search feature",
        category="test",
        feature_flags=["beta_search"],
    )


class MultiGatedTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="multi_gated_tool",
        description="A tool requiring multiple flags",
        category="test",
        feature_flags=["beta_search", "experimental_api"],
    )


def _build_registry(*tool_classes) -> ToolRegistry:
    registry = ToolRegistry()
    for cls in tool_classes:
        registry.register(cls)
    return registry


def _context(*, enabled_features: list[str] | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="test-agent",
        enabled_features=enabled_features or [],
    )


# ---------------------------------------------------------------------------
# Schema field tests
# ---------------------------------------------------------------------------


def test_tool_schema_feature_flags_default_empty():
    schema = ToolSchema(name="x", description="x", category="x")
    assert schema.feature_flags == []


def test_tool_schema_feature_flags_set():
    schema = ToolSchema(name="x", description="x", category="x", feature_flags=["a", "b"])
    assert schema.feature_flags == ["a", "b"]


def test_context_enabled_features_default_empty():
    ctx = ToolExecutionContext(agent_id="a")
    assert ctx.enabled_features == []


def test_context_enabled_features_set():
    ctx = ToolExecutionContext(agent_id="a", enabled_features=["beta_search"])
    assert ctx.enabled_features == ["beta_search"]


# ---------------------------------------------------------------------------
# Execution gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ungated_tool_executes_without_features():
    registry = _build_registry(UngatedTool)
    result = await registry.execute("ungated_tool", {}, _context())
    assert result.success is True


@pytest.mark.asyncio
async def test_gated_tool_blocked_without_feature():
    registry = _build_registry(GatedTool)
    result = await registry.execute("gated_tool", {}, _context())
    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    assert "beta_search" in result.error


@pytest.mark.asyncio
async def test_gated_tool_allowed_with_feature():
    registry = _build_registry(GatedTool)
    result = await registry.execute(
        "gated_tool", {}, _context(enabled_features=["beta_search"])
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_multi_gated_tool_blocked_with_partial_features():
    registry = _build_registry(MultiGatedTool)
    result = await registry.execute(
        "multi_gated_tool", {}, _context(enabled_features=["beta_search"])
    )
    assert result.success is False
    assert "experimental_api" in result.error


@pytest.mark.asyncio
async def test_multi_gated_tool_allowed_with_all_features():
    registry = _build_registry(MultiGatedTool)
    result = await registry.execute(
        "multi_gated_tool",
        {},
        _context(enabled_features=["beta_search", "experimental_api"]),
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# Discovery filtering
# ---------------------------------------------------------------------------


def test_list_tools_no_filter():
    registry = _build_registry(UngatedTool, GatedTool)
    tools = registry.list_tools()
    assert set(tools) == {"ungated_tool", "gated_tool"}


def test_list_tools_with_enabled_features_filters_gated():
    registry = _build_registry(UngatedTool, GatedTool)
    tools = registry.list_tools(enabled_features=[])
    assert tools == ["ungated_tool"]


def test_list_tools_with_matching_features_includes_gated():
    registry = _build_registry(UngatedTool, GatedTool)
    tools = registry.list_tools(enabled_features=["beta_search"])
    assert set(tools) == {"ungated_tool", "gated_tool"}


def test_get_all_tools_info_no_filter():
    registry = _build_registry(UngatedTool, GatedTool)
    infos = registry.get_all_tools_info()
    names = {i["name"] for i in infos}
    assert names == {"ungated_tool", "gated_tool"}


def test_get_all_tools_info_with_empty_features():
    registry = _build_registry(UngatedTool, GatedTool)
    infos = registry.get_all_tools_info(enabled_features=[])
    names = {i["name"] for i in infos}
    assert names == {"ungated_tool"}


def test_get_all_tools_info_with_matching_features():
    registry = _build_registry(UngatedTool, GatedTool)
    infos = registry.get_all_tools_info(enabled_features=["beta_search"])
    names = {i["name"] for i in infos}
    assert names == {"ungated_tool", "gated_tool"}


# ---------------------------------------------------------------------------
# _tool_passes_feature_gate helper
# ---------------------------------------------------------------------------


def test_passes_gate_no_flags():
    registry = _build_registry(UngatedTool)
    assert registry._tool_passes_feature_gate("ungated_tool", set()) is True


def test_passes_gate_flags_satisfied():
    registry = _build_registry(GatedTool)
    assert registry._tool_passes_feature_gate("gated_tool", {"beta_search"}) is True


def test_passes_gate_flags_not_satisfied():
    registry = _build_registry(GatedTool)
    assert registry._tool_passes_feature_gate("gated_tool", set()) is False


def test_passes_gate_unknown_tool():
    registry = _build_registry()
    assert registry._tool_passes_feature_gate("nonexistent", set()) is True
