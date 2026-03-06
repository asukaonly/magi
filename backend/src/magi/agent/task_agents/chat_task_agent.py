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
        runtime_paths = get_runtime_paths()
        self._session_state_file = runtime_paths.data_dir / "chat_sessions.json"
        self._events_db_path = runtime_paths.events_db_path
        self._load_session_state()
        # Note: Removed _restore_conversation_from_events() - now using lazy loading in build_context

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def build_context(self, merged_facts: list[FactRecord]) -> dict[str, Any]:
        context = await super().build_context(merged_facts)
        latest_fact = context.get("latest_fact")
        payload = latest_fact.payload if isinstance(latest_fact, FactRecord) else {}
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
            }
        )
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
        latest_fact = context.get("latest_fact")
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type in WORKER_AGENT_EVENT_TYPES:
            return {
                "intent": "worker_fact",
                "difficulty": "normal",
                "execution_mode": "fact_only",
                "tools": [],
                "deep_thinking": False,
                "reasoning": "Worker fact update does not require immediate LLM response",
            }
        if isinstance(latest_fact, FactRecord) and latest_fact.event_type != EventTypes.USER_MESSAGE:
            return {
                "intent": "non_user_fact",
                "difficulty": "normal",
                "execution_mode": "fact_only",
                "tools": [],
                "deep_thinking": False,
                "reasoning": "Non-user fact does not require immediate LLM response",
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
            "execution_mode": "function_calling" if decision.tools else "llm",
            "tools": decision.tools,
            "deep_thinking": decision.deep_thinking,
            "reasoning": decision.reasoning,
            "worker_strategy": decision.worker_strategy,
        }

    async def match_tools(self, context: dict[str, Any], intent_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "tools": intent_result.get("tools", []),
            "deep_thinking": bool(intent_result.get("deep_thinking", False)),
            "intent": str(intent_result.get("intent", "chat")),
            "worker_strategy": intent_result.get("worker_strategy", {}),
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
            "worker_strategy": tool_result.get("worker_strategy", {}),
            "execution_mode": str(intent_result.get("execution_mode", "llm")),
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
        if llm_params.get("execution_mode") == "fact_only":
            return {"response": "", "skip_emit": True}

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
                worker_strategy=llm_params.get("worker_strategy"),
            )
            response_text = execution_outcome.content
            return {"response": response_text, "execution_outcome": execution_outcome.to_dict()}
        return {"response": response_text}

    async def parse_result(self, context: dict[str, Any], raw_result: Any) -> None:
        if self._action_executor is None:
            return
        latest_fact = context.get("latest_fact")
        if not isinstance(latest_fact, FactRecord):
            return
        if latest_fact.event_type in WORKER_AGENT_EVENT_TYPES:
            logger.info(
                "Worker fact received by chat agent | worker_id=%s event_type=%s",
                latest_fact.payload.get("worker_id"),
                latest_fact.event_type,
            )
            return
        if latest_fact.event_type != EventTypes.USER_MESSAGE:
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
        user_message = context["user_message"]
        history_key = context["history_key"]
        history = self._conversation_history.setdefault(history_key, [])
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        await self._record_memory_updates(user_id=user_id, user_message=user_message)

        correlation_id = latest_fact.correlation_id

        await self._action_executor.emit_chat_response_event(
            user_id=user_id,
            session_id=session_id,
            response=response_text,
            correlation_id=correlation_id,
        )
        now = time.time()
        message_started_at = float(latest_fact.timestamp or now)
        response_time = max(0.0, now - message_started_at)
        action_payload = dict(latest_fact.payload) if isinstance(latest_fact.payload, dict) else {}
        action_payload.update(
            {
                "action_type": "ChatResponseAction",
                "response": response_text,
                "execution_time": response_time,
                "user_id": user_id,
                "session_id": session_id,
            }
        )
        await self._action_executor.emit_action_event(
            fact=FactRecord(
                agent_id=latest_fact.agent_id,
                event_type=latest_fact.event_type,
                payload=action_payload,
                agent_type=latest_fact.agent_type,
                agent_instance_id=latest_fact.agent_instance_id,
                timestamp=latest_fact.timestamp,
                correlation_id=latest_fact.correlation_id,
            ),
            success=True,
            error=None,
        )

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
