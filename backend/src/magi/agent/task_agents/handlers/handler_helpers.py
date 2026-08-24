"""Pure helper functions for chat execution handlers."""
from __future__ import annotations


from ..common import PreparedAgentRunRequest


def build_attachment_preparation_guidance_block(selected_tools: list[str]) -> str:
    tool_names = set(selected_tools)
    if "prepare_chat_attachments" not in tool_names:
        return ""
    lines = [
        "# Attachment Preparation Guidance",
        "Use `memory_query` as the source of truth for historical recall when it is available for this turn.",
        "Only prepare chat attachments after the relevant entities or assets have already been identified by recall results or reusable reply context.",
        "If the user wants matched local assets sent in chat, first use the appropriate source resolver tool to obtain concrete `file_paths`, then call `prepare_chat_attachments`.",
        "Do not pass raw local file paths to the user. Use `prepare_chat_attachments` to import resolved `file_paths` into managed chat attachments.",
        "After `prepare_chat_attachments` succeeds, the backend attaches the returned `chat_attachments` to the assistant turn as structured message metadata.",
        "Return normal assistant text only. Do not emit attachment JSON, `attachment_id` values, raw `file_paths`, or any other transport markup in the assistant message.",
    ]
    return "\n".join(lines)


MEMORY_QUERY_GUIDANCE_BLOCK = "\n".join(
    [
        "# Memory Query Guidance",
        "Use `memory_query` results as the source of truth for historical recall in this turn.",
        "Prefer `memory_query` before broader search tools when the user asks about prior conversations, personal facts, preferences, or historical activity.",
        "The absence of an item from bounded prompt memory is not proof that no relevant history exists.",
    ]
)


MEMORY_UNAVAILABLE_GUIDANCE_BLOCK = "\n".join(
    [
        "# Memory Availability",
        "Historical memory lookup is unavailable for this turn.",
        "Do not interpret an empty memory section as evidence that the user has no relevant history.",
        "State the limitation instead of inventing or denying prior facts.",
    ]
)


def build_scope_guidance_block(task_hint: dict | None) -> str:
    if not isinstance(task_hint, dict) or not task_hint:
        return ""

    target_locality = str(task_hint.get("target_locality") or "").strip()
    preferred_resolution_order = str(task_hint.get("preferred_resolution_order") or "").strip()
    requires_clarification = bool(task_hint.get("requires_clarification"))
    if not any([target_locality, preferred_resolution_order, requires_clarification]):
        return ""

    lines = [
        "# Scope Guidance",
        "Treat the current workspace as the default search boundary unless the user explicitly names another path.",
    ]
    if target_locality:
        lines.append(f"Target locality: {target_locality}")
    if preferred_resolution_order:
        lines.append(f"Preferred resolution order: {preferred_resolution_order}")
    if requires_clarification:
        lines.append(
            "If leaving the workspace would be required and the target location is still ambiguous, ask the user for a path or use web-search before any external local scan."
        )
    elif target_locality == "web":
        lines.append(
            "Prefer web-search or web-fetch over local repo discovery unless the user explicitly points to a local path."
        )
    return "\n".join(lines)


def serialize_ux_plan(intent: object) -> dict | None:
    plan = getattr(intent, "ux_plan", None)
    if plan is None:
        return None
    to_dict = getattr(plan, "to_dict", None)
    return to_dict() if callable(to_dict) else plan


def resolve_execution_workspace(request: PreparedAgentRunRequest) -> str | None:
    prompt_context = getattr(request, "prompt_context", None)
    runtime_system = getattr(prompt_context, "runtime_system", None)
    prompt_cwd = str(getattr(runtime_system, "cwd", "") or "").strip()
    if prompt_cwd:
        return prompt_cwd
    return resolve_turn_workspace_path(request.context)


def resolve_turn_workspace_path(context: object) -> str | None:
    latest_payload = getattr(context, "latest_payload", None)
    workspace_path = str(getattr(latest_payload, "workspace_path", "") or "").strip()
    return workspace_path or None
