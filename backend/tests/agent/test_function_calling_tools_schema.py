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
)
from magi.agent.execution.function_calling.tools import to_json_schema_type

_JSON_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}


def test_to_json_schema_type_aliases_float_and_file() -> None:
    assert to_json_schema_type("float") == "number"
    assert to_json_schema_type("file") == "string"
    assert to_json_schema_type("string") == "string"
    assert to_json_schema_type("INTEGER") == "integer"
    assert to_json_schema_type(None) == "string"


def _make_orchestrator_with_tools(tools: Dict[str, Dict[str, Any]]) -> FunctionCallingOrchestrator:
    registry = MagicMock()
    registry.get_tool_info.side_effect = lambda name: tools.get(name)
    registry.get_skill_info.return_value = None
    registry.is_skill.return_value = False
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


def test_build_tools_parameter_appends_tool_guidance_from_metadata() -> None:
    tools_registry = {
        "glob": {
            "description": "Find files matching shell-style patterns.",
            "metadata": {
                "tool_hint": "Use first to locate candidate files from module clues.",
                "task_intents": ["explore_codebase", "trace_implementation"],
                "domains": ["codebase"],
                "operations": ["discover"],
                "query_shapes": ["path_or_module"],
                "followed_by": ["grep", "file_read"],
                "avoid_task_intents": ["research_external"],
            },
            "parameters": [
                {"name": "pattern", "type": "string", "required": True},
            ],
        }
    }
    orchestrator = _make_orchestrator_with_tools(tools_registry)

    payload = orchestrator._build_tools_parameter(["glob"])
    description = payload[0]["function"]["description"]

    assert "Tool guidance:" in description
    assert "Best for tasks: explore_codebase, trace_implementation." in description
    assert "Domain: codebase." in description
    assert "Typical operations: discover." in description
    assert "Usually followed by: grep, file_read." in description


def test_build_tools_parameter_renders_non_search_tool_guidance_from_metadata() -> None:
    tools_registry = {
        "bash": {
            "description": "Execute Bash/Shell commands.",
            "metadata": {
                "tool_hint": "Use for narrow executable checks once the target is known.",
                "task_intents": ["debug_runtime", "inspect_runtime_state"],
                "domains": ["runtime", "system"],
                "operations": ["probe", "inspect"],
                "query_shapes": ["shell_command", "one_off_check"],
                "avoid_task_intents": ["explore_codebase", "research_external"],
            },
            "parameters": [
                {"name": "command", "type": "string", "required": True},
            ],
        }
    }
    orchestrator = _make_orchestrator_with_tools(tools_registry)

    payload = orchestrator._build_tools_parameter(["bash"])
    description = payload[0]["function"]["description"]

    assert "Tool guidance:" in description
    assert "Best for tasks: debug_runtime, inspect_runtime_state." in description
    assert "Domain: runtime, system." in description
    assert "Typical operations: probe, inspect." in description
    assert "Query shape: shell_command, one_off_check." in description
    assert "Avoid for task types: explore_codebase, research_external." in description


def test_build_tools_parameter_adds_same_language_guidance_for_ask_user_question() -> None:
    tools_registry = {
        "ask_user_question": {
            "description": (
                "Ask the user a clarifying question in the same language as the latest "
                "user message and wait for their reply."
            ),
            "metadata": {
                "tool_hint": (
                    "Use only when a missing user decision blocks safe progress or would likely "
                    "cause rework. Write the question and options in the same language as the "
                    "latest user message."
                ),
                "task_intents": ["clarify_requirement"],
                "domains": ["user"],
                "operations": ["clarify"],
                "query_shapes": ["blocking_decision"],
                "blocks_on_user": True,
            },
            "parameters": [
                {
                    "name": "question",
                    "type": "string",
                    "required": True,
                    "description": "The question to ask the user. Write it in the same language as the latest user message.",
                },
            ],
        },
    }
    orchestrator = _make_orchestrator_with_tools(tools_registry)

    payload = orchestrator._build_tools_parameter(["ask_user_question"])
    description = payload[0]["function"]["description"]
    question_description = payload[0]["function"]["parameters"]["properties"]["question"]["description"]

    assert "same language as the latest user message" in description
    assert "same language as the latest user message" in question_description
