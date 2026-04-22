"""Regression tests for JSON Schema safety of built function-calling tools.

GLM-5 (and other OpenAI-compatible providers with strict JSON Schema
validation) return ``400 / code 1210`` when a tool parameter declares a
non-standard type such as ``"float"`` or ``"file"``. The internal
``ParameterType`` enum uses those shorthands, so the tools-parameter
builder must translate them back to valid JSON Schema types.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
    _to_json_schema_type,
)

_JSON_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}


def test_to_json_schema_type_aliases_float_and_file() -> None:
    assert _to_json_schema_type("float") == "number"
    assert _to_json_schema_type("file") == "string"
    assert _to_json_schema_type("string") == "string"
    assert _to_json_schema_type("INTEGER") == "integer"
    assert _to_json_schema_type(None) == "string"


def _make_orchestrator_with_tools(tools: Dict[str, Dict[str, Any]]) -> FunctionCallingOrchestrator:
    registry = MagicMock()
    registry.get_tool_info.side_effect = lambda name: tools.get(name)
    registry.get_skill_info.return_value = None
    orchestrator = FunctionCallingOrchestrator.__new__(FunctionCallingOrchestrator)
    orchestrator.tool_registry = registry  # type: ignore[attr-defined]
    return orchestrator


def _collect_declared_types(tools_payload: List[Dict[str, Any]]) -> List[str]:
    types: List[str] = []
    for tool in tools_payload:
        params = tool.get("function", {}).get("parameters", {})
        for prop in params.get("properties", {}).values():
            types.append(prop.get("type"))
            if prop.get("type") == "array":
                items = prop.get("items") or {}
                if "type" in items:
                    types.append(items["type"])
    return types


def test_build_tools_parameter_emits_only_json_schema_types() -> None:
    tools_registry = {
        "ask_user_question": {
            "description": "Ask user",
            "parameters": [
                {"name": "question", "type": "string", "required": True},
                {"name": "timeout_seconds", "type": "float", "required": False},
            ],
        },
        "upload_thing": {
            "description": "Upload",
            "parameters": [
                {"name": "payload", "type": "file", "required": True},
                {"name": "tags", "type": "array", "array_item_type": "float"},
            ],
        },
    }
    orchestrator = _make_orchestrator_with_tools(tools_registry)

    payload = orchestrator._build_tools_parameter(["ask_user_question", "upload_thing"])

    declared = _collect_declared_types(payload)
    assert declared, "expected tool properties to be rendered"
    for declared_type in declared:
        assert declared_type in _JSON_SCHEMA_TYPES, (
            f"invalid JSON Schema type emitted: {declared_type!r}"
        )
    # Explicitly confirm the known-failing GLM 1210 strings are absent.
    assert "float" not in declared
    assert "file" not in declared
