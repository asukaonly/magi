"""Tests for tool feature-gating enforcement."""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from magi.tools.schema import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
    ToolSchema,
)
from magi.tools.registry import ToolRegistry


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_class,features,missing",
    [
        (UngatedTool, [], []),
        (GatedTool, [], ["beta_search"]),
        (GatedTool, ["beta_search"], []),
        (MultiGatedTool, ["beta_search"], ["experimental_api"]),
        (MultiGatedTool, ["experimental_api"], ["beta_search"]),
        (MultiGatedTool, ["beta_search", "experimental_api"], []),
    ],
)
async def test_feature_gates_prevent_body_execution_until_all_requirements_are_present(
    tool_class, features, missing
):
    registry = _build_registry(tool_class)
    name = tool_class.SCHEMA.name
    tool = registry.get_tool(name)
    body = AsyncMock(return_value=ToolResult(success=True, data="executed"))
    tool.execute = body
    context = _context(enabled_features=features)
    result = await registry.execute(name, {}, context)
    if missing:
        assert result.success is False
        assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
        assert all(flag in result.error for flag in missing)
        body.assert_not_awaited()
    else:
        assert result.success is True
        assert result.data == "executed"
        body.assert_awaited_once_with({}, context)


@pytest.mark.parametrize(
    "features,expected",
    [
        (None, {"ungated_tool", "gated_tool", "multi_gated_tool"}),
        ([], {"ungated_tool"}),
        (["beta_search"], {"ungated_tool", "gated_tool"}),
        (["beta_search", "experimental_api"], {"ungated_tool", "gated_tool", "multi_gated_tool"}),
    ],
)
def test_discovery_and_public_metadata_apply_the_same_feature_filter(features, expected):
    registry = _build_registry(UngatedTool, GatedTool, MultiGatedTool)
    assert set(registry.list_tools(enabled_features=features)) == expected
    assert {
        item["name"] for item in registry.get_all_tools_info(enabled_features=features)
    } == expected
