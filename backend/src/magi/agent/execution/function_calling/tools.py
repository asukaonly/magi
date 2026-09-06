"""Tool schema helpers for function-calling providers."""

from __future__ import annotations

from typing import Any

_JSON_SCHEMA_TYPE_ALIASES: dict[str, str] = {
    "float": "number",
    "file": "string",
}


def to_json_schema_type(raw: Any) -> str:
    """Return a JSON-Schema-valid type string for a tool parameter type."""
    text = str(raw or "string").strip().lower() or "string"
    return _JSON_SCHEMA_TYPE_ALIASES.get(text, text)


def build_tools_parameter(tool_registry: Any, selected_tools: list[str]) -> list[dict[str, Any]]:
    """Build the OpenAI-style tools parameter for selected tools and skills."""
    tools: list[dict[str, Any]] = []

    for tool_name in selected_tools:
        if _is_skill_tool(tool_registry, tool_name):
            tool_def = _skill_tool_definition(tool_registry, tool_name)
            if tool_def is not None:
                tools.append(tool_def)
            continue

        tool_info = tool_registry.get_tool_info(tool_name)
        if not tool_info:
            continue
        triggers = (tool_info.get("metadata") or {}).get("invocation_triggers")
        if triggers is not None and "model" not in triggers:
            continue
        exported_name = _exported_name(tool_registry, tool_name)
        tools.append(_registry_tool_definition(exported_name, tool_info))

    # Emit a deterministic, name-sorted order so an unchanged tool SET produces
    # a byte-identical tools parameter across turns even when the upstream
    # selector reranks it — preserving the provider prompt-cache prefix (#97).
    tools.sort(key=lambda tool: tool["function"]["name"])
    return tools


def _is_skill_tool(tool_registry: Any, tool_name: str) -> bool:
    return tool_name.startswith("/") or tool_registry.is_skill(tool_name.lstrip("/"))


def _exported_name(tool_registry: Any, name: str, *, skill: bool = False) -> str:
    exporter = getattr(tool_registry, "exported_tool_name", None)
    if callable(exporter):
        exported = exporter(name, skill=skill)
        if isinstance(exported, str):
            return exported
    return f"skill_{name}" if skill else name


def _skill_tool_definition(tool_registry: Any, tool_name: str) -> dict[str, Any] | None:
    skill_name = tool_name.lstrip("/")
    skill = tool_registry._skills.get(skill_name)
    if not skill or not hasattr(skill, "description"):
        return None
    return {
        "type": "function",
        "function": {
            "name": _exported_name(tool_registry, skill_name, skill=True),
            "description": skill.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The user's request or task description for this skill to accomplish"
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    }


def _registry_tool_definition(tool_name: str, tool_info: dict[str, Any]) -> dict[str, Any]:
    if tool_info.get("input_schema") is not None:
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": build_tool_description(tool_info),
                "parameters": tool_info["input_schema"],
            },
        }
    properties, required = _tool_parameter_schema(tool_info.get("parameters", []))
    tool_def: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": build_tool_description(tool_info),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
    tool_def["function"]["parameters"]["properties"] = properties
    tool_def["function"]["parameters"]["required"] = required
    return tool_def


def _tool_parameter_schema(
    parameters: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in parameters:
        param_name = param.get("name")
        if not param_name:
            continue
        properties[param_name] = _tool_parameter_property(param)
        if param.get("required", False):
            required.append(param_name)
    return properties, required


def _tool_parameter_property(param: dict[str, Any]) -> dict[str, Any]:
    prop_def: dict[str, Any] = {"type": to_json_schema_type(param.get("type", "string"))}
    if param.get("type") == "array":
        prop_def["items"] = {
            "type": to_json_schema_type(param.get("array_item_type", "string")),
        }
    if param.get("description"):
        prop_def["description"] = param["description"]
    if param.get("enum"):
        prop_def["enum"] = param["enum"]
    return prop_def


def build_tool_description(tool_info: dict[str, Any]) -> str:
    """Build provider-facing tool guidance from registry metadata."""
    description = str(tool_info.get("description", "") or "").strip()
    metadata = tool_info.get("metadata") if isinstance(tool_info.get("metadata"), dict) else {}
    tool_name = str(tool_info.get("name") or "").strip()
    if not metadata:
        if tool_name in {"glob", "grep"} and description:
            return f"{description}\n\nTool guidance: {_workspace_scan_guidance()}"
        return description

    guidance_parts: list[str] = []
    _append_metadata_guidance(guidance_parts, metadata)
    if metadata.get("requires_known_target"):
        guidance_parts.append("Best when the target is already known.")
    if metadata.get("blocks_on_user"):
        guidance_parts.append("Blocks on user input.")
    _append_tool_specific_guidance(guidance_parts, tool_name)

    if not guidance_parts:
        return description
    guidance = " ".join(guidance_parts)
    if description:
        return f"{description}\n\nTool guidance: {guidance}"
    return f"Tool guidance: {guidance}"


def _append_metadata_guidance(
    guidance_parts: list[str],
    metadata: dict[str, Any],
) -> None:
    tool_hint = str(metadata.get("tool_hint") or "").strip()
    if tool_hint:
        guidance_parts.append(tool_hint)
    _append_list_guidance(guidance_parts, "Best for tasks", metadata.get("task_intents", []))
    _append_list_guidance(guidance_parts, "Domain", metadata.get("domains", []))
    _append_list_guidance(guidance_parts, "Typical operations", metadata.get("operations", []))
    _append_list_guidance(guidance_parts, "Query shape", metadata.get("query_shapes", []))
    _append_list_guidance(guidance_parts, "Usually followed by", metadata.get("followed_by", []))
    _append_list_guidance(
        guidance_parts,
        "Avoid for task types",
        metadata.get("avoid_task_intents", []),
    )


def _append_list_guidance(
    guidance_parts: list[str],
    label: str,
    values: Any,
) -> None:
    items = [str(item).strip() for item in values if str(item).strip()]
    if items:
        guidance_parts.append(f"{label}: {', '.join(items)}.")


def _append_tool_specific_guidance(guidance_parts: list[str], tool_name: str) -> None:
    if tool_name in {"glob", "grep"}:
        guidance_parts.append(_workspace_scan_guidance())
    elif tool_name == "web-search":
        guidance_parts.append(
            "Prefer this before external local discovery when the target may be outside "
            "the current workspace and the user did not provide a path."
        )
    elif tool_name == "ask_user_question":
        guidance_parts.append(
            "Write the question and any options in the same language as the latest user message."
        )
        guidance_parts.append(
            "Use this when the target location is ambiguous and leaving the current workspace "
            "would otherwise require guessing."
        )


def _workspace_scan_guidance() -> str:
    return (
        "Keep scans inside the active workspace by default. If the target may be elsewhere "
        "but no explicit path was provided, ask the user for a path or use web-search before "
        "scanning outside the workspace."
    )
