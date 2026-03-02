"""
Runtime task agent for chat facts.
"""
from __future__ import annotations

import json
import platform
import re
import sqlite3
import time
import uuid
from typing import Any, Optional

from ...core.logger import get_logger
from ...llm.provider_bridge import LLMProviderBridge
from ...memory.behavior_evolution import SatisfactionLevel
from ...memory.context_builder import Scenario
from ...memory.emotional_state import EngagementLevel, InteractionOutcome
from ...memory.growth_memory import InteractionType
from ...skills.executor import SkillExecutor
from ...skills.indexer import SkillIndexer
from ...skills.loader import SkillLoader
from ...tools.context_decider import ContextDecider
from ...tools.function_calling import FunctionCallingExecutor
from ...tools.registry import tool_registry
from ...utils.runtime import get_runtime_paths
from ...core.runtime.contracts import FactRecord
from ...core.runtime.task_agent import TaskAgent
from ...core.runtime.types import TaskAgentType

logger = get_logger(__name__)
TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"


def clean_tool_artifacts(text: str) -> str:
    text = re.sub(r"<antml:function_calls>.*?</antml:function_calls>", "", text, flags=re.DOTALL)
    text = re.sub(r"<antml:tool_result>.*?</antml:tool_result>", "", text, flags=re.DOTALL)
    text = re.sub(r"<tool_result>.*?</tool_result>", "", text, flags=re.DOTALL)
    text = re.sub(r"<invoke>.*?</invoke>", "", text, flags=re.DOTALL)
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        remove_line = False
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                maybe_call = json.loads(stripped)
                remove_line = (
                    isinstance(maybe_call, dict)
                    and isinstance(maybe_call.get("name"), str)
                    and isinstance(maybe_call.get("arguments"), dict)
                    and set(maybe_call.keys()).issubset({"name", "arguments"})
                )
            except Exception:
                remove_line = False
        if not remove_line:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        self.llm = llm_adapter
        self.memory = memory
        self.other_memory = other_memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration
        self.context_decider = ContextDecider(tool_registry=tool_registry, llm_adapter=llm_adapter)

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
        )

        self._conversation_history: dict[str, list[dict]] = {}
        self._tool_interactions: dict[str, list[dict]] = {}
        self._current_session_by_user: dict[str, str] = {}
        runtime_paths = get_runtime_paths()
        self._session_state_file = runtime_paths.data_dir / "chat_sessions.json"
        self._events_db_path = runtime_paths.events_db_path
        self._load_session_state()
        self._restore_conversation_from_events()

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def build_context(self, merged_facts: list[FactRecord]) -> dict[str, Any]:
        context = await super().build_context(merged_facts)
        latest_fact = context.get("latest_fact")
        payload = latest_fact.payload if isinstance(latest_fact, FactRecord) else {}
        user_id = str(payload.get("user_id", self.agent_id))
        user_message = str(payload.get("message", "")).strip()
        session_id = self._resolve_session_id(user_id, payload.get("session_id"))
        context.update(
            {
                "user_id": user_id,
                "user_message": user_message,
                "session_id": session_id,
                "history_key": self._history_key(user_id, session_id),
                "history": self._conversation_history.get(self._history_key(user_id, session_id), []),
            }
        )
        return context

    async def match_intent(self, context: dict[str, Any]) -> dict[str, Any]:
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
        }

    async def match_tools(self, context: dict[str, Any], intent_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "tools": intent_result.get("tools", []),
            "deep_thinking": bool(intent_result.get("deep_thinking", False)),
            "intent": str(intent_result.get("intent", "chat")),
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
        system_prompt = await self._build_system_prompt(
            scenario=Scenario.CHAT,
            user_id=user_id,
            task_category=str(intent_result.get("intent", "chat")),
        )
        return {
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
            "history": history,
            "system_prompt": system_prompt,
            "tools": tool_result.get("tools", []),
            "deep_thinking": bool(tool_result.get("deep_thinking", False)),
            "intent": str(tool_result.get("intent", "chat")),
        }

    async def call_llm(self, context: dict[str, Any], llm_params: dict[str, Any]) -> dict[str, Any]:
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
            response_text = await self.function_calling_executor.execute_with_tools(
                user_message=user_message,
                system_prompt=llm_params["system_prompt"],
                selected_tools=llm_params["tools"],
                user_id=llm_params["user_id"],
                session_id=llm_params["session_id"],
                conversation_history=history,
                disable_thinking=not llm_params["deep_thinking"],
                intent=llm_params["intent"],
            )
        return {"response": clean_tool_artifacts(response_text)}

    async def parse_result(self, context: dict[str, Any], raw_result: Any) -> None:
        if self._action_executor is None:
            return
        response_text = str(raw_result.get("response", "")) if isinstance(raw_result, dict) else str(raw_result)
        user_id = context["user_id"]
        session_id = context["session_id"]
        user_message = context["user_message"]
        history_key = context["history_key"]
        history = self._conversation_history.setdefault(history_key, [])
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        await self._record_memory_updates(user_id=user_id, user_message=user_message)
        await self._action_executor.emit_chat_response_event(
            user_id=user_id,
            session_id=session_id,
            response=response_text,
        )
        latest_fact = context.get("latest_fact")
        if isinstance(latest_fact, FactRecord):
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
        if self.memory is not None:
            try:
                personality_context = await self.memory.build_context(
                    scenario=scenario,
                    task_category=task_category,
                    user_id=user_id,
                    tool_memory_context="",
                )
                if personality_context:
                    return personality_context
            except Exception as exc:
                logger.warning(f"Failed to build personality context: {exc}")
        return (
            "You are a friendly AI assistant."
            "Your task is to help users answer questions, provide advice, and execute tasks."
        )

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = True,
    ) -> str:
        provider_bridge = LLMProviderBridge(self.llm)
        return await provider_bridge.chat(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
            disable_thinking=disable_thinking,
        )

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
