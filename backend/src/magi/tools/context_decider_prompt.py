"""Prompt construction helpers for ContextDecider."""
from __future__ import annotations

from typing import Any

from ..agent.message_utils import trim_latest_user_message
from .context_decider_context import ContextDeciderContext


def build_context_decider_prompt(
    *,
    tool_registry: Any,
    user_message: str,
    available_tools: list[dict[str, Any]],
    context: ContextDeciderContext | None,
) -> str:
    prompt = """## Available Tools

"""

    for tool in available_tools:
        name = tool.get("name", "unknown")
        desc = tool.get("description", "No description")
        prompt += f"- {name}: {desc}\n"

    if hasattr(tool_registry, "_skills") and tool_registry._skills:
        prompt += "\n## Available Skills\n\n"
        for name, skill in tool_registry._skills.items():
            desc = skill.description if hasattr(skill, "description") else "No description"
            if len(desc) > 150:
                desc = desc[:150] + "..."
            prompt += f"- /{name}: {desc}\n"

    prompt += f"""
## User Request

{user_message}

## Environment

"""
    if context:
        prompt += _build_environment_block(context=context, user_message=user_message)
    else:
        prompt += "- No environment info\n"

    if context and context.tool_advisory:
        prompt += _build_tool_advisory_block(context.tool_advisory)

    prompt += "\nRespond with ONLY the JSON object."
    return prompt
def _build_environment_block(*, context: ContextDeciderContext, user_message: str) -> str:
    lines: list[str] = []
    if context.os_name:
        os_line = context.os_name
        if context.os_version:
            os_line = f"{os_line} {context.os_version}"
        lines.append(f"- OS: {os_line}")
    if context.current_datetime:
        lines.append(f"- Current datetime: {context.current_datetime}")
    if context.timezone:
        lines.append(f"- Timezone: {context.timezone}")
    if context.workspace_path:
        lines.append(f"- Workspace path: {context.workspace_path}")
    if context.home_dir:
        lines.append(f"- Home directory: {context.home_dir}")

    block = "\n".join(lines)
    if block:
        block += "\n"
    block += _build_recent_conversation_block(context=context, user_message=user_message)
    block += _build_recent_tool_errors_block(context.recent_tool_errors)
    block += _build_recent_tool_state_block(context.recent_tool_state)
    return block


def _build_recent_conversation_block(*, context: ContextDeciderContext, user_message: str) -> str:
    recent_messages = context.recent_messages
    if isinstance(recent_messages, list) and recent_messages:
        recent_messages = trim_latest_user_message(recent_messages, user_message)
    if not isinstance(recent_messages, list) or not recent_messages:
        return ""

    lines = ["\n## Recent Conversation\n"]
    for item in recent_messages[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "unknown"))
        content = str(item.get("content", ""))
        lines.append(f"- {role}: {content}")
    return "\n".join(lines) + "\n"


def _build_recent_tool_errors_block(recent_tool_errors: Any) -> str:
    if not isinstance(recent_tool_errors, list) or not recent_tool_errors:
        return ""

    lines = ["\n## Recent Tool Errors\n"]
    for item in recent_tool_errors[:3]:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name", "unknown"))
        error_code = str(item.get("error_code", "UNKNOWN"))
        error_message = str(item.get("error_message", ""))
        config_path = str(item.get("config_path") or "").strip()
        next_action = str(item.get("next_action") or "").strip()
        line = f"- {tool_name}: {error_code} | {error_message}"
        if config_path:
            line += f" | config_path={config_path}"
        if next_action:
            line += f" | next_action={next_action}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _build_recent_tool_state_block(recent_tool_state: Any) -> str:
    if not isinstance(recent_tool_state, list) or not recent_tool_state:
        return ""

    lines = [
        "\n## Recent Tool State\n",
        "Use this as lightweight continuity from recent tool activity. If exact parameters, durations, or detailed outputs are needed, prefer `trace_query`.",
    ]
    for item in recent_tool_state[:4]:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name", "unknown"))
        status = str(item.get("status", "unknown"))
        line = f"- {tool_name}: {status}"
        execution_time_ms = item.get("execution_time_ms")
        if execution_time_ms not in (None, ""):
            line += f" | duration_ms={execution_time_ms}"
        outcome = str(item.get("outcome") or "").strip()
        if outcome:
            line += f" | outcome={outcome}"
        handles = item.get("handles")
        if isinstance(handles, list) and handles:
            line += f" | handles={', '.join(str(handle) for handle in handles[:4])}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _build_tool_advisory_block(tool_advisory: list[dict[str, Any]]) -> str:
    prompt = "\n## Tool Experience Notes\n\n"
    prompt += "The following tools have notable historical observations. Use this to inform your tool selection.\n\n"
    for advisory in tool_advisory:
        name = advisory.get("tool_name", "unknown")
        parts: list[str] = []
        if not advisory.get("available", True):
            parts.append("UNAVAILABLE (breaker open)")
        rate = advisory.get("success_rate")
        attempts = advisory.get("total_attempts", 0)
        if rate is not None and attempts:
            parts.append(f"success {rate:.0%} over {attempts} uses")
        hint = advisory.get("strategy_hint")
        if hint:
            parts.append(f"tip: {hint}")
        risk = advisory.get("risk_note")
        if risk:
            parts.append(f"risk: {risk}")
        if parts:
            prompt += f"- {name}: {' | '.join(parts)}\n"
    return prompt
