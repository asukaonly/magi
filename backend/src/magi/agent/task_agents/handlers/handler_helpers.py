"""Pure helper functions for chat execution handlers."""
from __future__ import annotations


from collections.abc import Sequence

from ....config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
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
        "For questions about personal facts, preferences, prior conversations or historical activity, use `memory_query` before answering any requested detail that is not explicitly supported by the supplied context.",
        "The portrait and working context are selective summaries, not a complete inventory of stored memory. A missing field never proves that no record exists.",
        "Before saying a personal detail is unknown, unrecorded or forgotten, query memory for that detail in this turn. For a multi-part question, check every unsupported part even when another part is already in the portrait.",
        "If retrieval fails or reports partial coverage, say that the lookup was incomplete rather than claiming the memory does not exist.",
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

PERSONAL_COMMITMENTS_GUIDANCE_BLOCK = "\n".join(
    [
        "# Personal Commitments",
        "For an explicit request to watch for a future condition, use attention_watch_query/update. "
        "Only authorized saved sources can be watched; never promise live website monitoring. "
        "Query attention_watch_query before claiming a watch's current status or last check. "
        "No notification is not evidence that an event did not happen: it only means no confirmed match was delivered. "
        "Never imply continuous coverage; checks depend on saved-source freshness, service availability and budgets. "
        "Use personal_task_query for current personal to-dos and projects across conversations. "
        "Capture the current user's clear first-person commitments and explicit requests with personal_task_update, "
        "then briefly acknowledge what was recorded. Query first to avoid duplicate commitments. "
        "Do not capture every request you are already answering as a new personal task. "
        "Never turn assistant suggestions, quoted text, hypothetical wishes, imported history or third-party "
        "observations into active user commitments. Imported/source suggestions require user acceptance. "
        "When the user reports progress, waiting, completion or cancellation, update the existing item. "
        "Progress writes must include the resulting fields.status; waiting for a person means waiting. "
        "Keep state and dates in structured fields instead of duplicating them as Markdown status sections. "
        "Resolve relative dates with current_time and the user's timezone. "
        "When the user specifies a day without a clock time, store due/defer_until as YYYY-MM-DD; "
        "do not invent midnight or 23:59 timestamps. "
        "Use the item's Markdown context to help with the next step using ordinary tools; save useful progress "
        "and output references. Completing an AI run does not complete the user's real-world work. "
        "Do not guess deadlines or claim a reminder was scheduled before the tool confirms its registration. "
        "During a review, suggest a few concrete decisions; do not silently reorganize commitments.",
    ]
)

PICTURE_STICKERS_GUIDANCE_BLOCK = "\n".join(
    [
        "## Picture stickers",
        "Use chat_stickers to list the library, or save/remove pictures only at the user's request. "
        "To reply with a saved picture alone, output exactly [[STICKER:sticker_id]], using an ID "
        "from the catalog or a successful chat_stickers result. Do not invent IDs or mix the marker "
        "with prose. Prefer ordinary text when a question, task result, failure or emotional disclosure "
        "needs a substantive answer. Choose stickers sparingly when their named mood fits the conversation.",
    ]
)


def append_static_blocks_before_cache_boundary(
    system_prompt: str,
    blocks: Sequence[str],
) -> str:
    """Insert deterministic static blocks immediately before SYSTEM_PROMPT_CACHE_BOUNDARY."""
    cleaned = [str(block).strip() for block in blocks if str(block or "").strip()]
    if not cleaned:
        return system_prompt
    if SYSTEM_PROMPT_CACHE_BOUNDARY in system_prompt:
        head, _, tail = system_prompt.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
        parts = [part for part in (head.rstrip(), *cleaned, SYSTEM_PROMPT_CACHE_BOUNDARY) if part]
        assembled = "\n\n".join(parts)
        return f"{assembled}{tail}" if tail else assembled
    parts = [part for part in (system_prompt.rstrip(), *cleaned) if part]
    return "\n\n".join(parts)


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
