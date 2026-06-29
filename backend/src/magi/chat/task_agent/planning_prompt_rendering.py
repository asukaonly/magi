"""Pure rendering helpers for chat task planning prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LeafWorkerPromptInput:
    root_user_message: str
    subtask_description: str
    subtask_prompt: str
    request_profile: str
    subagent_type: str | None
    target_language: str
    tool_guidance: str
    date_range_hint: dict[str, str] | None = None


def build_leaf_worker_prompt(spec: LeafWorkerPromptInput) -> str:
    response_language_line = _response_language_line(spec.target_language)
    if spec.request_profile == "research":
        return _build_research_leaf_worker_prompt(spec, response_language_line)
    if str(spec.subagent_type or "").strip() == "general-purpose":
        return _build_general_leaf_worker_prompt(spec, response_language_line)
    return _build_code_leaf_worker_prompt(spec, response_language_line)


def render_planning_prompt_markdown(
    planning_prompt: dict[str, Any],
    *,
    default_target_language: str,
) -> str:
    lines: list[str] = ["# Planning Brief", ""]

    _append_planning_context(lines, planning_prompt)
    _append_response_language(lines, planning_prompt, default_target_language)
    _append_user_request(lines, planning_prompt)
    _append_recent_history(lines, _payload_list(planning_prompt, "recent_history"))
    _append_workspace_context(lines, _payload_dict_or_none(planning_prompt, "workspace_context"))
    _append_date_range_hint(lines, _payload_dict_or_none(planning_prompt, "date_range_hint"))
    _append_task_hints(lines, planning_prompt.get("task_hints"))
    _append_seed_subtasks(lines, _payload_list(planning_prompt, "seed_subtasks"))
    _append_requirements(lines, _payload_list(planning_prompt, "requirements"))
    _append_output_contract(lines)

    return "\n".join(lines).strip()


def render_planning_task_hint_markdown(task_hint: Any) -> list[str]:
    if not isinstance(task_hint, dict):
        return []

    lines: list[str] = []
    _append_task_hint_fields(lines, task_hint)
    _append_task_hint_tools(lines, _payload_list(task_hint, "tool_hints"))
    return lines


def _response_language_line(target_language: str) -> str:
    return (
        f"Response language: {target_language}. Write natural-language JSON values, findings, gaps, "
        "and next_steps in this language unless quoting exact source titles, identifiers, paths, or commands."
    )


def _build_research_leaf_worker_prompt(
    spec: LeafWorkerPromptInput,
    response_language_line: str,
) -> str:
    lines = _base_leaf_lines(spec, response_language_line)
    if spec.date_range_hint:
        lines.append(
            f"Normalized date range: {spec.date_range_hint['start_date']} to {spec.date_range_hint['end_date']} (inclusive)."
        )
    lines.extend(
        [
            spec.subtask_prompt,
            *([spec.tool_guidance] if spec.tool_guidance else []),
            "Success criteria:",
            "- Stay strictly within this subtask scope.",
            "- Prefer web-search for discovery and only use web-fetch when the task explicitly requires article details or verification.",
            "- When a normalized date range is available, pass it to web-search via `start_date` and `end_date` instead of relying on a fuzzy year in the query.",
            "- Preserve concrete evidence for each usable result: title, date, source, canonical link, and a short summary when available.",
            "- In findings, use `title` for the headline, `detail` for `DATE | SOURCE | SUMMARY`, and `path` for the canonical article URL.",
            "- If the available evidence is thin or conflicting, record it in gaps instead of guessing.",
            "- Gather evidence directly from your own sources; do not depend on sibling worker outputs or produce the final cross-source synthesis.",
            "- Do not fabricate publication dates, links, or sources.",
        ]
    )
    return "\n".join(lines)


def _build_general_leaf_worker_prompt(
    spec: LeafWorkerPromptInput,
    response_language_line: str,
) -> str:
    return "\n".join(
        [
            *_base_leaf_lines(spec, response_language_line),
            spec.subtask_prompt,
            *([spec.tool_guidance] if spec.tool_guidance else []),
            "Success criteria:",
            "- Stay strictly within this subtask scope.",
            "- Choose the evidence sources that fit the task: current workspace, official docs, public sources, or a bounded combination.",
            "- If the target is not guaranteed to exist in the current workspace, do not assume local files exist; use external discovery first.",
            "- When you reference repo-local code, verify the exact file or symbol before relying on it.",
            "- When you reference external evidence, preserve title, date, source, and canonical link when available.",
            "- Gather evidence directly; do not depend on sibling worker outputs or write the final cross-worker synthesis.",
            "- Prefer validated findings over speculation.",
            "- If information is missing, put it into gaps instead of guessing.",
        ]
    )


def _build_code_leaf_worker_prompt(
    spec: LeafWorkerPromptInput,
    response_language_line: str,
) -> str:
    return "\n".join(
        [
            *_base_leaf_lines(spec, response_language_line),
            spec.subtask_prompt,
            *([spec.tool_guidance] if spec.tool_guidance else []),
            "Success criteria:",
            "- Stay strictly within this subtask scope.",
            "- Start from the most concrete anchor available: an entry file, symbol, path, interface, or directly controlling module.",
            "- If you name a file, symbol, route, config key, or flag, verify it exists in the current code before relying on it.",
            "- Prefer focused glob/grep/read steps over broad repository scans.",
            "- Use absolute file paths in findings and evidence when you reference code.",
            "- Prefer validated findings over speculation.",
            "- If information is missing, put it into gaps instead of guessing.",
            "- Do not duplicate likely sibling subtasks unless it is necessary evidence.",
        ]
    )


def _base_leaf_lines(spec: LeafWorkerPromptInput, response_language_line: str) -> list[str]:
    return [
        f"Parent user request: {spec.root_user_message}",
        f"Assigned subtask: {spec.subtask_description}",
        response_language_line,
        "Task-specific instructions:",
    ]


def _append_planning_context(lines: list[str], planning_prompt: dict[str, Any]) -> None:
    planning_profile = str(planning_prompt.get("planning_profile") or "generic").strip()
    default_leaf_type = str(planning_prompt.get("default_leaf_type") or "CodeExplore").strip()
    allow_parallel = bool(planning_prompt.get("allow_parallel", True))
    lines.extend(
        [
            "## Planning Context",
            f"- Planning profile: {planning_profile}",
            f"- Default leaf type: {default_leaf_type}",
            f"- Parallel execution allowed: {'yes' if allow_parallel else 'no'}",
            "",
        ]
    )


def _append_response_language(
    lines: list[str],
    planning_prompt: dict[str, Any],
    default_target_language: str,
) -> None:
    target_language = str(planning_prompt.get("target_language") or default_target_language).strip()
    lines.extend(
        [
            "## Response Language",
            f"- Target language: {target_language}",
            "- Keep all natural-language JSON values in this language unless preserving exact names, paths, commands, or source titles.",
            "",
        ]
    )


def _append_user_request(lines: list[str], planning_prompt: dict[str, Any]) -> None:
    user_request = str(planning_prompt.get("user_request") or "").strip()
    if user_request:
        lines.extend(
            [
                "## User Request",
                user_request,
                "",
            ]
        )


def _append_recent_history(lines: list[str], recent_history: list[Any]) -> None:
    if not recent_history:
        return

    lines.append("## Recent History")
    for item in recent_history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "unknown").strip() or "unknown"
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- {role}: {content}")
    lines.append("")


def _append_workspace_context(
    lines: list[str],
    workspace_context: dict[str, Any] | None,
) -> None:
    if not workspace_context:
        return

    lines.extend(
        [
            "## Workspace Context",
            f"- Workspace root: {str(workspace_context.get('workspace_root') or '').strip()}",
            f"- Workspace name: {str(workspace_context.get('workspace_name') or '').strip()}",
            "",
        ]
    )


def _append_date_range_hint(lines: list[str], date_range_hint: dict[str, Any] | None) -> None:
    if not date_range_hint:
        return

    lines.extend(
        [
            "## Date Range Hint",
            f"- Start date: {str(date_range_hint.get('start_date') or '').strip()}",
            f"- End date: {str(date_range_hint.get('end_date') or '').strip()}",
            "",
        ]
    )


def _append_task_hints(lines: list[str], task_hint: Any) -> None:
    task_hint_lines = render_planning_task_hint_markdown(task_hint)
    if not task_hint_lines:
        return

    lines.append("## Task Hints")
    lines.extend(task_hint_lines)
    lines.append("")


def _append_seed_subtasks(lines: list[str], seed_subtasks: list[Any]) -> None:
    if not seed_subtasks:
        return

    lines.append("## Seed Subtasks")
    for index, item in enumerate(seed_subtasks, start=1):
        if not isinstance(item, dict):
            continue
        _append_seed_subtask(lines, index, item)
    lines.append("")


def _append_seed_subtask(lines: list[str], index: int, item: dict[str, Any]) -> None:
    description = str(item.get("description") or f"Seed subtask {index}").strip()
    subagent_type = str(item.get("subagent_type") or "").strip()
    parallel_group = str(item.get("parallel_group") or "").strip()
    prompt = str(item.get("prompt") or "").strip()
    summary_parts = [description]
    if subagent_type:
        summary_parts.append(f"type={subagent_type}")
    if parallel_group:
        summary_parts.append(f"parallel_group={parallel_group}")
    lines.append(f"- {' | '.join(summary_parts)}")
    if prompt:
        lines.append(f"  Prompt: {prompt}")


def _append_requirements(lines: list[str], requirements: list[Any]) -> None:
    if not requirements:
        return

    lines.append("## Requirements")
    for item in requirements:
        requirement = str(item or "").strip()
        if requirement:
            lines.append(f"- {requirement}")
    lines.append("")


def _append_output_contract(lines: list[str]) -> None:
    lines.extend(
        [
            "## Output Contract",
            "- Return ONLY valid JSON that matches the system prompt schema.",
            "- Produce execution-ready leaf tasks rather than answering the user directly.",
            "- Keep summary, description, prompt, findings, gaps, and next_steps values in the target language.",
        ]
    )


def _append_task_hint_fields(lines: list[str], task_hint: dict[str, Any]) -> None:
    field_labels = [
        ("task_intent", "Task intent"),
        ("domain", "Domain"),
        ("operation", "Operation"),
        ("target_locality", "Target locality"),
        ("preferred_resolution_order", "Preferred resolution order"),
    ]
    for field_name, label in field_labels:
        value = str(task_hint.get(field_name) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")

    if "requires_clarification" in task_hint:
        lines.append(
            f"- Requires clarification: {'yes' if bool(task_hint.get('requires_clarification')) else 'no'}"
        )


def _append_task_hint_tools(lines: list[str], tool_hints: list[Any]) -> None:
    if not tool_hints:
        return

    lines.append("- Preferred tools:")
    for item in tool_hints:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or "unknown").strip()
        priority = item.get("priority")
        reason = str(item.get("reason") or "").strip()
        tool_line = f"  - {tool_name}"
        if priority not in (None, ""):
            tool_line += f" (priority {priority})"
        if reason:
            tool_line += f": {reason}"
        lines.append(tool_line)


def _payload_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _payload_dict_or_none(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None
