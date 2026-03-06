"""Task agent dedicated to large Explore-style decompositions."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from ...agent.orchestration import TaskOrchestrationState, get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from ...core.logger import get_logger
from ...core.runtime.contracts import FactRecord
from ...core.runtime.task_agent import TaskAgent
from ...core.runtime.types import TaskAgentType
from ...events.events import EventTypes
from ...config import get_config
from ...llm.provider_bridge import LLMProviderBridge
from ...tools.registry import tool_registry
from ...utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = get_logger(__name__)
llm_logger = get_llm_logger("explore-task")

EXPLORE_TASK_REQUEST = "EXPLORE_TASK_REQUEST"
EXPLORE_TASK_COMPLETED = "EXPLORE_TASK_COMPLETED"
EXPLORE_TASK_FAILED = "EXPLORE_TASK_FAILED"

WORKER_AGENT_EVENT_TYPES = {
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
}

_CANONICAL_REPO_SECTIONS = {
    "Map repository layout": "Repository Layout",
    "Identify technology stack": "Technology Stack",
    "Analyze frontend structure": "Frontend Structure",
    "Analyze backend modules": "Backend Modules",
    "Inspect project progress": "Project Progress",
}


class ExploreTaskAgent(TaskAgent):
    """Parent task agent for large Explore tasks composed of leaf Explore workers."""

    def __init__(self, agent_id: str, llm_adapter) -> None:
        super().__init__(agent_type=TaskAgentType.EXPLORE, agent_id=agent_id)
        self.llm = llm_adapter
        self._last_batch_facts: list[FactRecord] = []
        self._request_history: dict[str, list[dict[str, str]]] = {}
        self._orchestration_store = get_orchestration_store()
        self._task_orchestrator = TaskOrchestrator(
            runtime_key=self.runtime_key,
            tool_registry=tool_registry,
            plan_subtasks=self._generate_subtask_plan,
            aggregate_orchestration=self._aggregate_orchestration,
            register_user_message=self._append_request_to_history,
            parent_task_agent_type=TaskAgentType.EXPLORE.value,
        )

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> dict[str, Any]:
        context = await super().build_context(merged_facts)
        batch_facts = list(self._last_batch_facts)
        latest_fact = context.get("latest_fact")
        payload = latest_fact.payload if isinstance(latest_fact, FactRecord) else {}
        user_id = str(payload.get("user_id", self.agent_id))
        session_id = str(payload.get("session_id", ""))
        user_message = str(payload.get("message") or payload.get("root_user_message") or "").strip()
        history_key = self._history_key(user_id, session_id)
        history_snapshot = payload.get("history_snapshot")
        if isinstance(history_snapshot, list) and history_snapshot:
            self._request_history[history_key] = [
                {
                    "role": str(item.get("role", "user")),
                    "content": str(item.get("content", "")),
                }
                for item in history_snapshot
                if isinstance(item, dict) and str(item.get("content", "")).strip()
            ]
        history = list(self._request_history.get(history_key, []))
        context.update(
            {
                "batch_facts": batch_facts,
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "history": history,
                "history_key": history_key,
                "upstream_task_agent_type": str(payload.get("upstream_task_agent_type") or TaskAgentType.CHAT.value),
                "upstream_task_agent_id": str(payload.get("upstream_task_agent_id") or user_id),
            }
        )
        return context

    async def match_intent(self, context: dict[str, Any]) -> dict[str, Any]:
        batch_facts = context.get("batch_facts", [])
        worker_batch = [
            fact
            for fact in batch_facts
            if isinstance(fact, FactRecord) and fact.event_type in WORKER_AGENT_EVENT_TYPES
        ]
        if worker_batch:
            return {
                "intent": "explore_orchestration_update",
                "execution_mode": "orchestration_update",
            }
        latest_fact = context.get("latest_fact")
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type == EXPLORE_TASK_REQUEST:
            return {
                "intent": "explore_request",
                "execution_mode": "orchestration_launch",
            }
        return {
            "intent": "fact_only",
            "execution_mode": "fact_only",
        }

    async def match_tools(self, context: dict[str, Any], intent_result: dict[str, Any]) -> dict[str, Any]:
        _ = context
        return {
            "tools": [],
            "orchestration_strategy": intent_result.get("orchestration_strategy", {}),
        }

    async def assemble_llm_params(
        self,
        context: dict[str, Any],
        intent_result: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        _ = tool_result
        return {
            "user_id": context.get("user_id", self.agent_id),
            "session_id": context.get("session_id", ""),
            "user_message": context.get("user_message", ""),
            "history": context.get("history", []),
            "history_key": context.get("history_key", ""),
            "batch_facts": context.get("batch_facts", []),
            "execution_mode": intent_result.get("execution_mode", "fact_only"),
            "orchestration_strategy": {
                "mode": "decompose",
                "planner": "task_agent",
                "default_leaf_type": "Explore",
                "allow_parallel": True,
            },
            "upstream_task_agent_type": context.get("upstream_task_agent_type", TaskAgentType.CHAT.value),
            "upstream_task_agent_id": context.get("upstream_task_agent_id", context.get("user_id", self.agent_id)),
        }

    async def call_llm(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        execution_mode = str(llm_params.get("execution_mode", "fact_only"))
        if execution_mode == "fact_only":
            return {"response": "", "skip_emit": True}
        if execution_mode == "orchestration_launch":
            latest_fact = context.get("latest_fact")
            return await self._task_orchestrator.start_orchestration(
                user_id=str(llm_params.get("user_id") or self.agent_id),
                session_id=str(llm_params.get("session_id") or ""),
                user_message=str(llm_params.get("user_message") or "").strip(),
                history=llm_params.get("history", []),
                history_key=str(llm_params.get("history_key", "")),
                correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
                orchestration_strategy=llm_params.get("orchestration_strategy", {}),
            )
        if execution_mode == "orchestration_update":
            return await self._task_orchestrator.process_worker_updates(llm_params.get("batch_facts", []))
        return {"response": "", "skip_emit": True}

    async def parse_result(self, context: dict[str, Any], raw_result: Any) -> None:
        if not isinstance(raw_result, dict) or raw_result.get("skip_emit"):
            return
        response_text = str(raw_result.get("response", "")).strip()
        if not response_text:
            return
        latest_fact = context.get("latest_fact")
        correlation_id = (
            str(raw_result.get("correlation_id"))
            if raw_result.get("correlation_id")
            else latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None
        )
        await self._emit_upstream_fact(
            event_type=EXPLORE_TASK_COMPLETED,
            user_id=str(context.get("user_id", self.agent_id)),
            session_id=str(context.get("session_id", "")),
            upstream_task_agent_type=str(context.get("upstream_task_agent_type", TaskAgentType.CHAT.value)),
            upstream_task_agent_id=str(context.get("upstream_task_agent_id", context.get("user_id", self.agent_id))),
            payload={
                "root_user_message": str(raw_result.get("root_user_message") or context.get("user_message") or ""),
                "markdown_dossier": response_text,
                "orchestration_id": raw_result.get("orchestration_id"),
                "message_started_at": raw_result.get("message_started_at"),
            },
            correlation_id=correlation_id,
        )

    async def _emit_upstream_fact(
        self,
        *,
        event_type: str,
        user_id: str,
        session_id: str,
        upstream_task_agent_type: str,
        upstream_task_agent_id: str,
        payload: dict[str, Any],
        correlation_id: Optional[str],
    ) -> None:
        try:
            from ...runtime import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
        except Exception as exc:
            logger.warning("Failed to deliver ExploreTaskAgent result upstream | error=%s", exc)
            return

        fact = FactRecord(
            agent_id=f"{upstream_task_agent_type}:{upstream_task_agent_id}",
            event_type=event_type,
            payload={
                "user_id": user_id,
                "session_id": session_id,
                "upstream_task_agent_type": upstream_task_agent_type,
                "upstream_task_agent_id": upstream_task_agent_id,
                **payload,
            },
            agent_type=upstream_task_agent_type,
            agent_instance_id=upstream_task_agent_id,
            timestamp=time.time(),
            correlation_id=correlation_id,
        )
        await manager.add_fact_to_agent(upstream_task_agent_type, upstream_task_agent_id, fact)

    async def _generate_subtask_plan(
        self,
        user_message: str,
        history: list[dict[str, Any]],
        orchestration_strategy: dict[str, Any],
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        _ = (orchestration_strategy, user_id, session_id)
        if self._is_repo_architecture_request(user_message):
            return {
                "summary": "Canonical codebase exploration plan.",
                "subtasks": self._canonical_repo_subtasks(user_message),
            }

        raw_plan = await self._plan_with_task_agent(user_message=user_message, history=history)
        if raw_plan is None:
            raw_plan = {
                "summary": "Fallback exploration plan generated by ExploreTaskAgent.",
                "subtasks": self._generic_fallback_subtasks(user_message),
            }
        return self._normalize_subtask_plan(user_message=user_message, raw_plan=raw_plan)

    async def _plan_with_task_agent(
        self,
        *,
        user_message: str,
        history: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        planning_prompt = {
            "user_request": user_message,
            "recent_history": history[-4:],
            "requirements": [
                "Decompose the exploration request into bounded Explore leaf subtasks only.",
                "Keep each subtask narrow enough for one worker to finish independently.",
                "Prefer parallel subtasks whenever dependencies are weak.",
                "Do not include final user-facing prose.",
            ],
        }
        system_prompt = (
            "You are ExploreTaskAgent planning bounded Explore subtasks. "
            "Return ONLY valid JSON with this schema: "
            '{"summary":"string","subtasks":[{"description":"string","subagent_type":"Explore","prompt":"string","parallel_group":"string"}]}.'
        )
        try:
            response = await self._call_llm(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": json.dumps(planning_prompt, ensure_ascii=False)}],
                disable_thinking=False,
            )
        except Exception as exc:
            logger.warning("ExploreTaskAgent planning call failed | error=%s", exc)
            return None
        return self._parse_subtask_plan(response)

    async def _aggregate_orchestration(self, state: TaskOrchestrationState) -> str:
        dossier = self._render_markdown_dossier(state)
        state.aggregated_markdown = dossier
        return dossier

    def _render_markdown_dossier(self, state: TaskOrchestrationState) -> str:
        completed = {
            item.description: item
            for item in state.subtasks
            if item.status == "completed" and isinstance(item.worker_result, dict)
        }
        failed = [item for item in state.subtasks if item.status == "failed"]
        evidence_lines = []
        gap_lines = []
        next_steps = []
        summary_lines = []

        for item in state.subtasks:
            worker_result = item.worker_result if isinstance(item.worker_result, dict) else {}
            summary = str(worker_result.get("summary", "")).strip()
            if summary and item.status == "completed":
                summary_lines.append(f"- **{item.description}:** {summary}")
            if item.status == "failed":
                gap_lines.append(f"- {item.description}: {item.failure_reason or 'Not completed in this run.'}")
            for gap in worker_result.get("gaps", []) if isinstance(worker_result, dict) else []:
                text = str(gap).strip()
                if text:
                    gap_lines.append(f"- {item.description}: {text}")
            for step in worker_result.get("next_steps", []) if isinstance(worker_result, dict) else []:
                text = str(step).strip()
                if text and text not in next_steps:
                    next_steps.append(text)
            for evidence in worker_result.get("evidence", []) if isinstance(worker_result, dict) else []:
                if not isinstance(evidence, dict):
                    continue
                path = str(evidence.get("path", "")).strip()
                detail = str(evidence.get("detail", "")).strip()
                if path and detail:
                    evidence_lines.append(f"- `{path}`: {detail}")

        lines = [
            "# Request",
            state.root_user_message,
            "",
            "# Exploration Summary",
            "\n".join(summary_lines) if summary_lines else "- No completed exploration sections yet.",
            "",
        ]

        for description, heading in _CANONICAL_REPO_SECTIONS.items():
            lines.extend(
                [
                    f"## {heading}",
                    self._render_subtask_section(completed.get(description), failed, description),
                    "",
                ]
            )

        lines.extend(
            [
                "## Confirmed Evidence",
                "\n".join(evidence_lines) if evidence_lines else "- No confirmed evidence was captured.",
                "",
                "## Gaps and Unverified Areas",
                "\n".join(gap_lines) if gap_lines else "- No explicit gaps were reported.",
                "",
                "## Recommended Next Steps",
                "\n".join(f"- {item}" for item in next_steps) if next_steps else "- No follow-up steps were suggested.",
            ]
        )
        return "\n".join(lines).strip()

    def _render_subtask_section(
        self,
        subtask: Optional[Any],
        failed: list[Any],
        description: str,
    ) -> str:
        if subtask is None:
            failed_item = next((item for item in failed if item.description == description), None)
            if failed_item is not None:
                return f"- Not fully verified. Failure reason: {failed_item.failure_reason or 'Unknown failure.'}"
            return "- Not explored in this run."

        worker_result = subtask.worker_result if isinstance(subtask.worker_result, dict) else {}
        result_lines = [str(worker_result.get("summary", "")).strip() or "- Completed without a summary."]
        findings = worker_result.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                title = str(finding.get("title", "")).strip()
                detail = str(finding.get("detail", "")).strip()
                path = str(finding.get("path", "")).strip()
                why = str(finding.get("why_it_matters", "")).strip()
                if title and detail:
                    line = f"- **{title}:** {detail}"
                    if path:
                        line += f" (`{path}`)"
                    if why:
                        line += f" - {why}"
                    result_lines.append(line)
        return "\n".join(result_lines)

    def _normalize_subtask_plan(self, user_message: str, raw_plan: dict[str, Any]) -> dict[str, Any]:
        raw_subtasks = raw_plan.get("subtasks")
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            raw_subtasks = self._generic_fallback_subtasks(user_message)
        normalized = []
        for item in raw_subtasks:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description", "")).strip()
            prompt = str(item.get("prompt", "")).strip()
            if not description or not prompt:
                continue
            normalized.append(
                {
                    "description": description,
                    "subagent_type": "Explore",
                    "prompt": self._build_leaf_prompt(user_message, description, prompt),
                    "parallel_group": str(item.get("parallel_group", "default")).strip() or "default",
                }
            )
        return {
            "summary": str(raw_plan.get("summary", "")).strip(),
            "subtasks": normalized,
        }

    def _parse_subtask_plan(self, response: str) -> Optional[dict[str, Any]]:
        raw = str(response or "").strip()
        if not raw:
            logger.warning("ExploreTaskAgent planning returned empty response")
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("ExploreTaskAgent planning returned invalid JSON | response_preview=%s", raw[:300])
            return None
        if not isinstance(payload, dict):
            return None
        subtasks = payload.get("subtasks")
        if not isinstance(subtasks, list) or not subtasks:
            logger.warning("ExploreTaskAgent planning returned empty subtasks")
            return None
        return {
            "summary": str(payload.get("summary", "")).strip(),
            "subtasks": [
                {
                    "description": str(item.get("description", "")).strip(),
                    "subagent_type": "Explore",
                    "prompt": str(item.get("prompt", "")).strip(),
                    "parallel_group": str(item.get("parallel_group", "default")).strip() or "default",
                }
                for item in subtasks
                if isinstance(item, dict)
                and str(item.get("description", "")).strip()
                and str(item.get("prompt", "")).strip()
            ],
        }

    def _canonical_repo_subtasks(self, user_message: str) -> list[dict[str, str]]:
        return [
            {
                "description": "Map repository layout",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Map repository layout",
                    "Analyze the top-level directory structure, major modules, and entry folders.",
                ),
                "parallel_group": "group_a",
            },
            {
                "description": "Identify technology stack",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Identify technology stack",
                    "Inspect dependency manifests and boot files to identify the backend, frontend, storage, and runtime stack.",
                ),
                "parallel_group": "group_a",
            },
            {
                "description": "Analyze frontend structure",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Analyze frontend structure",
                    "Focus on frontend organization, bootstrap flow, routing, and the main UI entry points.",
                ),
                "parallel_group": "group_a",
            },
            {
                "description": "Analyze backend modules",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Analyze backend modules",
                    "Focus on backend module boundaries, runtime startup, task agent chain, and the main execution flow.",
                ),
                "parallel_group": "group_a",
            },
            {
                "description": "Inspect project progress",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Inspect project progress",
                    "Look for docs, progress trackers, release notes, or TODO-style files that indicate the current project status and recent progress.",
                ),
                "parallel_group": "group_a",
            },
        ]

    def _generic_fallback_subtasks(self, user_message: str) -> list[dict[str, str]]:
        return [
            {
                "description": "Gather primary context",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Gather primary context",
                    "Collect the most relevant files, modules, and source-of-truth evidence for the request.",
                ),
                "parallel_group": "group_a",
            },
            {
                "description": "Analyze implementation details",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Analyze implementation details",
                    "Inspect the core implementation path, dependencies, and behavior that matter for the request.",
                ),
                "parallel_group": "group_a",
            },
            {
                "description": "Summarize risks and gaps",
                "subagent_type": "Explore",
                "prompt": self._build_leaf_prompt(
                    user_message,
                    "Summarize risks and gaps",
                    "Identify open questions, gaps, and next actions needed to complete the request.",
                ),
                "parallel_group": "group_b",
            },
        ]

    def _build_leaf_prompt(self, root_user_message: str, subtask_description: str, subtask_prompt: str) -> str:
        return "\n".join(
            [
                f"Parent user request: {root_user_message}",
                f"Assigned exploration subtask: {subtask_description}",
                "Task-specific instructions:",
                subtask_prompt,
                "Success criteria:",
                "- Stay strictly within this subtask scope.",
                "- Use absolute file paths in findings and evidence when you reference code.",
                "- Keep the result bounded and evidence-driven.",
                "- If the scope cannot be completed, set result_status to failed and explain the failure_reason.",
            ]
        )

    def _append_request_to_history(self, history_key: str, user_message: str) -> None:
        if not user_message:
            return
        history = self._request_history.setdefault(history_key, [])
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            return
        history.append({"role": "user", "content": user_message})

    def _history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def _is_repo_architecture_request(self, user_message: str) -> bool:
        lowered = user_message.lower()
        return any(
            keyword in lowered
            for keyword in ["architecture", "codebase", "repo", "代码架构", "项目架构", "代码库", "目录结构"]
        )

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool,
    ) -> str:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        model_name = getattr(self.llm, "model_name", "unknown")
        max_tokens = self._llm_max_tokens()
        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        try:
            provider_bridge = LLMProviderBridge(self.llm)
            provider_response = await provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.3,
                disable_thinking=disable_thinking,
            )
            response = provider_response.content
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms,
                provider_metadata=provider_response.metadata,
            )
            if not response.strip():
                logger.warning(
                    "ExploreTaskAgent LLM returned empty content | request_id=%s model=%s disable_thinking=%s metadata=%s",
                    request_id,
                    model_name,
                    disable_thinking,
                    provider_response.metadata,
                )
            return response
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise

    def _llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return 4096
