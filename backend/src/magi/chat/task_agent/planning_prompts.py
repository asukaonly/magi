"""Prompt and fallback builders for chat-owned task planning."""

from __future__ import annotations

import re
from typing import Any, Optional

from magi.i18n import llm_language_label
from magi.tools.schema import ToolExecutionContext
from magi.tools.tool_hint_resolver import ToolHintResolver
from magi.tools.capabilities import build_tool_capabilities
from magi.agent.orchestration import PlannedSubtask
from .planning_prompt_rendering import (
    LeafWorkerPromptInput,
    build_leaf_worker_prompt,
    render_planning_prompt_markdown,
)
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
        tool_guidance = self._tool_hint_resolver.render_guidance_block(
            self._resolve_leaf_task_hint(
                root_user_message=root_user_message,
                subtask_prompt=subtask_prompt,
                request_profile=request_profile,
                subagent_type=subagent_type,
            )
        )
        return build_leaf_worker_prompt(
            LeafWorkerPromptInput(
                root_user_message=root_user_message,
                subtask_description=subtask_description,
                subtask_prompt=subtask_prompt,
                request_profile=request_profile,
                subagent_type=subagent_type,
                target_language=target_language,
                tool_guidance=tool_guidance,
                date_range_hint=(
                    self._extract_date_range_hint(root_user_message)
                    if request_profile == "research"
                    else None
                ),
            )
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
        return render_planning_prompt_markdown(
            planning_prompt,
            default_target_language=llm_language_label(),
        )

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
