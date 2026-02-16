"""
ChatAgent - Chat Agent Implementation

processes user messages, generates responses via LLM, pushes via WebSocket
Follows proper Agent architecture: Sense-Plan-Act-Reflect
"""
import time
import logging
import re
import json
import uuid
import sqlite3
from typing import Any, Optional, Dict, List
from ..core.complete_agent import CompleteAgent
from ..core.agent import AgentConfig
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..utils.agent_logger import get_agent_logger, log_chain_start, log_chain_step, log_chain_end
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from ..tools.registry import ToolRegistry, tool_registry
from ..tools.selector import ToolSelector
from ..tools.context_decider import ContextDecider
from ..tools.function_calling import FunctionCallingExecutor
from ..tools.schema import ToolExecutionContext
from ..memory.self_memory import SelfMemory
from ..memory.other_memory import OtherMemory
from ..memory.behavior_evolution import Satisfactionlevel
from ..memory.emotional_state import InteractionOutcome, Engagementlevel
from ..memory.growth_memory import Interactiontype
from ..memory.context_builder import Scenario
from ..memory.models import TaskBehaviorProfile
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)
agent_logger = get_agent_logger('chat')
llm_logger = get_llm_logger('chat')
TOOL_intERACTION_EVENT_type = "TOOL_intERACTION"


