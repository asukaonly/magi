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
        if tool_name.startswith("/") or tool_registry.is_skill(tool_name.lstrip("/")):
            skill_name = tool_name.lstrip("/")
            skill = tool_registry._skills.get(skill_name)
            if skill and hasattr(skill, "description"):
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"skill_{skill_name}",
                            "description": skill.description,
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "The user's request or task description for this skill to accomplish",
                                    }
                                },
                                "required": ["query"],
                            },
                        },
                    }
                )
            continue

        tool_info = tool_registry.get_tool_info(tool_name)
        if not tool_info:
            continue

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

        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in tool_info.get("parameters", []):
            param_name = param.get("name")
            if not param_name:
                continue

            prop_def: dict[str, Any] = {"type": to_json_schema_type(param.get("type", "string"))}
            if param.get("type") == "array":
                prop_def["items"] = {
                    "type": to_json_schema_type(param.get("array_item_type", "string")),
                }
            if param.get("description"):
                prop_def["description"] = param["description"]
            if param.get("enum"):
                prop_def["enum"] = param["enum"]

            properties[param_name] = prop_def
            if param.get("required", False):
                required.append(param_name)

        tool_def["function"]["parameters"]["properties"] = properties
        tool_def["function"]["parameters"]["required"] = required
        tools.append(tool_def)

    # Emit a deterministic, name-sorted order so an unchanged tool SET produces
    # a byte-identical tools parameter across turns even when the upstream
    # selector reranks it — preserving the provider prompt-cache prefix (#97).
    tools.sort(key=lambda tool: tool["function"]["name"])
    return tools


def build_tool_description(tool_info: dict[str, Any]) -> str:
    """Build provider-facing tool guidance from registry metadata."""
    description = str(tool_info.get("description", "") or "").strip()
    metadata = tool_info.get("metadata") if isinstance(tool_info.get("metadata"), dict) else {}
    tool_name = str(tool_info.get("name") or "").strip()
    if not metadata:
        if tool_name in {"glob", "grep"} and description:
            return (
                f"{description}\n\nTool guidance: Keep scans inside the active workspace by default. "
                "If the target may be elsewhere but no explicit path was provided, ask the user for a path or use web-search before scanning outside the workspace."
            )
        return description

    guidance_parts: list[str] = []
    tool_hint = str(metadata.get("tool_hint") or "").strip()
    if tool_hint:
        guidance_parts.append(tool_hint)
    task_intents = [str(item).strip() for item in metadata.get("task_intents", []) if str(item).strip()]
    if task_intents:
        guidance_parts.append(f"Best for tasks: {', '.join(task_intents)}.")
    domains = [str(item).strip() for item in metadata.get("domains", []) if str(item).strip()]
    if domains:
        guidance_parts.append(f"Domain: {', '.join(domains)}.")
    operations = [str(item).strip() for item in metadata.get("operations", []) if str(item).strip()]
    if operations:
        guidance_parts.append(f"Typical operations: {', '.join(operations)}.")
    query_shapes = [str(item).strip() for item in metadata.get("query_shapes", []) if str(item).strip()]
    if query_shapes:
        guidance_parts.append(f"Query shape: {', '.join(query_shapes)}.")
    followed_by = [str(item).strip() for item in metadata.get("followed_by", []) if str(item).strip()]
    if followed_by:
        guidance_parts.append(f"Usually followed by: {', '.join(followed_by)}.")
    avoid_task_intents = [str(item).strip() for item in metadata.get("avoid_task_intents", []) if str(item).strip()]
    if avoid_task_intents:
        guidance_parts.append(f"Avoid for task types: {', '.join(avoid_task_intents)}.")
    if metadata.get("requires_known_target"):
        guidance_parts.append("Best when the target is already known.")
    if metadata.get("blocks_on_user"):
        guidance_parts.append("Blocks on user input.")
    if tool_name in {"glob", "grep"}:
        guidance_parts.append(
            "Keep scans inside the active workspace by default. If the target may be elsewhere but no explicit path was provided, ask the user for a path or use web-search before scanning outside the workspace."
        )
    elif tool_name == "web-search":
        guidance_parts.append(
            "Prefer this before external local discovery when the target may be outside the current workspace and the user did not provide a path."
        )
    elif tool_name == "ask_user_question":
        guidance_parts.append(
            "Write the question and any options in the same language as the latest user message."
        )
        guidance_parts.append(
            "Use this when the target location is ambiguous and leaving the current workspace would otherwise require guessing."
        )

    if not guidance_parts:
        return description
    guidance = " ".join(guidance_parts)
    if description:
        return f"{description}\n\nTool guidance: {guidance}"
    return f"Tool guidance: {guidance}"
