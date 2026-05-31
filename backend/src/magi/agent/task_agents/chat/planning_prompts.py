"""Prompt and fallback builders for chat-owned task planning."""

from __future__ import annotations

import re
from typing import Any, Optional

from ....i18n import llm_language_label
from ....tools.schema import ToolExecutionContext
from ....tools.tool_hint_resolver import ToolHintResolver
from magi.bootstrap.tool_capabilities import build_tool_capabilities
from ...orchestration import PlannedSubtask
from .planning_heuristics import (
    build_research_seed_subtasks,
    classify_request_profile,
    extract_date_range_hint,
    is_complex_research_request,
    is_synthesis_only_subtask,
    looks_like_code_or_repo_request,
    looks_like_external_evidence_subtask,
    needs_research_fetch,
)

CODE_EXPLORE_LEAF_TYPE = "CodeExplore"
GENERAL_PURPOSE_LEAF_TYPE = "general-purpose"
LEAF_SUBAGENT_TYPES = {CODE_EXPLORE_LEAF_TYPE, GENERAL_PURPOSE_LEAF_TYPE}


class ChatPlanningPromptMixin:
    """Build fallback subtasks, leaf prompts, and planning tool contexts."""

    _agent_id: str
    _runtime_key: str
    _parent_task_agent_type: str
    _tool_hint_resolver: ToolHintResolver
    _FILE_TOOL_HINT_CANDIDATES: list[str]
    _WEB_TOOL_HINT_CANDIDATES: list[str]

    def _fallback_subtask_plan(
        self,
        user_message: str,
        default_leaf_type: str,
        *,
        request_profile: str,
    ) -> list[PlannedSubtask]:
        is_repo_architecture = any(
            keyword in user_message.lower()
            for keyword in [
                "architecture",
                "codebase",
                "repo",
                "代码架构",
                "项目架构",
                "代码库",
                "目录结构",
            ]
        )
        leaf_type = (
            default_leaf_type
            if default_leaf_type in LEAF_SUBAGENT_TYPES
            else CODE_EXPLORE_LEAF_TYPE
        )
        if request_profile == "research":
            return self._build_research_seed_subtasks(user_message)
        if is_repo_architecture:
            return [
                PlannedSubtask(
                    description="Map repository layout",
                    subagent_type=CODE_EXPLORE_LEAF_TYPE,
                    prompt="Analyze the top-level directory structure, major modules, and entry folders.",
                    parallel_group="group_a",
                ),
                PlannedSubtask(
                    description="Identify technology stack",
                    subagent_type=CODE_EXPLORE_LEAF_TYPE,
                    prompt="Inspect dependency manifests and boot files to identify the backend, frontend, storage, and runtime stack.",
                    parallel_group="group_a",
                ),
                PlannedSubtask(
                    description="Analyze frontend structure",
                    subagent_type=CODE_EXPLORE_LEAF_TYPE,
                    prompt="Focus on frontend organization, bootstrap flow, routing, and the main UI entry points.",
                    parallel_group="group_a",
                ),
                PlannedSubtask(
                    description="Analyze backend modules",
                    subagent_type=CODE_EXPLORE_LEAF_TYPE,
                    prompt="Focus on backend module boundaries, runtime startup, task agent chain, and the main execution flow.",
                    parallel_group="group_a",
                ),
                PlannedSubtask(
                    description="Inspect project progress",
                    subagent_type=CODE_EXPLORE_LEAF_TYPE,
                    prompt="Look for docs, progress trackers, release notes, or TODO-style files that indicate the current project status and recent progress.",
                    parallel_group="group_a",
                ),
            ]
        return [
            PlannedSubtask(
                description="Locate the primary anchor",
                subagent_type=leaf_type,
                prompt="Find the smallest set of files, symbols, or entry modules most likely to control the requested behavior or answer.",
                parallel_group="group_a",
            ),
            PlannedSubtask(
                description="Trace the owning implementation path",
                subagent_type=leaf_type,
                prompt="Follow the code path that directly computes, routes, or controls the requested behavior, pulling in only the nearby dependencies needed to explain it.",
                parallel_group="group_a",
            ),
            PlannedSubtask(
                description="Validate gaps and edge cases",
                subagent_type=leaf_type,
                prompt="Validate important edge cases, unresolved assumptions, and remaining gaps from source evidence instead of repeating broad summary prose.",
                parallel_group="group_b",
            ),
        ]

    def _build_leaf_worker_prompt(
        self,
        *,
        root_user_message: str,
        subtask_description: str,
        subtask_prompt: str,
        request_profile: str,
        subagent_type: str | None = None,
    ) -> str:
        target_language = llm_language_label()
        response_language_line = (
            f"Response language: {target_language}. Write natural-language JSON values, findings, gaps, "
            "and next_steps in this language unless quoting exact source titles, identifiers, paths, or commands."
        )
        tool_guidance = self._tool_hint_resolver.render_guidance_block(
            self._resolve_leaf_task_hint(
                root_user_message=root_user_message,
                subtask_prompt=subtask_prompt,
                request_profile=request_profile,
                subagent_type=subagent_type,
            )
        )
        if request_profile == "research":
            date_range_hint = self._extract_date_range_hint(root_user_message)
            lines = [
                f"Parent user request: {root_user_message}",
                f"Assigned subtask: {subtask_description}",
                response_language_line,
                "Task-specific instructions:",
                subtask_prompt,
                *([tool_guidance] if tool_guidance else []),
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
            if date_range_hint:
                lines.insert(
                    4,
                    f"Normalized date range: {date_range_hint['start_date']} to {date_range_hint['end_date']} (inclusive).",
                )
            return "\n".join(lines)
        if str(subagent_type or "").strip() == "general-purpose":
            return "\n".join(
                [
                    f"Parent user request: {root_user_message}",
                    f"Assigned subtask: {subtask_description}",
                    response_language_line,
                    "Task-specific instructions:",
                    subtask_prompt,
                    *([tool_guidance] if tool_guidance else []),
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
        return "\n".join(
            [
                f"Parent user request: {root_user_message}",
                f"Assigned subtask: {subtask_description}",
                response_language_line,
                "Task-specific instructions:",
                subtask_prompt,
                *([tool_guidance] if tool_guidance else []),
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

    def _resolve_planning_task_hint(
        self,
        *,
        user_message: str,
        request_profile: str,
        default_leaf_type: str,
    ) -> dict[str, Any]:
        available_tools = (
            list(self._WEB_TOOL_HINT_CANDIDATES)
            if request_profile == "research"
            else self._candidate_file_tools(default_leaf_type, user_message)
        )
        return self._tool_hint_resolver.resolve(
            user_message=user_message,
            available_tools=available_tools,
            request_profile=request_profile,
        )

    def _resolve_leaf_task_hint(
        self,
        *,
        root_user_message: str,
        subtask_prompt: str,
        request_profile: str,
        subagent_type: str | None,
    ) -> dict[str, Any]:
        if request_profile == "research":
            available_tools = list(self._WEB_TOOL_HINT_CANDIDATES)
            hint_profile = "research"
        elif str(subagent_type or "").strip() == "general-purpose":
            available_tools = list(self._WEB_TOOL_HINT_CANDIDATES)
            hint_profile = "research"
        elif str(
            subagent_type or ""
        ).strip() == CODE_EXPLORE_LEAF_TYPE or self._looks_like_code_or_repo_request(
            root_user_message, subtask_prompt
        ):
            available_tools = list(self._FILE_TOOL_HINT_CANDIDATES)
            hint_profile = request_profile
        else:
            available_tools = []
            hint_profile = request_profile
        return self._tool_hint_resolver.resolve(
            user_message=root_user_message,
            available_tools=available_tools,
            request_profile=hint_profile,
        )

    def _candidate_file_tools(self, default_leaf_type: str, user_message: str) -> list[str]:
        if default_leaf_type == CODE_EXPLORE_LEAF_TYPE or self._looks_like_code_or_repo_request(
            user_message, ""
        ):
            return list(self._FILE_TOOL_HINT_CANDIDATES)
        return []

    def _build_workspace_context(self, workspace_root: str | None) -> dict[str, str] | None:
        normalized = str(workspace_root or "").strip()
        if not normalized:
            return None
        workspace_name = re.sub(
            r"[^A-Za-z0-9._-]+", " ", normalized.rstrip("/").split("/")[-1]
        ).strip()
        return {
            "workspace_root": normalized,
            "workspace_name": workspace_name or normalized,
        }

    def _render_planning_prompt_markdown(self, planning_prompt: dict[str, Any]) -> str:
        lines: list[str] = ["# Planning Brief", ""]

        planning_profile = str(planning_prompt.get("planning_profile") or "generic").strip()
        default_leaf_type = str(
            planning_prompt.get("default_leaf_type") or CODE_EXPLORE_LEAF_TYPE
        ).strip()
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

        target_language = str(
            planning_prompt.get("target_language") or llm_language_label()
        ).strip()
        lines.extend(
            [
                "## Response Language",
                f"- Target language: {target_language}",
                "- Keep all natural-language JSON values in this language unless preserving exact names, paths, commands, or source titles.",
                "",
            ]
        )

        user_request = str(planning_prompt.get("user_request") or "").strip()
        if user_request:
            lines.extend(
                [
                    "## User Request",
                    user_request,
                    "",
                ]
            )

        recent_history = (
            planning_prompt.get("recent_history")
            if isinstance(planning_prompt.get("recent_history"), list)
            else []
        )
        if recent_history:
            lines.append("## Recent History")
            for item in recent_history:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "unknown").strip() or "unknown"
                content = str(item.get("content") or "").strip()
                if content:
                    lines.append(f"- {role}: {content}")
            lines.append("")

        workspace_context = (
            planning_prompt.get("workspace_context")
            if isinstance(planning_prompt.get("workspace_context"), dict)
            else None
        )
        if workspace_context:
            lines.extend(
                [
                    "## Workspace Context",
                    f"- Workspace root: {str(workspace_context.get('workspace_root') or '').strip()}",
                    f"- Workspace name: {str(workspace_context.get('workspace_name') or '').strip()}",
                    "",
                ]
            )

        date_range_hint = (
            planning_prompt.get("date_range_hint")
            if isinstance(planning_prompt.get("date_range_hint"), dict)
            else None
        )
        if date_range_hint:
            lines.extend(
                [
                    "## Date Range Hint",
                    f"- Start date: {str(date_range_hint.get('start_date') or '').strip()}",
                    f"- End date: {str(date_range_hint.get('end_date') or '').strip()}",
                    "",
                ]
            )

        task_hint_lines = self._render_planning_task_hint_markdown(
            planning_prompt.get("task_hints")
        )
        if task_hint_lines:
            lines.append("## Task Hints")
            lines.extend(task_hint_lines)
            lines.append("")

        seed_subtasks = (
            planning_prompt.get("seed_subtasks")
            if isinstance(planning_prompt.get("seed_subtasks"), list)
            else []
        )
        if seed_subtasks:
            lines.append("## Seed Subtasks")
            for index, item in enumerate(seed_subtasks, start=1):
                if not isinstance(item, dict):
                    continue
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
            lines.append("")

        requirements = (
            planning_prompt.get("requirements")
            if isinstance(planning_prompt.get("requirements"), list)
            else []
        )
        if requirements:
            lines.append("## Requirements")
            for item in requirements:
                requirement = str(item or "").strip()
                if requirement:
                    lines.append(f"- {requirement}")
            lines.append("")

        lines.extend(
            [
                "## Output Contract",
                "- Return ONLY valid JSON that matches the system prompt schema.",
                "- Produce execution-ready leaf tasks rather than answering the user directly.",
                "- Keep summary, description, prompt, findings, gaps, and next_steps values in the target language.",
            ]
        )
        return "\n".join(lines).strip()

    @staticmethod
    def _render_planning_task_hint_markdown(task_hint: Any) -> list[str]:
        if not isinstance(task_hint, dict):
            return []

        lines: list[str] = []
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

        tool_hints = (
            task_hint.get("tool_hints") if isinstance(task_hint.get("tool_hints"), list) else []
        )
        if tool_hints:
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
        return lines

    def _normalize_leaf_subagent_type(
        self,
        *,
        requested_subagent_type: str | None,
        default_leaf_type: str,
        request_profile: str,
        root_user_message: str,
        description: str,
        subtask_prompt: str,
    ) -> str:
        subagent_type = str(requested_subagent_type or default_leaf_type).strip()
        if subagent_type not in LEAF_SUBAGENT_TYPES:
            subagent_type = (
                default_leaf_type
                if default_leaf_type in LEAF_SUBAGENT_TYPES
                else CODE_EXPLORE_LEAF_TYPE
            )
        if request_profile == "research":
            return GENERAL_PURPOSE_LEAF_TYPE
        if subagent_type == CODE_EXPLORE_LEAF_TYPE:
            if self._looks_like_external_evidence_subtask(description, subtask_prompt):
                return GENERAL_PURPOSE_LEAF_TYPE
            if not self._looks_like_code_or_repo_request(
                root_user_message, f"{description}\n{subtask_prompt}"
            ):
                return GENERAL_PURPOSE_LEAF_TYPE
        return subagent_type

    def _looks_like_external_evidence_subtask(self, description: str, subtask_prompt: str) -> bool:
        return looks_like_external_evidence_subtask(description, subtask_prompt)

    def _is_synthesis_only_subtask(self, description: str, subtask_prompt: str) -> bool:
        return is_synthesis_only_subtask(description, subtask_prompt)

    @staticmethod
    def _looks_like_code_or_repo_request(user_message: str, subtask_prompt: str) -> bool:
        return looks_like_code_or_repo_request(user_message, subtask_prompt)

    def _classify_request_profile(self, *, user_message: str, default_leaf_type: str) -> str:
        return classify_request_profile(
            user_message=user_message, default_leaf_type=default_leaf_type
        )

    def _is_complex_research_request(self, user_message: str) -> bool:
        return is_complex_research_request(user_message)

    def _needs_research_fetch(self, user_message: str) -> bool:
        return needs_research_fetch(user_message)

    def _build_research_seed_subtasks(self, user_message: str) -> list[PlannedSubtask]:
        return build_research_seed_subtasks(user_message)

    def _extract_date_range_hint(self, user_message: str) -> Optional[dict[str, str]]:
        return extract_date_range_hint(user_message)

    def _build_agent_tool_context(
        self,
        user_id: str,
        session_id: str,
        workspace_root: str | None = None,
        *,
        run_id: str | None = None,
        run_revision: int = 0,
    ) -> ToolExecutionContext:
        parent_task_agent_id = self._resolve_parent_task_agent_id(user_id, session_id)
        return ToolExecutionContext(
            agent_id=self._runtime_key,
            workspace=str(workspace_root or "").strip(),
            env_vars={
                "user_id": user_id,
                "session_id": session_id,
                "target_task_agent_type": self._parent_task_agent_type,
                "target_task_agent_id": parent_task_agent_id,
                "parent_task_agent_type": self._parent_task_agent_type,
                "parent_task_agent_id": parent_task_agent_id,
                "run_id": run_id or "",
                "run_revision": str(run_revision),
            },
            permissions=["authenticated"],
            capabilities=build_tool_capabilities(),
        )

    def _resolve_parent_task_agent_id(self, user_id: str, session_id: str) -> str:
        if self._parent_task_agent_type == "chat" and str(session_id).strip():
            return session_id
        return user_id


__all__ = ["ChatPlanningPromptMixin"]