def clean_tool_artifacts(text: str) -> str:
    """
    Clean tool call artifacts from LLM response

    Removes formats like:
    - <antml:function_calls>...</antml:function_calls>
    - <antml:tool_result>...</antml:tool_result>
    - <tool_result>...</tool_result>
    - {"name": "tool", "arguments": {...}}
    - <invoke>...</invoke>

    Args:
        text: Raw LLM response

    Returns:
        Cleaned response
    """
    # Remove function_calls tag and itsContent
    text = re.sub(r'<antml:function_calls>.*?</antml:function_calls>', '', text, flags=re.DOTALL)

    # Remove tool_result tag and itsContent
    text = re.sub(r'<antml:tool_result>.*?</antml:tool_result>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.DOTALL)

    # Remove invoke tag and itsContent
    text = re.sub(r'<invoke>.*?</invoke>', '', text, flags=re.DOTALL)

    # Only remove“occupying a single line”的Function调用JSON，avoid mistakenly deleting notttrmal businessJSONContent
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

    # Remove剩余的空row（超过2个连续换row）
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


class ChatAgent(CompleteAgent):
    """
    Chat Agent - Handles user messages and generates responses

    Architecture flow:
    1. Sense - Get user messages from UserMessageSensor
    2. Plan - processingModule analyzes messages, generates response plan
    3. Act - Execute action: call LLM to generate response, send via WebSocket
    4. Reflect - Save conversation history to memory
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBusBackend,
        llm_adapter: LLMAdapter,
        memory: SelfMemory = None,
        other_memory: OtherMemory = None,
        unified_memory = None,
        memory_integration = None,
    ):
        """
        initialize ChatAgent

        Args:
            config: Agent configuration
            message_bus: Message bus
            llm_adapter: LLM adapter
            memory: Self memory system (optional)
            other_memory: Other memory system (optional)
            unified_memory: Unified memory storage (optional, L1-L5)
            memory_integration: Memory integration module (optional)
        """
        super().__init__(config, message_bus, llm_adapter)

        # Conversation history (by user_id + session_id)
        self._conversation_history: dict[str, list[dict]] = {}
        self._current_session_by_user: dict[str, str] = {}
        runtime_paths = get_runtime_paths()
        self._session_state_file = runtime_paths.data_dir / "chat_sessions.json"
        self._events_db_path = runtime_paths.events_db_path

        # Tool selector (five-step decision process) - kept for compatibility
        self.tool_selector = ToolSelector(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
        )

        # Context decider - new tool selection method
        self.context_decider = ContextDecider(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
        )

        # Function calling executor - supports consecutive tool calls
        self.function_calling_executor = FunctionCallingExecutor(
            llm_adapter=llm_adapter,
            tool_registry=tool_registry,
            skill_executor=None,  # Will set after skill_executor is initialized
            tool_result_callback=self._record_tool_interaction,
        )

        # Tool interaction history (by user_id + session_id)
        self._tool_interactions: dict[str, list[dict]] = {}
        self._load_session_state()
        self._restore_conversation_from_events()

        # Self memory system
        self.memory = memory

        # Other memory system
        self.other_memory = other_memory

        # Unified memory storage (L1-L5)
        self.unified_memory = unified_memory

        # Memory integration module
        self.memory_integration = memory_integration

        # Skill executor
        from ..skills.indexer import SkillIndexer
        from ..skills.loader import SkillLoader
        from ..skills.executor import SkillExecutor

        self._skill_indexer = SkillIndexer()
        self._skill_loader = SkillLoader(self._skill_indexer)
        self._skill_executor = SkillExecutor(self._skill_loader, llm_adapter)

        # Update function calling executor's skill_executor
        self.function_calling_executor.skill_executor = self._skill_executor

        # initialize skills index
        skills = self._skill_indexer.scan_all()
        if skills:
            tool_registry.register_skill_index(skills)
            agent_logger.info(f"📚 Skills indexed: {list(skills.keys())}")

        agent_logger.info(
            f"🤖 ChatAgent initialized | Name: {config.name} | "
            f"SelfMemory: {'enabled' if memory else 'disabled'} | "
            f"OtherMemory: {'enabled' if other_memory else 'disabled'} | "
            f"UnifiedMemory: {'enabled' if unified_memory else 'disabled'} | "
            f"MemoryIntegration: {'enabled' if memory_integration else 'disabled'}"
        )

    async def execute_action(self, action: Any) -> dict:
        """
        Act phase - Execute action

        Args:
            action: Action to execute (ChatResponseAction)

        Returns:
            Execution result
        """
        from ..processing.actions import ChatResponseAction

        if not isinstance(action, ChatResponseAction):
            return {"success": False, "error": "Unknotttwn action type"}

        chain_id = action.chain_id
        user_id = action.user_id
        user_message = action.user_message
        session_id = self._resolve_session_id(user_id, action.session_id)

        log_chain_step(agent_logger, chain_id, "ACT", "Generating LLM response", "debug")

        try:
            # Generate LLM response
            response_text = await self._generate_response(user_id, user_message, session_id)

            log_chain_step(
                agent_logger,
                chain_id,
                "ACT",
                f"Response generated | Length: {len(response_text)} chars",
                "debug"
            )

            # Clean tool call artifacts
            cleaned_response = clean_tool_artifacts(response_text)
            if cleaned_response != response_text:
                agent_logger.info("🧹 Cleaned tool artifacts from response")
                response_text = cleaned_response

            # Send response via WebSocket
            from ..api.websocket import manager

            room = f"user_{user_id}"
            response_data = {
                "response": response_text,
                "timestamp": time.time(),
                "user_id": user_id,
                "session_id": session_id,
            }

            await manager.broadcast("agent_response", response_data, room=room)

            agent_logger.info(
                f"📤 Response delivered | User: {user_id} | Room: {room} | Length: {len(response_text)}"
            )

            return {
                "success": True,
                "response": response_text,
                "user_id": user_id,
                "session_id": session_id,
            }

        except Exception as e:
            agent_logger.error(f"❌ Failed to generate response: {e}")
            return {"success": False, "error": str(e)}

    async def _generate_response(self, user_id: str, user_message: str, session_id: str) -> str:
        """
        Generate LLM response (integrated with tool calls and skill execution)

        process:
        1. Check if it's a direct Skill call (/skill-name)
        2. Use context decider to select relevant tools
        3. Use function calling executor for consecutive tool calls
        4. Feed execution results back to LLM to generate final response

        Args:
            user_id: User id
            user_message: User message

        Returns:
            LLM response
        """
        start_time = time.time()

        # Get conversation history
        history_key = self._history_key(user_id, session_id)
        history = self._conversation_history.get(history_key, [])

        # Step 0: checkis not为直接 Skill 调用
        skill_invocation = self._skill_executor.validate_skill_invocation(user_message)
        if skill_invocation:
            skill_name, arguments = skill_invocation
            agent_logger.info(f"🎯 Direct skill invocation | Skill: /{skill_name} | Arguments: {arguments}")

            # Execute Skill
            skill_result = await self._execute_skill(
                skill_name,
                arguments,
                user_id,
                user_message,
                history,
            )

            if skill_result["success"]:
                return skill_result["response"]
            else:
                # Skill execution failed, return error message
                return f"Skill execution failed: {skill_result.get('error', 'Unknotttwn error')}"

        # Step 1: Context decision - select relevant tools
        import os
        import platform
        context = {
            "os": platform.system(),
            "os_version": platform.release(),
            "current_user": os.getenv("user") or os.getenv("username") or "unknotttwn",
            "home_dir": os.path.expanduser("~"),
            "current_dir": os.getcwd(),
        }

        context_decision = await self.context_decider.decide(user_message, context)
        agent_logger.info(
            f"🎯 Context decision | Intent: {context_decision.intent} | "
            f"Tools: {context_decision.tools} | Reasoning: {context_decision.reasoning}"
        )

        # Step 2: Use function calling executor to process
        response_text = await self._generate_response_with_function_calling(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            context_decision=context_decision,
            history=history,
        )

        # Calculate task duration
        duration = time.time() - start_time

        # Save to conversation history
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        self._conversation_history[history_key] = history

        # Record interaction to memory system
        if self.memory:
            try:
                outcome = InteractionOutcome.SUCCESS
                await self.memory.record_interaction(
                    user_id=user_id,
                    interaction_type=Interactiontype.CHAT,
                    outcome="success",
                    sentiment=0.0,
                    notes=f"Message: {user_message[:100]}..."
                )

                await self.memory.update_after_interaction(
                    outcome=outcome,
                    user_engagement=Engagementlevel.MEDIUM,
                    complexity=0.5
                )

                task_id = f"chat_{int(start_time)}_{user_id}"
                await self.memory.record_task_outcome(
                    task_id=task_id,
                    task_category=context_decision.intent,
                    user_satisfaction=Satisfactionlevel.NEUTRAL,
                    accepted=True,
                    task_complexity=0.5,
                    task_duration=duration,
                )

            except Exception as e:
                agent_logger.warning(f"Failed to record interaction: {e}")

        # Update other memory
        if self.other_memory:
            try:
                self.other_memory.update_interaction(
                    user_id=user_id,
                    interaction_type="chat",
                    outcome="positive",
                    notes=f"Message: {user_message[:100]}{'...' if len(user_message) > 100 else ''}",
                )
            except Exception as e:
                agent_logger.warning(f"Failed to update other memory: {e}")

        return response_text

    async def _generate_response_with_function_calling(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        context_decision,
        history: list[dict],
    ) -> str:
        """
        Generate response using function calling executor

        Args:
            user_id: User id
            user_message: User message
            context_decision: Context decision result
            history: Conversation history

        Returns:
            LLM response
        """
        try:
            tool_context = self._build_relevant_tool_context(
                user_id=user_id,
                session_id=session_id,
                user_message=user_message,
                intent=context_decision.intent,
            )

            # Build system prompt
            system_prompt = await self._build_system_prompt(
                tool_decision=None,  # tool_decision nottt longer needed
                scenario=Scenario.CHAT,
                user_id=user_id,
                task_category=context_decision.intent,
                tool_memory_context=tool_context,
            )

            # If nottt tools selected, call LLM directly
            if not context_decision.tools:
                agent_logger.info("ℹ️  No tools selected, using direct LLM response")

                messages = []
                for msg in history[-10:]:
                    messages.append(msg)
                messages.append({"role": "user", "content": user_message})

                response_text = await self._call_llm(
                    system_prompt,
                    messages,
                    disable_thinking=not context_decision.deep_thinking,
                )
                return clean_tool_artifacts(response_text)

            # Use function calling executor
            agent_logger.info(f"🔧 Using function calling with tools: {context_decision.tools}")

            response_text = await self.function_calling_executor.execute_with_tools(
                user_message=user_message,
                system_prompt=system_prompt,
                selected_tools=context_decision.tools,
                user_id=user_id,
                session_id=session_id,
                conversation_history=history,
                disable_thinking=not context_decision.deep_thinking,
                intent=context_decision.intent,
            )

            return response_text

        except Exception as e:
            agent_logger.error(f"❌ error in _generate_response_with_function_calling: {e}")
            import traceback
            agent_logger.error(f"Traceback: {traceback.format_exc()}")

            # Fallback: try simple LLM call
            try:
                messages = [{"role": "user", "content": user_message}]
                system_prompt = await self._build_system_prompt(
                    tool_decision=None,
                    scenario=Scenario.CHAT,
                    user_id=user_id,
                    task_category="chat",
                    tool_memory_context="",
                )
                return await self._call_llm(system_prompt, messages, disable_thinking=True)
            except Exception as e2:
                agent_logger.error(f"❌ Fallback LLM call also failed: {e2}")
                return "抱歉，我遇到了一些problem，请稍后再试。"

    async def _build_system_prompt(
        self,
        tool_decision: Optional[Dict],
        scenario: str = Scenario.CHAT,
        user_id: str = None,
        task_category: str = "chat",
        tool_memory_context: str = "",
    ) -> str:
        """
        Build system prompt

        Args:
            tool_decision: Tool decision info
            scenario: Interaction scenario
            user_id: User id (optional, used to get relationship info)
            task_category: Task category

        Returns:
            System prompt
        """
        # If memory system exists, use personality context
        if self.memory:
            try:
                personality_context = await self.memory.build_context(
                    scenario=scenario,
                    task_category=task_category,
                    user_id=user_id,
                )
                agent_logger.info(f"🎭 Personality context loaded | Length: {len(personality_context)} chars")
                if personality_context:
                    agent_logger.debug(f"🎭 Context preview: {personality_context[:200]}...")
            except Exception as e:
                agent_logger.warning(f"Failed to build personality context: {e}")
                personality_context = ""
        else:
            agent_logger.warning("⚠️ Memory system not enabled, using default personality")
            personality_context = ""

        # Base prompt (don't repeat identity info, identity already included in personality_context)
        base_prompt = (
            "Always respond to the user in the above identity."
            "Your task is to help users answer questions, provide advice, and execute tasks."
        )

        # Assemble prompt
        if personality_context:
            full_prompt = personality_context  # Already includes complete identity info, don't add base_prompt
        else:
            # Default prompt when nottt personality context
            full_prompt = (
                "You are a friendly AI assistant."
                "Your task is to help users answer questions, provide advice, and execute tasks."
            )

        # Add tool-related prompts
        if tool_decision and tool_decision.get("tool"):
            tool_name = tool_decision.get("tool")
            full_prompt += (
                f"\n\n[系统prompt] 已为user调用tool: {tool_name}"
                f"\nIf there are belowtool调用Result，please base onResultanswer user's question。"
                f"\nIf there are notool调用Result，it meanstoolExecutefailure，请告知user。"
            )

        if tool_memory_context:
            full_prompt += (
                "\n\n## Recent Tool Context\n"
                "Use these recent tool execution facts only when relevant to user's query:\n"
                f"{tool_memory_context}"
            )

        return full_prompt

    def _record_tool_interaction(self, payload: Dict[str, Any]) -> None:
        """Record tool execution facts for short-term cross-turn context."""
        user_id = payload.get("user_id")
        if not user_id:
            return
        session_id = self._resolve_session_id(user_id, payload.get("session_id"))

        success = bool(payload.get("success"))
        error_message = payload.get("error") or ""
        error_code = payload.get("error_code") or ""
        data = payload.get("data")
        data_summary = ""
        if data is not None:
            data_summary = str(data)
            if len(data_summary) > 240:
                data_summary = data_summary[:240] + "..."

        tool_name = str(payload.get("tool_name") or "unknotttwn")
        args_text = str(payload.get("arguments") or {})
        if len(args_text) > 160:
            args_text = args_text[:160] + "..."

        combined_text = f"{tool_name} {error_code} {error_message} {data_summary} {args_text}".lower()
        tags: list[str] = []
        for keyword, tag in (
            ("weather", "weather"),
            ("days气", "weather"),
            ("api_key", "api_key"),
            ("api key", "api_key"),
            ("qweather", "weather_provider"),
            ("missing", "missing"),
            ("not set", "missing"),
            ("Configuration", "config"),
            ("环境Variable", "env"),
        ):
            if keyword in combined_text:
                tags.append(tag)

        record = {
            "timestamp": time.time(),
            "intent": payload.get("intent") or "unknotttwn",
            "tool_name": tool_name,
            "status": "success" if success else "error",
            "error_code": error_code,
            "error_message": error_message,
            "result_summary": data_summary,
            "args_summary": args_text,
            "ttl_seconds": 1800 if success else 86400,
            "tags": sorted(set(tags)),
        }

        records_key = self._history_key(user_id, session_id)
        records = self._tool_interactions.setdefault(records_key, [])
        records.append(record)
        if len(records) > 100:
            self._tool_interactions[records_key] = records[-100:]
        self._persist_tool_interaction(
            user_id=user_id,
            session_id=session_id,
            record=record,
        )

    def _persist_tool_interaction(
        self,
        user_id: str,
        session_id: str,
        record: Dict[str, Any],
    ) -> None:
        """persist tool interaction record into event_store for restart recovery."""
        try:
            if not self._events_db_Path.exists():
                return

            payload = {
                "user_id": user_id,
                "session_id": session_id,
                "record": record,
            }

            event_id = str(uuid.uuid4())
            correlation_id = str(uuid.uuid4())
            timestamp = float(record.get("timestamp", time.time()))
            conn = sqlite3.connect(str(self._events_db_path))
            cur = conn.cursor()
            cur.execute(
                """
                INSERT intO event_store (
                    id, Type, data, media_path, timestamp, source,
                    level, correlation_id, metadata, created_at
                ) valueS (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    TOOL_intERACTION_EVENT_type,
                    json.dumps(payload, ensure_ascii=False),
                    None,
                    timestamp,
                    "chat_agent",
                    1,
                    correlation_id,
                    json.dumps({}, ensure_ascii=False),
                    time.time(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            agent_logger.warning(f"Failed to persist tool interaction: {e}")

    def _build_relevant_tool_context(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        intent: str,
    ) -> str:
        """Always include recent tool errors from current session."""
        records = self._tool_interactions.get(self._history_key(user_id, session_id), [])
        if not records:
            return ""

        notttw = time.time()
        recent_errors: list[dict] = []
        for record in records:
            age_seconds = notttw - float(record.get("timestamp", notttw))
            ttl = int(record.get("ttl_seconds", 0))
            if ttl > 0 and age_seconds > ttl:
                continue
            if str(record.get("status", "success")) == "error":
                recent_errors.append(record)

        if not recent_errors:
            return ""

        recent_errors.sort(key=lambda item: float(item.get("timestamp", 0.0)), reverse=True)
        selected = recent_errors[:3]

        lines: list[str] = []
        for record in selected:
            status = record.get("status", "unknotttwn")
            tool_name = record.get("tool_name", "unknotttwn")
            if status == "error":
                error_code = record.get("error_code") or "UNKNOWN_error"
                error_message = record.get("error_message") or "No error message"
                lines.append(f"- [{status}] {tool_name}: {error_code} | {error_message}")
            else:
                result_summary = record.get("result_summary") or "No result summary"
                lines.append(f"- [{status}] {tool_name}: {result_summary}")

        return "\n".join(lines)

    def _extract_query_tokens(self, text: str) -> list[str]:
        """Extract lightweight tokens for relevance matching."""
        tokens = set(re.findall(r"[a-z0-9_]{2,}", text))
        for phrase in [
            "days气",
            "error report",
            "error",
            "failure",
            "malfunction",
            "what happened",
            "why",
            "why",
            "reason",
            "problem",
            "Configuration",
            "环境Variable",
            "api",
            "key",
            "没Configuration",
        ]:
            if phrase in text:
                tokens.add(phrase)
        return sorted(tokens)

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

    def _load_session_state(self) -> None:
        try:
            if self._session_state_file.exists():
                data = json.loads(self._session_state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    mapping = data.get("current_session_by_user", {})
                    if isinstance(mapping, dict):
                        self._current_session_by_user = {
                            str(k): str(v) for k, v in mapping.items() if k and v
                        }
        except Exception as e:
            agent_logger.warning(f"Failed to load session state: {e}")

    def _save_session_state(self) -> None:
        try:
            payload = {"current_session_by_user": self._current_session_by_user}
            self._session_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._session_state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            agent_logger.warning(f"Failed to save session state: {e}")

    def _restore_conversation_from_events(self) -> None:
        """Restore in-memory chat histories and tool interactions from event_store."""
        try:
            if not self._events_db_Path.exists():
                return
            conn = sqlite3.connect(str(self._events_db_path))
            cur = conn.cursor()
            cur.execute(
                """
                SELECT type, data
                FROM event_store
                WHERE type IN ('user_input', 'AI_RESPONSE', ?)
                order BY timestamp asC
                LIMIT 5000
                """
                ,
                (TOOL_intERACTION_EVENT_type,)
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            agent_logger.warning(f"Failed to load event_store for history restore: {e}")
            return

        restored = 0
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
            if event_type == "user_input":
                content = payload.get("message", "")
                if content:
                    history.append({"role": "user", "content": str(content)})
                    restored += 1
            elif event_type == "AI_RESPONSE":
                content = payload.get("response", "")
                if content:
                    history.append({"role": "assistant", "content": str(content)})
                    restored += 1
            elif event_type == TOOL_intERACTION_EVENT_type:
                record = payload.get("record")
                if not isinstance(record, dict):
                    continue
                records = self._tool_interactions.setdefault(key, [])
                records.append(record)
                if len(records) > 100:
                    self._tool_interactions[key] = records[-100:]
        if restored:
            agent_logger.info(f"🔁 Restored conversation messages from event_store: {restored}")

    async def _call_llm(
        self,
        system_prompt: str,
        messages: list,
        disable_thinking: bool = True,
    ) -> str:
        """
        Call LLM to generate response

        Args:
            system_prompt: System prompt
            messages: Message list

        Returns:
            LLM response
        """
        import time
        import uuid

        # Generate request id
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        model_name = self.llm.model_name

        # Log request
        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=1000,
            temperature=0.7
        )

        try:
            provider_bridge = LLMProviderBridge(self.llm)
            response_text = await provider_bridge.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=1000,
                temperature=0.7,
                disable_thinking=disable_thinking,
            )

            # Clean tool call artifacts
            response_text = clean_tool_artifacts(response_text)

            # Log response
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=response_text,
                success=True,
                duration_ms=duration_ms
            )

            return response_text

        except Exception as e:
            # Log error
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )
            raise

    async def _execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Execute tool

        Args:
            tool_name: Tool name
            parameters: Tool parameters
            user_id: User id

        Returns:
            Execution result
        """
        try:
            # Determine required permissions
            permissions = ["authenticated"]

            # Check if tool requires dangerous operation permission
            tool_info = tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")

            # Create execution context
            context = ToolExecutionContext(
                agent_id=self.config.name,  # Use name from Agent config
                user_id=user_id,
                workspace="/tmp",  # Use /tmp as default working directory
                env_vars={},
                permissions=permissions,
            )

            # Execute tool
            result = await tool_registry.execute(tool_name, parameters, context)

            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "execution_time": result.execution_time,
            }

        except Exception as e:
            agent_logger.error(f"❌ Tool execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None,
            }

    async def _execute_skill(
        self,
        skill_name: str,
        arguments: List[str],
        user_id: str,
        user_message: str,
        conversation_history: list[dict],
    ) -> Dict[str, Any]:
        """
        Execute Skill

        Args:
            skill_name: Skill name (without / prefix)
            arguments: Command line arguments
            user_id: User id
            user_message: Original user message
            conversation_history: Conversation history

        Returns:
            Execution result {"success": bool, "response": str, "error": ...}
        """
        import os

        # Build Skill execution context
        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "user_message": user_message,
            "conversation_history": conversation_history,
            "env_vars": {
                "user": os.getenv("user") or os.getenv("username") or "unknotttwn",
                "HOME": os.path.expanduser("~"),
                "PWD": os.getcwd(),
                "CLAUDE_session_id": f"session_{user_id}",
                "user_id": user_id,
            },
        }

        try:
            # Execute Skill
            result = await self._skill_executor.execute(
                skill_name=skill_name,
                arguments=arguments,
                context=skill_context,
            )

            if result.success:
                # If Skill execution succeeded, return content
                response_content = result.content or ""

                # If Skill returns instructions (direct mode), need to generate final response via LLM
                if result.metadata.get("mode") == "direct":
                    # Use Skill content as system prompt
                    system_prompt = response_content

                    messages = []
                    # Add conversation history
                    for msg in conversation_history[-5:]:
                        messages.append(msg)
                    # Add current user message
                    messages.append({"role": "user", "content": user_message})

                    response_text = await self._call_llm(system_prompt, messages)
                    # Clean tool call artifacts
                    response_text = clean_tool_artifacts(response_text)

                    return {
                        "success": True,
                        "response": response_text,
                        "mode": "direct_with_llm",
                    }
                else:
                    # Sub-agent mode, clean tool call artifacts and return result
                    response_content = clean_tool_artifacts(response_content)
                    return {
                        "success": True,
                        "response": response_content,
                        "mode": "subagent",
                    }
            else:
                return {
                    "success": False,
                    "error": result.error or "Skill execution failed",
                }

        except Exception as e:
            agent_logger.error(f"❌ Skill execution error: {e}")
            import traceback
            agent_logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_conversation_history(self, user_id: str, session_id: Optional[str] = None) -> list[dict]:
        """
        Get conversation history

        Args:
            user_id: User id

        Returns:
            Conversation history
        """
        active_session = self._resolve_session_id(user_id, session_id)
        return self._conversation_history.get(self._history_key(user_id, active_session), [])

    def clear_conversation_history(self, user_id: str, session_id: Optional[str] = None):
        """
        Clear conversation history

        Args:
            user_id: User id
        """
        active_session = self._resolve_session_id(user_id, session_id)
        key = self._history_key(user_id, active_session)
        self._conversation_history[key] = []
        self._tool_interactions[key] = []
        agent_logger.info(f"🗑️ Conversation history cleared | User: {user_id} | Session: {active_session}")
