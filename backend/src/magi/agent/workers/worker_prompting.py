"""Prompt and tool-profile helpers for worker agents."""

from __future__ import annotations

import os
import platform
from datetime import datetime
from typing import Any, List, Optional, Protocol, cast

from ...utils.runtime import get_default_chat_workspace_path
from ...i18n import llm_language_label


class _WorkerPromptHostProtocol(Protocol):
    TYPE_GENERAL: str
    TYPE_EXPLORE: str
    TYPE_PLAN: str
    TYPE_CODING: str
    _WORKER_TYPE_MAP: dict[str, str]
    _EXPLORE_TOOL_CANDIDATES: list[str]
    _PLAN_TOOL_CANDIDATES: list[str]
    _CODING_TOOL_CANDIDATES: list[str]
    _tool_registry: Any


class WorkerPromptMixin:
    """Build worker prompts, tool scopes, and exploration profiles."""

    def _normalize_subagent_type(self, subagent_type: str) -> Optional[str]:
        host = cast(_WorkerPromptHostProtocol, self)
        return host._WORKER_TYPE_MAP.get(subagent_type.strip())

    def _resolve_tools_for_type(self, subagent_type: str) -> List[str]:
        host = cast(_WorkerPromptHostProtocol, self)
        available_tools = set(host._tool_registry.list_tools())
        if subagent_type == host.TYPE_GENERAL:
            return sorted(name for name in available_tools if name not in {"agent", "todo_write"})
        if subagent_type == host.TYPE_EXPLORE:
            return [name for name in host._EXPLORE_TOOL_CANDIDATES if name in available_tools]
        if subagent_type == host.TYPE_PLAN:
            return [name for name in host._PLAN_TOOL_CANDIDATES if name in available_tools]
        if subagent_type == host.TYPE_CODING:
            return [name for name in host._CODING_TOOL_CANDIDATES if name in available_tools]
        return []

    def _build_worker_system_prompt(
        self,
        worker_id: str,
        subagent_type: str,
        description: str,
        selected_tools: List[str],
        execution_workspace: Optional[str] = None,
    ) -> str:
        base_rules = (
            f"You are worker agent {worker_id}. "
            f"Task summary: {description}. "
            "You are a leaf executor. Stay inside the given scope, use tools autonomously when needed, "
            "and return only the requested structured JSON result."
        )
        environment_rules = self._build_worker_environment_rules(execution_workspace)
        tool_rules = (
            "Only use these tools: " + ", ".join(selected_tools)
            if selected_tools
            else "No tools are available. Reason directly from prompt context."
        )
        language_rules = (
            f"Response language: {llm_language_label()}. Write natural-language JSON values in this language "
            "unless preserving exact names, paths, commands, identifiers, or source titles."
        )
        role_rules = self._build_worker_role_rules(subagent_type, description)
        return "\n".join([base_rules, environment_rules, role_rules, language_rules, tool_rules])

    def _build_worker_role_rules(self, subagent_type: str, description: str) -> str:
        host = cast(_WorkerPromptHostProtocol, self)
        if subagent_type == host.TYPE_EXPLORE:
            return self._build_explore_role_rules(description)
        if subagent_type == host.TYPE_PLAN:
            return (
                "Act as a software architect. Return ONLY valid JSON with this schema: "
                '{"result_status":"success|partial|failed","summary":"string","findings":[{"title":"string","detail":"string"}],"evidence":[{"path":"string","detail":"string"}],"records":[{"field":"value"}],"gaps":["string"],"next_steps":["string"],"failure_reason":"string|null","subtasks":[{"description":"string","subagent_type":"CodeExplore|general-purpose","prompt":"string","parallel_group":"string"}]}. '
                "The plan must be decision-complete, keep subtasks bounded, and not include any final user-facing aggregation. "
                "Start from the most concrete anchor or owning code path you can identify, then split by neighboring responsibilities only when needed. "
                "Prefer execution-ready subtasks organized around concrete entry points, interfaces, modules, or discriminating checks. "
                "Avoid generic subtasks like gathering context or summarizing risks unless the parent request explicitly needs them or ambiguity remains unresolved. "
                "If you name a file, symbol, route, flag, or config key in findings or evidence, confirm it exists in the current code before treating it as fact. "
                "Put homogeneous structured rows in records, or use an empty list when there are none. Never return a top-level JSON array. "
                "Any response that is not a single valid JSON object will be treated as failure."
            )
        if subagent_type == host.TYPE_CODING:
            return self._build_coding_role_rules()
        return self._build_general_role_rules()

    def _build_general_role_rules(self) -> str:
        return (
            "Act as a general-purpose leaf execution agent for one bounded task. "
            "Return ONLY valid JSON with this schema: "
            '{"result_status":"success|partial|failed","summary":"string","findings":[{"title":"string","detail":"string"}],"evidence":[{"path":"string","detail":"string"}],"records":[{"field":"value"}],"gaps":["string"],"next_steps":["string"],"failure_reason":"string|null"}. '
            "For external evidence, evidence.path should be the canonical URL or source label. "
            "For local file evidence, evidence.path should be the verified file path. "
            "Put homogeneous structured rows such as file inventories or candidate lists in records, or use an empty list when there are none. Never return a top-level JSON array. "
            "Treat the iteration limit as a safety ceiling, not a target: stop as soon as the bounded task has enough evidence, and do not repeat equivalent searches. "
            "Any response that is not a single valid JSON object will be treated as failure."
        )

    def _build_coding_role_rules(self) -> str:
        return (
            "Role: small-scope coding worker for a single bounded change "
            "(typically 1-3 files).\n"
            "Discipline:\n"
            "1. Always file_read a file before file_edit / file_write overwrite.\n"
            "2. After every batch of edits, call verify (mode=changed). Do not "
            "claim done while verify reports failures unrelated to pre-existing issues.\n"
            "3. Match existing nearby style. Do not refactor unrelated code, do not "
            "add backwards-compatibility shims, and do not add comments unless the "
            "*why* is non-obvious.\n"
            "4. If a destructive bash command (rm -rf, git push --force, git reset "
            "--hard) is required, STOP and report. Never pass confirm_destructive=true "
            "on your own initiative; that decision is the user's.\n"
            "5. If two consecutive verify cycles still fail, stop and report what "
            "blocked you instead of looping.\n"
            "Final reply: plain text. List (a) files changed, (b) intent of the "
            "change, (c) verify summary, (d) anything you noticed but did not do."
        )

    def _build_worker_environment_rules(self, execution_workspace: Optional[str]) -> str:
        workspace_root = self._resolve_execution_workspace(execution_workspace)
        home_dir = os.path.realpath(os.path.expanduser("~"))
        current_time = datetime.now().astimezone().isoformat(timespec="seconds")
        return "\n".join(
            [
                "Execution environment:",
                f"- Workspace root: {workspace_root}",
                f"- Home directory: {home_dir}",
                f"- Operating system: {platform.system()} {platform.release()}",
                f"- Current local time: {current_time}",
                f"- Interpret '~' as: {home_dir}",
                "- Prefer paths under the workspace root unless the prompt explicitly requires another location.",
                "- Do not invent alternative Linux-style or macOS-style home paths when a path is missing; report the missing path instead.",
            ]
        )

    def _resolve_execution_workspace(self, execution_workspace: Optional[str]) -> str:
        raw_workspace = str(execution_workspace or "").strip() or get_default_chat_workspace_path()
        return os.path.realpath(os.path.expandvars(os.path.expanduser(raw_workspace)))

    def _build_explore_role_rules(self, description: str) -> str:
        lowered = description.lower()
        profile = self._select_explore_prompt_profile(lowered)
        common_rules = """
Role: CodeExplore worker for current workspace, repository, source-code, and local-file evidence only.
Do not handle web, current-world, travel, weather, restaurants, news, or other external evidence requests.
Prioritize bounded code exploration over exhaustive scans.
Common rules:
1.Directionality: Start from the layer most likely to contain the answer. If unclear, follow: frontend -> backend -> ops -> docs.
    2.Anchor First: Identify the most concrete likely anchor first (entry file, symbol, route, config, or owning module) and investigate that before widening scope.
2.Precision Search: Use targeted glob patterns to map structure, then grep for logic entry points. Strictly avoid root-level ls -R or dumping non-essential trees.
3.Execution Discipline: For glob calls, default to recursive=false and only recurse when pattern explicitly includes '**'. Never use '*' or '**/*' at repository root.
4.Scope Control: Start from one focused layer (frontend/, backend/, docs/, scripts/) and expand only if needed. Keep every glob/grep call at max_results <= 200.
5.Negative Constraints: Always exclude node_modules, dist, build, .git, .venv, __pycache__, and lock files. Do not read binary files or minified assets.
    6.Claim Validation: If you mention a file, symbol, route, flag, or config key in findings, confirm it exists in the current code before treating it as fact.
6.Incremental Validation: Identify 2-5 validated findings with absolute paths and a brief 'why it matters'. Prefer source-of-truth entry files over broad scans.
7.Response Validation: Your final answer must be one parseable JSON object and nothing else. Any prose, markdown, code fences, or trailing commentary will be treated as failure.
"""
        schema_rules = """
STRICT OUTPUT SCHEMA:
Return ONLY valid JSON with this schema:
{
  "result_status": "success|partial|failed",
  "summary": "string",
  "findings": [{"title": "string", "detail": "string", "path": "string", "why_it_matters": "string"}],
  "evidence": [{"path": "string", "detail": "string"}],
  "records": [{"field": "value"}],
  "gaps": ["string"],
  "next_steps": ["string"],
  "failure_reason": "string|null"
}
Do not emit Markdown, prose before the JSON, or fenced code blocks.
Put homogeneous structured rows in records, or use an empty list when there are none. Never return a top-level JSON array.
Before sending the final answer, self-check that it can be parsed by json.loads and that all required fields are present.
"""
        return "\n".join([common_rules.strip(), profile, schema_rules.strip()])

    def _select_explore_prompt_profile(self, lowered_description: str) -> str:
        if "repository layout" in lowered_description or "layout" in lowered_description:
            return """
SUBTASK PROFILE: Repository Layout
- Primary goal: map the top-level structure, major directories, and ownership boundaries.
- Start with immediate children of the repository root and major first-level folders before any recursive scan.
- Prefer directory and manifest evidence over reading many implementation files.
- Do not drift into detailed frontend/backend logic unless it is necessary to explain module boundaries.
""".strip()
        if "technology stack" in lowered_description or "tech stack" in lowered_description:
            return """
SUBTASK PROFILE: Technology Stack
- Primary goal: identify frameworks, runtimes, storage, package managers, and deployment/runtime targets.
- Prioritize dependency manifests, lockfiles, config files, boot files, and build scripts.
- Avoid broad source-code traversal unless a manifest is ambiguous and needs confirmation.
- Call out the evidence file that confirms each stack claim.
""".strip()
        if "frontend structure" in lowered_description or "frontend" in lowered_description:
            return """
SUBTASK PROFILE: Frontend Structure
- Primary goal: explain frontend organization, bootstrap flow, routing, stores, and key UI entry points.
- Start from frontend entry files, router setup, app shell, and major feature folders.
- Prefer reading index, main, router, page, and store files before component-level exploration.
- Do not spend time on backend or docs unless they directly explain the frontend boundary.
""".strip()
        if "backend modules" in lowered_description or "backend" in lowered_description:
            return """
SUBTASK PROFILE: Backend Modules
- Primary goal: explain backend module boundaries, runtime startup, task-agent chain, APIs, and execution flow.
- Start from backend bootstrap/backend.py and app entry files, then trace the task-agent and worker chain.
- Prefer source-of-truth files such as backend app creation, bootstrap wiring, router wiring, and agent runtime modules.
- Do not drift into frontend structure or docs unless they are required to explain a backend dependency.
""".strip()
        if "project progress" in lowered_description or "progress" in lowered_description:
            return """
SUBTASK PROFILE: Project Progress
- Primary goal: infer current project status, active migration work, and unfinished areas.
- Prioritize README, PROGRESS, CHANGELOG, migration plans, release notes, TODO-style docs, and roadmap files.
- Use source code only as supporting evidence when documentation is stale or missing.
- Do not spend time mapping the whole codebase; stay focused on status signals and recent direction.
""".strip()
        return """
SUBTASK PROFILE: Generic Exploration
- Primary goal: gather the minimum source-of-truth evidence needed to answer this bounded exploration request.
- Start from the most likely folder and expand only when evidence is incomplete.
- Prefer entry files, manifests, and coordinator modules over exhaustive file reads.
- Keep the result narrow, evidence-driven, and scoped to the assigned subtask.
""".strip()
