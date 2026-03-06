"""
Runtime task agent for chat facts.
"""
from __future__ import annotations

import json
import os
import platform
import sqlite3
import time
import uuid
from typing import Any, Optional

from ...agent.orchestration import (
    RETRIABLE_WORKER_FAILURES,
    SubtaskDefinition,
    TaskOrchestrationState,
    get_orchestration_store,
)
from ...core.logger import get_logger
from ...llm.provider_bridge import LLMProviderBridge
from ...utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from ...memory.behavior_evolution import SatisfactionLevel
from ...memory.context_builder import Scenario
from ...memory.emotional_state import EngagementLevel, InteractionOutcome
from ...memory.growth_memory import InteractionType
from ...memory.prompt_context_assembler import PromptContextAssembler, PromptContextRenderer
from ...skills.executor import SkillExecutor
from ...skills.indexer import SkillIndexer
from ...skills.loader import SkillLoader
from ..execution.function_calling import FunctionCallingExecutor
from ...tools.context_decider import ContextDecider
from ...tools.registry import tool_registry
from ...tools.schema import ToolExecutionContext
from ...utils.runtime import get_runtime_paths
from ...core.runtime.contracts import FactRecord
from ...core.runtime.task_agent import TaskAgent
from ...core.runtime.types import TaskAgentType
from ...events.events import EventTypes

logger = get_logger(__name__)
llm_logger = get_llm_logger('chat')
TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"
CHAT_TOOL_LOOP_STEP_EVENT_TYPE = "CHAT_TOOL_LOOP_STEP"
WORKER_AGENT_EVENT_TYPES = {
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
}


