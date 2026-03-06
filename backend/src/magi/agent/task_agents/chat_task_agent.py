"""
Runtime task agent for chat facts.
"""
from __future__ import annotations

import json
import platform
import sqlite3
import time
import uuid
from typing import Any, Optional

from ...agent.orchestration import TaskOrchestrationState, get_orchestration_store
from ...agent.task_orchestrator import TaskOrchestrator
from .explore_task_agent import (
    EXPLORE_TASK_COMPLETED,
    EXPLORE_TASK_REQUEST,
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
CHAT_INTERNAL_EVENT_TYPES = WORKER_AGENT_EVENT_TYPES | {EXPLORE_TASK_COMPLETED}


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
        self._task_orchestrator = TaskOrchestrator(
            runtime_key=self.runtime_key,
            tool_registry=tool_registry,
            plan_subtasks=self._generate_subtask_plan,
            aggregate_orchestration=self._aggregate_orchestration,
            register_user_message=self._append_user_message_to_history,
            parent_task_agent_type=TaskAgentType.CHAT.value,
        )
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
        user_message = str(payload.get("message") or payload.get("root_user_message") or "").strip()
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
        explore_batch = [
            fact
            for fact in batch_facts
            if isinstance(fact, FactRecord) and fact.event_type == EXPLORE_TASK_COMPLETED
        ]
        if explore_batch:
            return {
                "intent": "explore_task_completed",
                "difficulty": "normal",
                "execution_mode": "explore_task_result",
                "tools": [],
                "deep_thinking": False,
                "reasoning": "ExploreTaskAgent produced a Markdown dossier that must be rendered back to the user.",
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
            "tools": [] if execution_mode in {"orchestration_launch", "orchestration_update", "fact_only", "explore_task_result"} else intent_result.get("tools", []),
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
        if execution_mode in {"fact_only", "orchestration_launch", "orchestration_update", "explore_task_result"}:
            return {
                "user_id": user_id,
                "session_id": session_id,
                "user_message": user_message,
                "history": history,
                "batch_facts": context.get("batch_facts", []),
                "orchestration_strategy": tool_result.get("orchestration_strategy", {}),
                "execution_mode": execution_mode,
                "markdown_dossier": payload_or_none(context.get("latest_fact"), "markdown_dossier"),
                "root_user_message": payload_or_none(context.get("latest_fact"), "root_user_message") or user_message,
                "message_started_at": payload_or_none(context.get("latest_fact"), "message_started_at"),
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
        if execution_mode == "explore_task_result":
            return await self._render_explore_task_result(context, llm_params)

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
        if latest_fact.event_type != EventTypes.USER_MESSAGE and latest_fact.event_type not in CHAT_INTERNAL_EVENT_TYPES:
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
        orchestration_strategy = llm_params.get("orchestration_strategy", {})
        if self._should_route_to_explore_task_agent(
            user_message=str(llm_params.get("user_message") or context.get("user_message") or "").strip(),
            orchestration_strategy=orchestration_strategy,
        ):
            return await self._start_explore_task_agent(context, llm_params)
        latest_fact = context.get("latest_fact")
        return await self._task_orchestrator.start_orchestration(
            user_id=str(llm_params.get("user_id") or context.get("user_id") or self.agent_id),
            session_id=str(llm_params.get("session_id") or context.get("session_id") or ""),
            user_message=str(llm_params.get("user_message") or context.get("user_message") or "").strip(),
            history=llm_params.get("history", []),
            history_key=str(context.get("history_key", "")),
            correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
            orchestration_strategy=orchestration_strategy,
        )

    async def _process_worker_updates(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        _ = context
        return await self._task_orchestrator.process_worker_updates(
            llm_params.get("batch_facts", []) if isinstance(llm_params, dict) else []
        )

    async def _start_explore_task_agent(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        latest_fact = context.get("latest_fact")
        user_id = str(llm_params.get("user_id") or context.get("user_id") or self.agent_id)
        session_id = str(llm_params.get("session_id") or context.get("session_id") or "")
        user_message = str(llm_params.get("user_message") or context.get("user_message") or "").strip()
        history = self._filter_history_for_aggregation(llm_params.get("history", []))
        fact = FactRecord(
            agent_id=f"{TaskAgentType.EXPLORE.value}:{user_id}",
            event_type=EXPLORE_TASK_REQUEST,
            payload={
                "message": user_message,
                "user_id": user_id,
                "session_id": session_id,
                "history_snapshot": history,
                "upstream_task_agent_type": TaskAgentType.CHAT.value,
                "upstream_task_agent_id": user_id,
            },
            agent_type=TaskAgentType.EXPLORE.value,
            agent_instance_id=user_id,
            timestamp=time.time(),
            correlation_id=latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
        )
        try:
            from ...runtime import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
            enqueued = await manager.add_fact_to_agent(TaskAgentType.EXPLORE, user_id, fact)
        except Exception as exc:
            logger.warning("Failed to route request to ExploreTaskAgent | user_id=%s error=%s", user_id, exc)
            enqueued = False
        if not enqueued:
            return {
                "response": "Failed to start Explore task decomposition for this request.",
                "skip_emit": False,
                "root_user_message": user_message,
                "correlation_id": fact.correlation_id,
            }
        self._append_user_message_to_history(str(context.get("history_key", "")), user_message)
        return {
            "response": "",
            "skip_emit": True,
        }

    async def _render_explore_task_result(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
        dossier = str(llm_params.get("markdown_dossier") or "").strip()
        root_user_message = str(llm_params.get("root_user_message") or context.get("user_message") or "").strip()
        latest_fact = context.get("latest_fact")
        orchestration_id = None
        if isinstance(latest_fact, FactRecord) and isinstance(latest_fact.payload, dict):
            orchestration_id = latest_fact.payload.get("orchestration_id")
        if not dossier:
            return {
                "response": self._build_explore_render_fallback(root_user_message),
                "root_user_message": root_user_message,
                "correlation_id": latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
                "orchestration_id": orchestration_id,
                "message_started_at": llm_params.get("message_started_at"),
            }

        history = llm_params.get("history", [])
        filtered_history = self._filter_history_for_aggregation(history)
        system_prompt = await self._build_system_prompt(
            scenario=Scenario.ANALYSIS,
            user_id=str(llm_params.get("user_id") or context.get("user_id") or self.agent_id),
            task_category="analysis",
        )
        messages = filtered_history + [
            {
                "role": "user",
                "content": self._build_explore_render_message(root_user_message, dossier),
            }
        ]
        try:
            response = await self._call_llm(
                system_prompt=system_prompt,
                messages=messages,
                disable_thinking=False,
            )
        except Exception as exc:
            logger.warning("Explore dossier rendering failed | orchestration_id=%s error=%s", orchestration_id, exc)
            response = ""
        if not response.strip():
            logger.warning(
                "Explore dossier rendering returned empty response | orchestration_id=%s dossier_preview=%s",
                orchestration_id,
                dossier[:300],
            )
            response = self._build_explore_render_fallback(root_user_message, dossier)
        return {
            "response": response.strip(),
            "root_user_message": root_user_message,
            "correlation_id": latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None,
            "orchestration_id": orchestration_id,
            "message_started_at": llm_params.get("message_started_at"),
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
        raw_plan: Optional[dict[str, Any]] = None
        if planner == "plan_worker":
            raw_plan = await self._plan_with_plan_worker(
                user_message=user_message,
                user_id=user_id,
                session_id=session_id,
            )
        if raw_plan is None:
            raw_plan = await self._plan_with_task_agent(
                user_message=user_message,
                history=history,
                orchestration_strategy=orchestration_strategy,
            )
        if raw_plan is None:
            raw_plan = {
                "summary": "Fallback decomposition generated by chat task agent.",
                "subtasks": self._fallback_subtask_plan(
                    user_message=user_message,
                    default_leaf_type=str(orchestration_strategy.get("default_leaf_type", "Explore")),
                ),
            }
        return self._normalize_subtask_plan(
            user_message=user_message,
            raw_plan=raw_plan,
            default_leaf_type=str(orchestration_strategy.get("default_leaf_type", "Explore")),
        )

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
        if not str(response or "").strip():
            logger.warning(
                "Task-agent planning returned empty response | user_id=%s request_preview=%s",
                self.agent_id,
                user_message[:120],
            )
            return None

        parsed_plan = self._parse_subtask_plan(response)
        if parsed_plan is None:
            logger.warning(
                "Task-agent planning returned non-executable plan | request_preview=%s response_preview=%s",
                user_message[:120],
                str(response).strip()[:300],
            )
        return parsed_plan

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

    async def _aggregate_orchestration(self, state: TaskOrchestrationState) -> str:
        payload = self._build_aggregation_payload(state)
        history_key = self._history_key(state.user_id, state.session_id)
        history = await self._get_or_load_history(state.user_id, state.session_id, history_key)
        filtered_history = self._filter_history_for_aggregation(history)
        system_prompt = await self._build_system_prompt(
            user_id=state.user_id,
            task_category="chat",
        )
        messages = filtered_history + [
            {
                "role": "user",
                "content": self._build_aggregation_user_message(state, payload),
            }
        ]
        try:
            response = await self._call_llm(
                system_prompt=system_prompt,
                messages=messages,
                disable_thinking=False,
            )
        except Exception as exc:
            logger.warning("Parent aggregation LLM call failed | orchestration_id=%s error=%s", state.orchestration_id, exc)
            response = ""
        if response.strip():
            return response.strip()
        logger.warning(
            "Parent aggregation returned empty response | orchestration_id=%s completed_subtasks=%s failed_subtasks=%s",
            state.orchestration_id,
            len(payload.get("completed_subtasks", [])),
            len(payload.get("failed_subtasks", [])),
        )
        return self._build_aggregation_fallback(state)

    def _normalize_subtask_plan(
        self,
        user_message: str,
        raw_plan: dict[str, Any],
        default_leaf_type: str,
    ) -> dict[str, Any]:
        raw_subtasks = raw_plan.get("subtasks")
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            raw_subtasks = self._fallback_subtask_plan(user_message, default_leaf_type)
        normalized_subtasks: list[dict[str, Any]] = []
        for item in raw_subtasks:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description", "")).strip()
            subtask_prompt = str(item.get("prompt", "")).strip()
            if not description or not subtask_prompt:
                continue
            subagent_type = str(item.get("subagent_type", default_leaf_type)).strip()
            if subagent_type not in {"Explore", "general-purpose"}:
                subagent_type = "Explore"
            normalized_subtasks.append(
                {
                    "description": description,
                    "subagent_type": subagent_type,
                    "prompt": self._build_leaf_worker_prompt(
                        root_user_message=user_message,
                        subtask_description=description,
                        subtask_prompt=subtask_prompt,
                    ),
                    "parallel_group": str(item.get("parallel_group", "default")).strip() or "default",
                }
            )
        return {
            "summary": str(raw_plan.get("summary", "")).strip(),
            "subtasks": normalized_subtasks,
        }

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

    def _build_agent_tool_context(self, user_id: str, session_id: str):
        return self._task_orchestrator._build_agent_tool_context(user_id, session_id)

    def _build_aggregation_payload(self, state: TaskOrchestrationState) -> dict[str, Any]:
        return {
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

    def _filter_history_for_aggregation(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        filtered: list[dict[str, str]] = []
        for item in history[-8:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            if content.startswith("[Worker:"):
                continue
            filtered.append({"role": role, "content": content})
        return filtered

    def _build_aggregation_user_message(
        self,
        state: TaskOrchestrationState,
        payload: dict[str, Any],
    ) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False)
        if self._prefers_chinese_response(state.root_user_message):
            return "\n".join(
                [
                    f"用户原始请求：{state.root_user_message}",
                    "你已经拿到了内部子任务的结构化结果。现在请直接面向用户回答原始请求。",
                    "要求：",
                    "- 使用自然、正常的聊天语气，不要暴露子任务、worker、编排、JSON 或内部流程。",
                    "- 优先整合已经确认的信息，并在合适的时候引用关键文件路径作为依据。",
                    "- 对失败的部分，只需要简短说明哪些方面还没完全确认，不要把失败列表原样抄给用户。",
                    "- 如果已有信息不足以完整覆盖原问题，就先给出当前最可靠的结论，再明确缺口。",
                    "- 回复语言跟随用户。",
                    "",
                    f"内部结果(JSON): {payload_json}",
                ]
            )
        return "\n".join(
            [
                f"Original user request: {state.root_user_message}",
                "You already have the structured results from internal leaf tasks. Now answer the original request directly to the user.",
                "Requirements:",
                "- Respond in a natural conversational style and do not mention subtasks, workers, orchestration, JSON, or internal process details.",
                "- Prioritize confirmed information and cite key file paths naturally when they matter.",
                "- For failed areas, briefly mention what remains unconfirmed instead of dumping an internal failure list.",
                "- If the available evidence is incomplete, give the most reliable current conclusion first and then call out the remaining gaps.",
                "- Mirror the user's language.",
                "",
                f"Internal results (JSON): {payload_json}",
            ]
        )

    def _build_explore_render_message(self, root_user_message: str, dossier: str) -> str:
        if self._prefers_chinese_response(root_user_message):
            return "\n".join(
                [
                    f"用户原始请求：{root_user_message}",
                    "下面是一份已经整理好的探索报告，请直接面向用户给出最终回答。",
                    "要求：",
                    "- 使用自然、正常的聊天语气，但允许多段或简短的小标题来提升清晰度。",
                    "- 以已经确认的信息为主，必要时自然引用关键文件路径。",
                    "- 对尚未确认的部分，简短说明边界和缺口，不要暴露内部流程。",
                    "",
                    dossier,
                ]
            )
        return "\n".join(
            [
                f"Original user request: {root_user_message}",
                "Below is a prepared exploration dossier. Answer the user directly based on it.",
                "Requirements:",
                "- Use a natural conversational tone, but you may use multiple paragraphs or short headings when clarity improves.",
                "- Lead with confirmed findings and cite important file paths naturally when they matter.",
                "- Briefly call out remaining gaps without exposing internal process details.",
                "",
                dossier,
            ]
        )

    def _build_explore_render_fallback(self, root_user_message: str, dossier: str = "") -> str:
        if dossier.strip():
            return dossier.strip()
        if self._prefers_chinese_response(root_user_message):
            return "这次探索报告已经完成，但最终整理回答时没有拿到可用文本结果。"
        return "The exploration dossier completed, but the final rendering step did not return usable text."

    def _should_route_to_explore_task_agent(
        self,
        *,
        user_message: str,
        orchestration_strategy: dict[str, Any],
    ) -> bool:
        if str(orchestration_strategy.get("mode", "")).strip() != "decompose":
            return False
        if str(orchestration_strategy.get("default_leaf_type", "")).strip() != "Explore":
            return False
        lowered = user_message.lower()
        return any(
            keyword in lowered
            for keyword in [
                "architecture",
                "codebase",
                "repo",
                "跨模块",
                "跨子系统",
                "代码架构",
                "项目架构",
                "代码库",
                "目录结构",
            ]
        )

    def _prefers_chinese_response(self, text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _build_aggregation_fallback(self, state: TaskOrchestrationState) -> str:
        completed = [item for item in state.subtasks if item.status == "completed" and isinstance(item.worker_result, dict)]
        failed = [item for item in state.subtasks if item.status == "failed"]
        if self._prefers_chinese_response(state.root_user_message):
            lines = ["我先基于目前已经确认的结果给你一个可用的结论。", ""]
            if completed:
                lines.append("目前已经确认的部分：")
                for item in completed:
                    summary = str(item.worker_result.get("summary", "")).strip()
                    if summary:
                        lines.append(f"- {summary}")
            if failed:
                lines.append("")
                lines.append("还有几部分这次没有成功完成，所以相关信息暂时不能完全确认：")
                for item in failed:
                    lines.append(f"- {item.description}")
            return "\n".join(lines).strip()

        lines = ["Here is the most reliable answer I can give based on the completed analysis so far.", ""]
        completed = [item for item in state.subtasks if item.status == "completed" and isinstance(item.worker_result, dict)]
        if completed:
            lines.append("Confirmed so far:")
            for item in completed:
                summary = str(item.worker_result.get("summary", "")).strip()
                lines.append(f"- {summary or 'Completed with structured findings.'}")
        if failed:
            lines.append("")
            lines.append("These areas are still not fully confirmed because the underlying worker run failed:")
            for item in failed:
                lines.append(f"- {item.description}")
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
            provider_response = await provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=1000,
                temperature=0.7,
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
                    "LLM returned empty content | request_id=%s model=%s disable_thinking=%s metadata=%s",
                    request_id,
                    model_name,
                    disable_thinking,
                    provider_response.metadata,
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


def payload_or_none(fact: Any, key: str) -> Any:
    if not isinstance(fact, FactRecord) or not isinstance(fact.payload, dict):
        return None
    return fact.payload.get(key)
