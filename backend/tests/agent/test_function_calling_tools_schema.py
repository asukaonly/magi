"""Regression tests for JSON Schema safety of built function-calling tools.

GLM-5 (and other OpenAI-compatible providers with strict JSON Schema
validation) return ``400 / code 1210`` when a tool parameter declares a
non-standard type such as ``"float"`` or ``"file"``. The internal
``ParameterType`` enum uses those shorthands, so the tools-parameter
builder must translate them back to valid JSON Schema types.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from unittest.mock import MagicMock

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
)


def _make_orchestrator_with_tools(tools: Dict[str, Dict[str, Any]]) -> FunctionCallingOrchestrator:
    registry = MagicMock()
    registry.get_tool_info.side_effect = lambda name: tools.get(name)
    registry.get_skill_info.return_value = None
    registry.is_skill.return_value = False
    orchestrator = FunctionCallingOrchestrator.__new__(FunctionCallingOrchestrator)
    orchestrator.tool_registry = registry  # type: ignore[attr-defined]
    return orchestrator


def test_tool_schema_maps_each_parameter_and_array_item_type_exactly():
    parameters = [
        {"name": "question", "type": "string", "required": True, "description": "Question"},
        {"name": "timeout", "type": "float"},
        {"name": "payload", "type": "file", "required": True},
        {"name": "retries", "type": "INTEGER"},
        {"name": "unspecified", "type": None},
        {"name": "scores", "type": "array", "array_item_type": "float"},
        {"name": "tags", "type": "array"},
    ]
    orchestrator = _make_orchestrator_with_tools(
        {"inspect": {"description": "Inspect", "parameters": parameters}}
    )
    assert orchestrator._build_tools_parameter(["inspect"]) == [
        {
            "type": "function",
            "function": {
                "name": "inspect",
                "description": "Inspect",
                "parameters": {
                    "type": "object",
                    "required": ["question", "payload"],
                    "properties": {
                        "question": {"type": "string", "description": "Question"},
                        "timeout": {"type": "number"},
                        "payload": {"type": "string"},
                        "retries": {"type": "integer"},
                        "unspecified": {"type": "string"},
                        "scores": {"type": "array", "items": {"type": "number"}},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        }
    ]


@pytest.mark.parametrize("tool_name", ["glob", "bash"])
@pytest.mark.parametrize("include_metadata", [False, True])
def test_provider_description_includes_supplied_guidance_for_any_tool(tool_name, include_metadata):
    metadata = {
        "tool_hint": "Choose narrow targets.",
        "task_intents": ["inspect_runtime", "debug"],
        "domains": ["codebase"],
        "operations": ["probe"],
        "query_shapes": ["path_or_command"],
        "followed_by": ["file_read"],
        "avoid_task_intents": ["research_external"],
    }
    tool_info = {"description": "Base description", "parameters": []}
    if include_metadata:
        tool_info["metadata"] = metadata
    orchestrator = _make_orchestrator_with_tools({tool_name: tool_info})
    payload = orchestrator._build_tools_parameter([tool_name])
    assert len(payload) == 1
    assert payload[0]["function"]["name"] == tool_name
    description = payload[0]["function"]["description"]
    if include_metadata:
        assert description.startswith("Base description")
        for value in metadata.values():
            for text in ([value] if isinstance(value, str) else value):
                assert text in description
    else:
        assert description == "Base description"