class ChatTaskAgent(TaskAgent):
    """Consumes chat facts and delegates response execution."""

    def __init__(
        self,
        agent_id: str,
        llm_adapter,
        memory=None,
        other_memory=None,
        unified_memory=None,
        memory_integration=None,
        history_cache_max_sessions: int = 500,
        history_fetch_limit: int = 200,
        scenario_prompts_store=None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self.llm = llm_adapter
        self.memory = memory
        self.other_memory = other_memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration
        self.context_decider = ContextDecider(tool_registry=tool_registry, llm_adapter=llm_adapter)
        self.prompt_context_assembler = PromptContextAssembler(
            tool_registry=tool_registry,
            scenario_prompts_store=scenario_prompts_store,
        )
        self.prompt_context_renderer = PromptContextRenderer()

        # Initialize skill system first (dependency for FunctionCallingExecutor)
        self._skill_indexer = SkillIndexer()
        self._skill_loader = SkillLoader(self._skill_indexer)
        self._skill_executor = SkillExecutor(self._skill_loader, llm_adapter)

        # Now create FunctionCallingExecutor with all dependencies properly injected
        self.function_calling_executor = FunctionCallingExecutor(
            llm_adapter=llm_adapter,
            tool_registry=tool_registry,
            skill_executor=self._skill_executor,
            tool_result_callback=self._record_tool_interaction,
            loop_event_callback=self._record_tool_loop_fact,
        )

        self._conversation_history: dict[str, list[dict]] = {}
        self._tool_interactions: dict[str, list[dict]] = {}
        self._current_session_by_user: dict[str, str] = {}
        self._history_cache_max_sessions = history_cache_max_sessions
        self._history_fetch_limit = history_fetch_limit
        self._history_cache_order: list[str] = []  # LRU tracking
        self._last_batch_facts: list[FactRecord] = []
        self._orchestration_store = get_orchestration_store()
        runtime_paths = get_runtime_paths()
        self._session_state_file = runtime_paths.data_dir / "chat_sessions.json"
        self._events_db_path = runtime_paths.events_db_path
        self._load_session_state()
        # Note: Removed _restore_conversation_from_events() - now using lazy loading in build_context

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
        if not payload and batch_facts:
            payload = batch_facts[-1].payload if isinstance(batch_facts[-1], FactRecord) else {}
        user_id = str(payload.get("user_id", self.agent_id))
        user_message = str(payload.get("message", "")).strip()
        session_id = self._resolve_session_id(user_id, payload.get("session_id"))
        history_key = self._history_key(user_id, session_id)

        # Lazy load history if not in cache
        history = await self._get_or_load_history(user_id, session_id, history_key)

        context.update(
            {
                "user_id": user_id,
                "user_message": user_message,
                "session_id": session_id,
                "history_key": history_key,
                "history": history,
                "batch_facts": batch_facts,
            }
        )
        active_orchestrations = await self._orchestration_store.list_orchestrations(
            user_id=user_id,
            session_id=session_id,
            statuses=["running", "aggregating"],
        )
        context["active_orchestrations"] = [item.to_dict() for item in active_orchestrations]
        return context

    async def _get_or_load_history(self, user_id: str, session_id: str, history_key: str) -> list[dict]:
        """Get history from cache or lazy load from storage."""
        if history_key in self._conversation_history:
            return self._conversation_history[history_key]

        # Lazy load from ChatReadService
        try:
            from ...api.services.chat_read_service import get_chat_read_service
            read_service = get_chat_read_service()
            history = read_service.get_conversation_history(
                user_id=user_id,
                session_id=session_id,
                limit=self._history_fetch_limit,
            )
            self._conversation_history[history_key] = history
            self._update_lru_cache(history_key)
            return history
        except Exception as exc:
            logger.warning(f"Failed to lazy load history | user={user_id} session={session_id} error={exc}")
            return []

    def _update_lru_cache(self, history_key: str) -> None:
        """Update LRU cache order and evict if necessary."""
        if history_key in self._history_cache_order:
            self._history_cache_order.remove(history_key)
        self._history_cache_order.append(history_key)

        # Evict oldest if over limit
        while len(self._history_cache_order) > self._history_cache_max_sessions:
            oldest_key = self._history_cache_order.pop(0)
            if oldest_key in self._conversation_history:
                del self._conversation_history[oldest_key]
            if oldest_key in self._tool_interactions:
                del self._tool_interactions[oldest_key]
            logger.debug(f"Evicted history cache for | key={oldest_key}")

    async def match_intent(self, context: dict[str, Any]) -> dict[str, Any]:
        batch_facts = context.get("batch_facts", [])
        worker_batch = [
            fact
            for fact in batch_facts
            if isinstance(fact, FactRecord) and fact.event_type in WORKER_AGENT_EVENT_TYPES
        ]
        if worker_batch:
            return {
                "intent": "worker_orchestration_update",
                "difficulty": "normal",
                "execution_mode": "orchestration_update",
                "tools": [],
                "deep_thinking": False,
                "reasoning": "Worker events must update orchestration state before any final response is emitted.",
                "orchestration_strategy": {},
            }
        latest_fact = context.get("latest_fact")
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type != EventTypes.USER_MESSAGE:
            return {
                "intent": "non_user_fact",
                "difficulty": "normal",
                "execution_mode": "fact_only",
                "tools": [],
                "deep_thinking": False,
                "reasoning": "Non-user fact does not require immediate LLM response",
                "orchestration_strategy": {},
            }

        user_message = context.get("user_message", "")
        history = context.get("history", [])
        recent_messages: list[dict[str, str]] = []
        for msg in history[-6:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "unknown"))
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if len(content) > 120:
                content = content[:120] + "..."
            recent_messages.append({"role": role, "content": content})
        decision_context = {
            "os": platform.system(),
            "os_version": platform.release(),
            "current_user": "unknown",
            "recent_messages": recent_messages,
        }
        decision = await self.context_decider.decide(user_message, decision_context)
        return {
            "intent": decision.intent,
            "difficulty": "hard" if decision.deep_thinking else "normal",
            "execution_mode": (
                "orchestration_launch"
                if decision.orchestration_strategy.get("mode") == "decompose" and "agent" in decision.tools
                else "function_calling" if decision.tools else "llm"
            ),
            "tools": decision.tools,
            "deep_thinking": decision.deep_thinking,
            "reasoning": decision.reasoning,
            "orchestration_strategy": decision.orchestration_strategy,
        }

    async def match_tools(self, context: dict[str, Any], intent_result: dict[str, Any]) -> dict[str, Any]:
        execution_mode = str(intent_result.get("execution_mode", "llm"))
        return {
            "tools": [] if execution_mode in {"orchestration_launch", "orchestration_update", "fact_only"} else intent_result.get("tools", []),
            "deep_thinking": bool(intent_result.get("deep_thinking", False)),
            "intent": str(intent_result.get("intent", "chat")),
            "orchestration_strategy": intent_result.get("orchestration_strategy", {}),
        }

    async def assemble_llm_params(
        self,
        context: dict[str, Any],
        intent_result: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        user_id = context["user_id"]
        session_id = context["session_id"]
        user_message = context["user_message"]
        history = context["history"]
        execution_mode = str(intent_result.get("execution_mode", "llm"))
        if execution_mode in {"fact_only", "orchestration_launch", "orchestration_update"}:
            return {
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "history": history,
                "batch_facts": context.get("batch_facts", []),
                "orchestration_strategy": tool_result.get("orchestration_strategy", {}),
                "execution_mode": execution_mode,
            }
        prompt_context = await self.build_prompt_context(
            context=context,
            intent_result=intent_result,
            tool_result=tool_result,
        )
        system_prompt = self.prompt_context_renderer.render_system_prompt(prompt_context)
        return {
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
            "history": history,
            "system_prompt": system_prompt,
            "prompt_context": prompt_context,
            "tools": tool_result.get("tools", []),
            "deep_thinking": bool(tool_result.get("deep_thinking", False)),
            "intent": str(tool_result.get("intent", "chat")),
            "orchestration_strategy": tool_result.get("orchestration_strategy", {}),
            "execution_mode": execution_mode,
        }

    async def build_prompt_context(
        self,
        context: dict[str, Any],
        intent_result: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        user_id = str(context.get("user_id", self.agent_id))
        task_category = str(intent_result.get("intent", "chat"))
        retrieved_memory_payload = {
            "short_term_workbench": [],
            "reflection_memory_l5": [],
            "preference_memory": {},
        }

        prompt_context = await self.prompt_context_assembler.assemble(
            agent_id=self.agent_id,
            agent_type=str(self.agent_type.value if hasattr(self.agent_type, "value") else self.agent_type),
            scenario=Scenario.CHAT,
            task_category=task_category,
            user_id=user_id,
            self_memory=self.memory,
            other_memory=self.other_memory,
            tool_result=tool_result,
            retrieved_memory_payload=retrieved_memory_payload,
            state_transition_override=None,
            persona_name=self.memory.personality_name if self.memory else "default",
        )
        return prompt_context

    async def call_llm(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        execution_mode = llm_params.get("execution_mode")
        if execution_mode == "fact_only":
            return {"response": "", "skip_emit": True}
        if execution_mode == "orchestration_launch":
            return await self._start_orchestration(context, llm_params)
        if execution_mode == "orchestration_update":
            return await self._process_worker_updates(context, llm_params)

        history = llm_params["history"]
        user_message = llm_params["user_message"]
        if not llm_params["tools"]:
            messages = history[-10:] + [{"role": "user", "content": user_message}]
            response_text = await self._call_llm(
                llm_params["system_prompt"],
                messages,
                disable_thinking=not llm_params["deep_thinking"],
            )
        else:
            execution_outcome = await self.function_calling_executor.execute_with_tools(
                user_message=user_message,
                system_prompt=llm_params["system_prompt"],
                selected_tools=llm_params["tools"],
                user_id=llm_params["user_id"],
                session_id=llm_params["session_id"],
                conversation_history=history,
                disable_thinking=not llm_params["deep_thinking"],
                intent=llm_params["intent"],
                execution_agent_id=str(context.get("runtime_key", "chat_agent")),
                orchestration_strategy=llm_params.get("orchestration_strategy"),
            )
            response_text = execution_outcome.content
            return {"response": response_text, "execution_outcome": execution_outcome.to_dict()}
        return {"response": response_text}

    async def parse_result(self, context: dict[str, Any], raw_result: Any) -> None:
        if self._action_executor is None:
            return
        if isinstance(raw_result, dict) and raw_result.get("skip_emit"):
            return
        latest_fact = context.get("latest_fact")
        if not isinstance(latest_fact, FactRecord):
            return
        if latest_fact.event_type != EventTypes.USER_MESSAGE and latest_fact.event_type not in WORKER_AGENT_EVENT_TYPES:
            return

        response_text = str(raw_result.get("response", "")) if isinstance(raw_result, dict) else str(raw_result)
        execution_outcome = raw_result.get("execution_outcome", {}) if isinstance(raw_result, dict) else {}
        if not response_text.strip() and isinstance(execution_outcome, dict) and execution_outcome.get("status") == "failed":
            failure_reason = str(execution_outcome.get("failure_reason") or "EXECUTION_ERROR")
            response_text = f"Execution failed: {failure_reason}"
        if not response_text.strip():
            return
        user_id = context["user_id"]
        session_id = context["session_id"]
        history_key = context["history_key"]
        history = self._conversation_history.setdefault(history_key, [])
        user_message = str(raw_result.get("root_user_message") or context.get("user_message") or "")
        if latest_fact.event_type == EventTypes.USER_MESSAGE and user_message:
            history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        if user_message:
            await self._record_memory_updates(user_id=user_id, user_message=user_message)

        correlation_id = (
            str(raw_result.get("correlation_id"))
            if isinstance(raw_result, dict) and raw_result.get("correlation_id")
            else latest_fact.correlation_id
        )

        await self._action_executor.emit_chat_response_event(
            user_id=user_id,
            session_id=session_id,
            response=response_text,
            correlation_id=correlation_id,
        )
        now = time.time()
        message_started_at = float(raw_result.get("message_started_at") or latest_fact.timestamp or now) if isinstance(raw_result, dict) else float(latest_fact.timestamp or now)
        response_time = max(0.0, now - message_started_at)
        action_payload = dict(latest_fact.payload) if isinstance(latest_fact.payload, dict) else {}
        action_payload.update(
            {
                "action_type": "ChatResponseAction",
                "response": response_text,
                "execution_time": response_time,
                "user_id": user_id,
                "session_id": session_id,
                "orchestration_id": raw_result.get("orchestration_id") if isinstance(raw_result, dict) else None,
            }
        )
        await self._action_executor.emit_action_event(
            fact=FactRecord(
                agent_id=latest_fact.agent_id,
                event_type=EventTypes.AI_RESPONSE if latest_fact.event_type in WORKER_AGENT_EVENT_TYPES else latest_fact.event_type,
                payload=action_payload,
                agent_type=latest_fact.agent_type,
                agent_instance_id=latest_fact.agent_instance_id,
                timestamp=latest_fact.timestamp,
                correlation_id=correlation_id,
            ),
            success=True,
            error=None,
        )

    async def _start_orchestration(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        user_id = str(llm_params.get("user_id") or context.get("user_id") or self.agent_id)
        session_id = str(llm_params.get("session_id") or context.get("session_id") or self._resolve_session_id(user_id))
        user_message = str(llm_params.get("user_message") or context.get("user_message") or "").strip()
        latest_fact = context.get("latest_fact")
        orchestration_strategy = llm_params.get("orchestration_strategy", {})
        plan_payload = await self._generate_subtask_plan(
            user_message=user_message,
            history=llm_params.get("history", []),
            orchestration_strategy=orchestration_strategy,
            user_id=user_id,
            session_id=session_id,
        )

        raw_subtasks = plan_payload.get("subtasks") if isinstance(plan_payload, dict) else []
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            raw_subtasks = self._fallback_subtask_plan(
                user_message=user_message,
                default_leaf_type=str(orchestration_strategy.get("default_leaf_type", "Explore")),
            )

        orchestration_id = f"orch_{uuid.uuid4().hex[:12]}"
        now = time.time()
        state = TaskOrchestrationState(
            orchestration_id=orchestration_id,
            user_id=user_id,
            session_id=session_id,
            root_user_message=user_message,
            planner=str(orchestration_strategy.get("planner", "task_agent") or "task_agent"),
            status="running",
            retry_budget=1,
            allow_parallel=bool(orchestration_strategy.get("allow_parallel", True)),
            created_at=now,
            updated_at=now,
            correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
            subtasks=[
                SubtaskDefinition(
                    subtask_id=f"subtask_{uuid.uuid4().hex[:10]}",
                    description=str(item.get("description", "")).strip(),
                    subagent_type=str(item.get("subagent_type", orchestration_strategy.get("default_leaf_type", "Explore"))).strip() or "Explore",
                    prompt=self._build_leaf_worker_prompt(
                        root_user_message=user_message,
                        subtask_description=str(item.get("description", "")).strip(),
                        subtask_prompt=str(item.get("prompt", "")).strip(),
                    ),
                    parallel_group=str(item.get("parallel_group", "default")).strip() or "default",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                for item in raw_subtasks
                if isinstance(item, dict) and str(item.get("description", "")).strip() and str(item.get("prompt", "")).strip()
            ],
        )
        if not state.subtasks:
            state.subtasks = [
                SubtaskDefinition(
                    subtask_id=f"subtask_{uuid.uuid4().hex[:10]}",
                    description=str(item.get("description", "")).strip(),
                    subagent_type=str(item.get("subagent_type", "Explore")).strip() or "Explore",
                    prompt=self._build_leaf_worker_prompt(
                        root_user_message=user_message,
                        subtask_description=str(item.get("description", "")).strip(),
                        subtask_prompt=str(item.get("prompt", "")).strip(),
                    ),
                    parallel_group=str(item.get("parallel_group", "default")).strip() or "default",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                for item in self._fallback_subtask_plan(
                    user_message=user_message,
                    default_leaf_type=str(orchestration_strategy.get("default_leaf_type", "Explore")),
                )
            ]

        await self._orchestration_store.save_orchestration(state)
        launch_error = await self._launch_orchestration_workers(state)
        if launch_error:
            state.status = "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            return {
                "response": f"Failed to launch worker subtasks: {launch_error}",
                "skip_emit": False,
                "root_user_message": user_message,
                "correlation_id": state.correlation_id,
                "orchestration_id": state.orchestration_id,
            }

        self._append_user_message_to_history(
            history_key=context["history_key"],
            user_message=user_message,
        )
        return {
            "response": "",
            "skip_emit": True,
            "orchestration_id": orchestration_id,
        }

    async def _process_worker_updates(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        batch_facts = llm_params.get("batch_facts", []) if isinstance(llm_params, dict) else []
        touched_states: dict[str, TaskOrchestrationState] = {}
        for fact in batch_facts:
            if not isinstance(fact, FactRecord) or fact.event_type not in WORKER_AGENT_EVENT_TYPES:
                continue
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            orchestration_id = str(payload.get("orchestration_id", "")).strip()
            subtask_id = str(payload.get("subtask_id", "")).strip()
            if not orchestration_id or not subtask_id:
                continue
            state = touched_states.get(orchestration_id)
            if state is None:
                state = await self._orchestration_store.get_orchestration(orchestration_id)
            if state is None or state.status in {"completed", "failed"}:
                continue
            subtask = state.get_subtask(subtask_id)
            if subtask is None:
                continue
            payload_worker_id = str(payload.get("worker_id", "")).strip()
            if payload_worker_id and subtask.worker_id and payload_worker_id != subtask.worker_id:
                continue

            now = time.time()
            if fact.event_type == "WORKER_AGENT_PROGRESS":
                if subtask.status == "pending":
                    subtask.status = "running"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            if fact.event_type == "WORKER_AGENT_COMPLETED":
                worker_result = payload.get("worker_result")
                if not isinstance(worker_result, dict) and payload_worker_id:
                    worker_result = await self._orchestration_store.get_worker_result(payload_worker_id)
                if not isinstance(worker_result, dict):
                    subtask.status = "failed"
                    subtask.failure_reason = "INVALID_WORKER_RESULT"
                    subtask.updated_at = now
                    state.updated_at = now
                    touched_states[state.orchestration_id] = state
                    continue
                subtask.worker_result = worker_result
                subtask.failure_reason = None
                subtask.status = "completed"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            failure_reason = str(
                payload.get("failure_reason")
                or payload.get("error")
                or "WORKER_FAILED"
            ).strip()
            retried = await self._maybe_retry_subtask(state, subtask, failure_reason)
            if not retried:
                subtask.status = "failed"
                subtask.failure_reason = failure_reason
            subtask.updated_at = now
            state.updated_at = now
            touched_states[state.orchestration_id] = state

        for state in touched_states.values():
            await self._orchestration_store.save_orchestration(state)

        completed_payloads: list[dict[str, Any]] = []
        for state in touched_states.values():
            if not self._is_orchestration_terminal(state):
                continue
            if state.status == "completed":
                continue
            state.status = "aggregating"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            final_response = await self._aggregate_orchestration(state)
            state.final_response = final_response
            state.status = "completed" if final_response.strip() else "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            if final_response.strip():
                completed_payloads.append(
                    {
                        "response": final_response,
                        "skip_emit": False,
                        "root_user_message": state.root_user_message,
                        "correlation_id": state.correlation_id,
                        "orchestration_id": state.orchestration_id,
                        "message_started_at": state.created_at,
                    }
                )

        if not completed_payloads:
            return {"response": "", "skip_emit": True}
        if len(completed_payloads) == 1:
            return completed_payloads[0]

        combined = "\n\n".join(
            item["response"]
            for item in completed_payloads
            if str(item.get("response", "")).strip()
        )
        first = completed_payloads[0]
        return {
            "response": combined,
            "skip_emit": False,
            "root_user_message": first.get("root_user_message"),
            "correlation_id": first.get("correlation_id"),
            "orchestration_id": ",".join(
                str(item.get("orchestration_id", ""))
                for item in completed_payloads
                if item.get("orchestration_id")
            ),
            "message_started_at": first.get("message_started_at"),
        }

    async def _generate_subtask_plan(
        self,
        user_message: str,
        history: list[dict[str, Any]],
        orchestration_strategy: dict[str, Any],
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        planner = str(orchestration_strategy.get("planner", "task_agent") or "task_agent")
        if planner == "plan_worker":
            plan_payload = await self._plan_with_plan_worker(
                user_message=user_message,
                user_id=user_id,
                session_id=session_id,
            )
            if plan_payload:
                return plan_payload
        plan_payload = await self._plan_with_task_agent(
            user_message=user_message,
            history=history,
            orchestration_strategy=orchestration_strategy,
        )
        if plan_payload:
            return plan_payload
        return {
            "summary": "Fallback decomposition generated by chat task agent.",
            "subtasks": self._fallback_subtask_plan(
                user_message=user_message,
                default_leaf_type=str(orchestration_strategy.get("default_leaf_type", "Explore")),
            ),
        }

    async def _plan_with_task_agent(
        self,
        user_message: str,
        history: list[dict[str, Any]],
        orchestration_strategy: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        recent_history = [
            {
                "role": str(item.get("role", "unknown")),
                "content": str(item.get("content", ""))[:400],
            }
            for item in history[-4:]
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ]
        planning_prompt = {
            "user_request": user_message,
            "recent_history": recent_history,
            "default_leaf_type": str(orchestration_strategy.get("default_leaf_type", "Explore")),
            "allow_parallel": bool(orchestration_strategy.get("allow_parallel", True)),
            "requirements": [
                "Decompose into bounded leaf subtasks owned by the parent task agent.",
                "Favor parallel subtasks when there are no strong dependencies.",
                "For codebase architecture analysis, prefer separate subtasks for directory structure, tech stack, frontend, backend, and project progress when relevant.",
            ],
        }
        system_prompt = (
            "You are a parent task agent planning bounded leaf subtasks. "
            "Return ONLY valid JSON with this schema: "
            '{"summary":"string","subtasks":[{"description":"string","subagent_type":"Explore|general-purpose","prompt":"string","parallel_group":"string"}]}. '
            "Do not answer the user request directly. Produce execution-ready leaf tasks only."
        )
        try:
            response = await self._call_llm(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": json.dumps(planning_prompt, ensure_ascii=False)}],
                disable_thinking=False,
            )
        except Exception as exc:
            logger.warning("Task-agent planning call failed | error=%s", exc)
            return None
        return self._parse_subtask_plan(response)

    async def _plan_with_plan_worker(
        self,
        user_message: str,
        user_id: str,
        session_id: str,
    ) -> Optional[dict[str, Any]]:
        context = self._build_agent_tool_context(user_id=user_id, session_id=session_id)
        result = await tool_registry.execute(
            "agent",
            {
                "action": "launch",
                "subagent_type": "Plan",
                "description": "plan leaf subtasks",
                "prompt": (
                    "Decompose the parent task into bounded leaf workers. "
                    "Return JSON with summary, findings, evidence, gaps, next_steps, and subtasks only. "
                    f"Parent task: {user_message}"
                ),
                "run_in_background": False,
                "target_task_agent_type": "chat",
                "target_task_agent_id": user_id,
                "parent_task_agent_type": "chat",
                "parent_task_agent_id": user_id,
            },
            context,
        )
        if not result.success or not isinstance(result.data, dict):
            return None
        payload = result.data.get("result")
        if not isinstance(payload, dict):
            return None
        subtasks = payload.get("subtasks")
        if not isinstance(subtasks, list) or not subtasks:
            return None
        return {
            "summary": str(payload.get("summary", "")).strip(),
            "subtasks": subtasks,
        }

    async def _launch_orchestration_workers(self, state: TaskOrchestrationState) -> Optional[str]:
        context = self._build_agent_tool_context(user_id=state.user_id, session_id=state.session_id)
        worker_payloads = []
        for subtask in state.subtasks:
            worker_payloads.append(
                {
                    "subagent_type": subtask.subagent_type,
                    "description": subtask.description,
                    "prompt": subtask.prompt,
                    "orchestration_id": state.orchestration_id,
                    "subtask_id": subtask.subtask_id,
                    "parent_task_agent_type": "chat",
                    "parent_task_agent_id": state.user_id,
                    "target_task_agent_type": "chat",
                    "target_task_agent_id": state.user_id,
                    "retry_count": max(subtask.attempt_count, 0),
                }
            )
        result = await tool_registry.execute(
            "agent",
            {
                "action": "launch",
                "workers": worker_payloads,
                "parallel": state.allow_parallel,
                "run_in_background": True,
                "target_task_agent_type": "chat",
                "target_task_agent_id": state.user_id,
            },
            context,
        )
        if not result.success or not isinstance(result.data, dict):
            return str(result.error or "Unknown worker launch error")
        worker_ids = result.data.get("worker_ids")
        if not isinstance(worker_ids, list) or len(worker_ids) != len(state.subtasks):
            return "Worker launch did not return a complete worker id list"
        now = time.time()
        for subtask, worker_id in zip(state.subtasks, worker_ids):
            subtask.worker_id = str(worker_id)
            subtask.status = "running"
            subtask.attempt_count = max(subtask.attempt_count, 1)
            subtask.updated_at = now
        state.updated_at = now
        await self._orchestration_store.save_orchestration(state)
        return None

    async def _maybe_retry_subtask(
        self,
        state: TaskOrchestrationState,
        subtask: SubtaskDefinition,
        failure_reason: str,
    ) -> bool:
        if failure_reason not in RETRIABLE_WORKER_FAILURES:
            return False
        if subtask.attempt_count > state.retry_budget:
            return False
        context = self._build_agent_tool_context(user_id=state.user_id, session_id=state.session_id)
        next_attempt = subtask.attempt_count + 1
        result = await tool_registry.execute(
            "agent",
            {
                "action": "launch",
                "subagent_type": subtask.subagent_type,
                "description": subtask.description,
                "prompt": subtask.prompt,
                "run_in_background": True,
                "orchestration_id": state.orchestration_id,
                "subtask_id": subtask.subtask_id,
                "parent_task_agent_type": "chat",
                "parent_task_agent_id": state.user_id,
                "target_task_agent_type": "chat",
                "target_task_agent_id": state.user_id,
                "retry_count": next_attempt - 1,
            },
            context,
        )
        if not result.success or not isinstance(result.data, dict):
            logger.warning(
                "Failed to relaunch worker for retry | orchestration_id=%s subtask_id=%s error=%s",
                state.orchestration_id,
                subtask.subtask_id,
                result.error,
            )
            return False
        worker_id = str(result.data.get("worker_id", "")).strip()
        if not worker_id:
            return False
        subtask.worker_id = worker_id
        subtask.status = "running"
        subtask.failure_reason = None
        subtask.worker_result = None
        subtask.attempt_count = next_attempt
        subtask.updated_at = time.time()
        state.updated_at = subtask.updated_at
        await self._orchestration_store.save_orchestration(state)
        return True

    async def _aggregate_orchestration(self, state: TaskOrchestrationState) -> str:
        payload = {
            "user_request": state.root_user_message,
            "planner": state.planner,
            "completed_subtasks": [
                {
                    "subtask_id": item.subtask_id,
                    "description": item.description,
                    "result": item.worker_result,
                }
                for item in state.subtasks
                if item.status == "completed" and isinstance(item.worker_result, dict)
            ],
            "failed_subtasks": [
                {
                    "subtask_id": item.subtask_id,
                    "description": item.description,
                    "failure_reason": item.failure_reason,
                    "attempt_count": item.attempt_count,
                }
                for item in state.subtasks
                if item.status == "failed"
            ],
        }
        system_prompt = (
            "You are the parent task agent for a decomposed task. "
            "Synthesize a final response from completed leaf worker results. "
            "Use only the provided worker outputs, mention concrete evidence when available, "
            "and explicitly call out gaps caused by failed subtasks. "
            "Do not mention internal implementation details like orchestration ids."
        )
        try:
            response = await self._call_llm(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                disable_thinking=False,
            )
        except Exception as exc:
            logger.warning("Parent aggregation LLM call failed | orchestration_id=%s error=%s", state.orchestration_id, exc)
            response = ""
        if response.strip():
            return response.strip()
        return self._build_aggregation_fallback(state)

    def _parse_subtask_plan(self, response: str) -> Optional[dict[str, Any]]:
        raw = str(response or "").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        subtasks = payload.get("subtasks")
        if not isinstance(subtasks, list) or not subtasks:
            return None
        normalized = []
        for item in subtasks:
            if not isinstance(item, dict):
                continue
            normalized_item = {
                "description": str(item.get("description", "")).strip(),
                "subagent_type": str(item.get("subagent_type", "Explore")).strip() or "Explore",
                "prompt": str(item.get("prompt", "")).strip(),
                "parallel_group": str(item.get("parallel_group", "default")).strip() or "default",
            }
            if not normalized_item["description"] or not normalized_item["prompt"]:
                continue
            normalized.append(normalized_item)
        if not normalized:
            return None
        return {
            "summary": str(payload.get("summary", "")).strip(),
            "subtasks": normalized,
        }

    def _fallback_subtask_plan(self, user_message: str, default_leaf_type: str) -> list[dict[str, Any]]:
        is_repo_architecture = any(
            keyword in user_message.lower()
            for keyword in ["architecture", "codebase", "repo", "代码架构", "项目架构", "代码库", "目录结构"]
        )
        leaf_type = default_leaf_type if default_leaf_type in {"Explore", "general-purpose"} else "Explore"
        if is_repo_architecture:
            return [
                {
                    "description": "Map repository layout",
                    "subagent_type": "Explore",
                    "prompt": "Analyze the top-level directory structure, major modules, and entry folders.",
                    "parallel_group": "group_a",
                },
                {
                    "description": "Identify technology stack",
                    "subagent_type": "Explore",
                    "prompt": "Inspect dependency manifests and boot files to identify the backend, frontend, storage, and runtime stack.",
                    "parallel_group": "group_a",
                },
                {
                    "description": "Analyze frontend structure",
                    "subagent_type": "Explore",
                    "prompt": "Focus on frontend organization, bootstrap flow, routing, and the main UI entry points.",
                    "parallel_group": "group_a",
                },
                {
                    "description": "Analyze backend modules",
                    "subagent_type": "Explore",
                    "prompt": "Focus on backend module boundaries, runtime startup, task agent chain, and the main execution flow.",
                    "parallel_group": "group_a",
                },
                {
                    "description": "Inspect project progress",
                    "subagent_type": "Explore",
                    "prompt": "Look for docs, progress trackers, release notes, or TODO-style files that indicate the current project status and recent progress.",
                    "parallel_group": "group_a",
                },
            ]
        return [
            {
                "description": "Gather primary context",
                "subagent_type": leaf_type,
                "prompt": "Collect the most relevant files, modules, and source-of-truth evidence for the request.",
                "parallel_group": "group_a",
            },
            {
                "description": "Analyze implementation details",
                "subagent_type": leaf_type,
                "prompt": "Inspect the core implementation path, dependencies, and behavior that matter for the request.",
                "parallel_group": "group_a",
            },
            {
                "description": "Summarize risks and gaps",
                "subagent_type": leaf_type,
                "prompt": "Identify open questions, gaps, and next actions needed to complete the request.",
                "parallel_group": "group_b",
            },
        ]

    def _build_leaf_worker_prompt(
        self,
        root_user_message: str,
        subtask_description: str,
        subtask_prompt: str,
    ) -> str:
        return "\n".join(
            [
                f"Parent user request: {root_user_message}",
                f"Assigned subtask: {subtask_description}",
                "Task-specific instructions:",
                subtask_prompt,
                "Success criteria:",
                "- Stay strictly within this subtask scope.",
                "- Use absolute file paths in findings and evidence when you reference code.",
                "- Prefer validated findings over speculation.",
                "- If information is missing, put it into gaps instead of guessing.",
                "- Do not duplicate likely sibling subtasks unless it is necessary evidence.",
            ]
        )

    def _build_agent_tool_context(self, user_id: str, session_id: str) -> ToolExecutionContext:
        return ToolExecutionContext(
            agent_id=self.runtime_key,
            workspace=os.getcwd(),
            env_vars={
                "user_id": user_id,
                "session_id": session_id,
                "target_task_agent_type": "chat",
                "target_task_agent_id": user_id,
                "parent_task_agent_type": "chat",
                "parent_task_agent_id": user_id,
            },
            permissions=["authenticated"],
        )

    def _is_orchestration_terminal(self, state: TaskOrchestrationState) -> bool:
        if not state.subtasks:
            return False
        return all(item.status in {"completed", "failed"} for item in state.subtasks)

    def _build_aggregation_fallback(self, state: TaskOrchestrationState) -> str:
        lines = [f"Request: {state.root_user_message}", ""]
        completed = [item for item in state.subtasks if item.status == "completed" and isinstance(item.worker_result, dict)]
        failed = [item for item in state.subtasks if item.status == "failed"]
        if completed:
            lines.append("Completed subtasks:")
            for item in completed:
                summary = str(item.worker_result.get("summary", "")).strip()
                lines.append(f"- {item.description}: {summary or 'Completed with structured findings.'}")
        if failed:
            lines.append("")
            lines.append("Gaps / failed subtasks:")
            for item in failed:
                lines.append(f"- {item.description}: {item.failure_reason or 'Unknown failure'}")
        return "\n".join(lines).strip()

    def _append_user_message_to_history(self, history_key: str, user_message: str) -> None:
        if not user_message:
            return
        history = self._conversation_history.setdefault(history_key, [])
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            return
        history.append({"role": "user", "content": user_message})

    async def _record_memory_updates(self, user_id: str, user_message: str) -> None:
        if self.memory is not None:
            try:
                await self.memory.record_interaction(
                    user_id=user_id,
                    interaction_type=InteractionType.CHAT,
                    outcome="success",
                    sentiment=0.0,
                    notes=f"Message: {user_message[:100]}...",
                )
                await self.memory.update_after_interaction(
                    outcome=InteractionOutcome.SUCCESS,
                    user_engagement=EngagementLevel.MEDIUM,
                    complexity=0.5,
                )
                await self.memory.record_task_outcome(
                    task_id=f"chat_{int(time.time())}_{user_id}",
                    task_category="chat",
                    user_satisfaction=SatisfactionLevel.NEUTRAL,
                    accepted=True,
                    task_complexity=0.5,
                    task_duration=0.0,
                )
            except Exception as exc:
                logger.warning(f"Failed to update self memory: {exc}")
        if self.other_memory is not None:
            try:
                self.other_memory.update_interaction(
                    user_id=user_id,
                    interaction_type="chat",
                    outcome="positive",
                    notes=f"Message: {user_message[:100]}",
                )
            except Exception as exc:
                logger.warning(f"Failed to update other memory: {exc}")

    async def _build_system_prompt(
        self,
        scenario: str = Scenario.CHAT,
        user_id: str | None = None,
        task_category: str = "chat",
    ) -> str:
        prompt_context = await self.prompt_context_assembler.assemble(
            agent_id=self.agent_id,
            agent_type=str(self.agent_type.value if hasattr(self.agent_type, "value") else self.agent_type),
            scenario=scenario,
            task_category=task_category,
            user_id=str(user_id or self.agent_id),
            self_memory=self.memory,
            other_memory=self.other_memory,
            tool_result={"tools": []},
            retrieved_memory_payload={},
            state_transition_override=None,
        )
        return self.prompt_context_renderer.render_system_prompt(prompt_context)

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
    ) -> str:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        model_name = self.llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
        )

        try:
            provider_bridge = LLMProviderBridge(self.llm)
            response = await provider_bridge.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=1000,
                temperature=0.7,
                disable_thinking=disable_thinking,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response,
                success=True,
                duration_ms=duration_ms,
            )
            return response

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise

    async def _record_tool_interaction(self, payload: dict[str, Any]) -> None:
        user_id = str(payload.get("user_id") or self.agent_id)
        session_id = self._resolve_session_id(user_id, payload.get("session_id"))
        history_key = self._history_key(user_id, session_id)
        records = self._tool_interactions.setdefault(history_key, [])
        tool_name = str(payload.get("tool_name") or "unknown")
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        execution_time = float(payload.get("execution_time") or 0.0)
        success = bool(payload.get("success"))
        error_text = str(payload.get("error") or "") or None
        records.append(
            {
                "timestamp": time.time(),
                "intent": payload.get("intent") or "unknown",
                "tool_name": tool_name,
                "status": "success" if success else "error",
                "error_code": str(payload.get("error_code") or ""),
                "error_message": str(payload.get("error") or ""),
                "result_summary": str(payload.get("data") or ""),
            }
        )
        if len(records) > 100:
            self._tool_interactions[history_key] = records[-100:]

        if self._action_executor is None:
            return

        await self._action_executor.emit_action_event(
            fact=FactRecord(
                agent_id=self.agent_id,
                event_type=TOOL_INTERACTION_EVENT_TYPE,
                payload={
                    "action_type": tool_name,
                    "tool_name": tool_name,
                    "params": arguments,
                    "arguments": arguments,
                    "execution_time": execution_time,
                    "user_id": user_id,
                    "session_id": session_id,
                },
                correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
            ),
            success=success,
            error=error_text,
        )

    async def _record_tool_loop_fact(self, payload: dict[str, Any]) -> None:
        """Persist function-calling loop stages as chat facts."""
        user_id = str(payload.get("user_id") or self.agent_id)
        session_id = self._resolve_session_id(user_id, payload.get("session_id"))
        stage = str(payload.get("stage") or "unknown")

        fact = FactRecord(
            agent_id=f"{TaskAgentType.CHAT.value}:{user_id}",
            event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
            payload={
                "stage": stage,
                "iteration": payload.get("iteration"),
                "max_iterations": payload.get("max_iterations"),
                "tool_name": payload.get("tool_name"),
                "tool_names": payload.get("tool_names"),
                "tool_count": payload.get("tool_count"),
                "tool_call_id": payload.get("tool_call_id"),
                "success": payload.get("success"),
                "error": payload.get("error"),
                "execution_time": payload.get("execution_time"),
                "response_preview": payload.get("response_preview"),
                "intent": payload.get("intent"),
                "execution_agent_id": payload.get("execution_agent_id"),
                "user_id": user_id,
                "session_id": session_id,
                "timestamp": time.time(),
            },
            agent_type=TaskAgentType.CHAT.value,
            agent_instance_id=user_id,
            timestamp=time.time(),
            correlation_id=str(payload.get("tool_call_id") or str(uuid.uuid4())),
        )

        try:
            from ...runtime import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
            await manager.add_fact_to_agent(TaskAgentType.CHAT, user_id, fact)
        except Exception as exc:
            logger.debug(f"Failed to append loop stage fact via runtime manager: {exc}")
            self._fact_memory.append(fact)
            if len(self._fact_memory) > self._max_fact_memory:
                self._fact_memory = self._fact_memory[-self._max_fact_memory :]

    def _history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def _resolve_session_id(self, user_id: str, session_id: Optional[str] = None) -> str:
        if session_id:
            self._current_session_by_user[user_id] = session_id
            self._save_session_state()
            return session_id
        existing = self._current_session_by_user.get(user_id)
        if existing:
            return existing
        new_id = str(uuid.uuid4())
        self._current_session_by_user[user_id] = new_id
        self._save_session_state()
        return new_id

    def get_current_session_id(self, user_id: str) -> str:
        return self._resolve_session_id(user_id)

    def create_new_session(self, user_id: str) -> str:
        new_id = str(uuid.uuid4())
        self._current_session_by_user[user_id] = new_id
        self._conversation_history.setdefault(self._history_key(user_id, new_id), [])
        self._tool_interactions.setdefault(self._history_key(user_id, new_id), [])
        self._save_session_state()
        return new_id

    def get_conversation_history(self, user_id: str, session_id: Optional[str] = None) -> list[dict]:
        active_session = self._resolve_session_id(user_id, session_id)
        return self._conversation_history.get(self._history_key(user_id, active_session), [])

    def clear_conversation_history(self, user_id: str, session_id: Optional[str] = None) -> None:
        active_session = self._resolve_session_id(user_id, session_id)
        key = self._history_key(user_id, active_session)
        self._conversation_history[key] = []
        self._tool_interactions[key] = []

    def _load_session_state(self) -> None:
        try:
            if self._session_state_file.exists():
                data = json.loads(self._session_state_file.read_text(encoding="utf-8"))
                mapping = data.get("current_session_by_user", {}) if isinstance(data, dict) else {}
                if isinstance(mapping, dict):
                    self._current_session_by_user = {str(k): str(v) for k, v in mapping.items() if k and v}
        except Exception as exc:
            logger.warning(f"Failed to load session state: {exc}")

    def _save_session_state(self) -> None:
        try:
            payload = {"current_session_by_user": self._current_session_by_user}
            self._session_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._session_state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to save session state: {exc}")

    def _restore_conversation_from_events(self) -> None:
        try:
            if not self._events_db_path.exists():
                return
            conn = sqlite3.connect(str(self._events_db_path))
            cur = conn.cursor()
            cur.execute(
                """
                SELECT type, data
                FROM event_store
                WHERE type IN ('USER_INPUT', 'AI_RESPONSE', ?)
                ORDER BY timestamp ASC
                LIMIT 5000
                """,
                (TOOL_INTERACTION_EVENT_TYPE,),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning(f"Failed to restore conversation from event store: {exc}")
            return

        for event_type, raw_data in rows:
            try:
                payload = json.loads(raw_data or "{}")
            except Exception:
                continue
            user_id = payload.get("user_id")
            if not user_id:
                continue
            session_id = self._resolve_session_id(user_id, payload.get("session_id"))
            key = self._history_key(user_id, session_id)
            history = self._conversation_history.setdefault(key, [])
            if event_type == "USER_INPUT":
                content = payload.get("message", "")
                if content:
                    history.append({"role": "user", "content": str(content)})
            elif event_type == "AI_RESPONSE":
                content = payload.get("response", "")
                if content:
                    history.append({"role": "assistant", "content": str(content)})
