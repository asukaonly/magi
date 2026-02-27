"""
ChatWorkerAgent - Chat Task Worker Agent

Specialized worker for handling chat tasks in the three-layer architecture.
Integrates LLM calls, tool execution, memory systems, and WebSocket responses.
"""
import time
import logging
import re
import json
import uuid
import asyncio
from typing import Any, Optional, Dict, List

from .agent import Agent, AgentState, AgentConfig
from .task_database import Task, TaskStatus
from ..events.events import Event, EventTypes, EventLevel
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter
from ..llm.provider_bridge import LLMProviderBridge
from ..tools.registry import ToolRegistry, tool_registry
from ..tools.selector import ToolSelector
from ..tools.context_decider import ContextDecider
from ..tools.function_calling import FunctionCallingExecutor
from ..tools.schema import ToolExecutionContext
from ..memory.context_builder import Scenario
from ..memory.behavior_evolution import SatisfactionLevel
from ..memory.emotional_state import InteractionOutcome, EngagementLevel
from ..memory.growth_memory import InteractionType
from ..utils.agent_logger import get_agent_logger
from ..utils.llm_logger import get_llm_logger

logger = logging.getLogger(__name__)
agent_logger = get_agent_logger('chat_worker')
llm_logger = get_llm_logger('chat_worker')


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
    # Remove function_calls tag and its content
    text = re.sub(r'<antml:function_calls>.*?</antml:function_calls>', '', text, flags=re.DOTALL)

    # Remove tool_result tag and its content
    text = re.sub(r'<antml:tool_result>.*?</antml:tool_result>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.DOTALL)

    # Remove invoke tag and its content
    text = re.sub(r'<invoke>.*?</invoke>', '', text, flags=re.DOTALL)

    # Only remove "occupying a single line" function call JSON
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

    # Remove remaining empty rows (more than 2 consecutive newlines)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


class ChatWorkerAgent(Agent):
    """
    ChatWorkerAgent - Specialized worker for chat tasks

    Responsibilities:
    - Execute chat tasks with LLM and tools
    - Integrate with memory systems
    - Push responses via WebSocket
    - Report task completion

    Lifecycle:
    - Created by TaskAgent for each chat task
    - Destroyed after task completion
    """

    def __init__(
        self,
        task_id: str,
        task: Task,
        subtasks: List,
        message_bus: MessageBusBackend,
        llm_adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        memory=None,
        other_memory=None,
        unified_memory=None,
        memory_integration=None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        """
        Initialize ChatWorkerAgent

        Args:
            task_id: Task ID
            task: Task object
            subtasks: List of subtasks
            message_bus: Message bus for event publishing
            llm_adapter: LLM adapter
            tool_registry: Tool registry
            memory: SelfMemory system (optional)
            other_memory: OtherMemory system (optional)
            unified_memory: UnifiedMemoryStore (optional)
            memory_integration: MemoryIntegrationModule (optional)
            timeout: Task timeout in seconds
            max_retries: Maximum retry count
        """
        config = AgentConfig(name=f"ChatWorker-{task_id}", llm_config={})
        super().__init__(config)

        self.task_id = task_id
        self.task = task
        self.subtasks = subtasks
        self.message_bus = message_bus
        self.llm = llm_adapter
        self.tool_registry = tool_registry
        self.timeout = timeout
        self.max_retries = max_retries

        # Memory systems
        self.memory = memory
        self.other_memory = other_memory
        self.unified_memory = unified_memory
        self.memory_integration = memory_integration

        # Conversation history (by user_id + session_id)
        self._conversation_history: Dict[str, List[Dict]] = {}
        self._tool_interactions: Dict[str, List[Dict]] = {}

        # Context decider for tool selection
        self.context_decider = ContextDecider(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
        )

        # Function calling executor for consecutive tool calls
        self.function_calling_executor = FunctionCallingExecutor(
            llm_adapter=llm_adapter,
            tool_registry=tool_registry,
            skill_executor=None,
            tool_result_callback=self._record_tool_interaction,
        )

        # Initialize skills
        self._init_skills()

        # Completion tracking
        self._completion_event = asyncio.Event()
        self._final_result = None

        agent_logger.info(
            f"ChatWorkerAgent initialized | Task: {task_id} | "
            f"Memory: {'enabled' if memory else 'disabled'} | "
            f"Timeout: {timeout}s"
        )

    def _init_skills(self):
        """Initialize skills system"""
        try:
            from ..skills.indexer import SkillIndexer
            from ..skills.loader import SkillLoader
            from ..skills.executor import SkillExecutor

            self._skill_indexer = SkillIndexer()
            self._skill_loader = SkillLoader(self._skill_indexer)
            self._skill_executor = SkillExecutor(self._skill_loader, self.llm)

            # Update function calling executor's skill_executor
            self.function_calling_executor.skill_executor = self._skill_executor

            # Initialize skills index
            skills = self._skill_indexer.scan_all()
            if skills:
                self.tool_registry.register_skill_index(skills)
                agent_logger.info(f"Skills indexed: {list(skills.keys())}")
        except Exception as e:
            agent_logger.warning(f"Failed to initialize skills: {e}")
            self._skill_executor = None

    async def _on_start(self):
        """Execute task on start"""
        try:
            # Use asyncio.wait_for for timeout
            result = await asyncio.wait_for(
                self._execute_with_retry(),
                timeout=self.timeout
            )

            self._final_result = result

            # Task completed
            agent_logger.info(f"ChatWorkerAgent-{self.task_id} completed successfully")

        except asyncio.TimeoutError:
            # Task timeout
            agent_logger.error(f"ChatWorkerAgent-{self.task_id} timeout after {self.timeout}s")
            await self._publish_error_event(
                f"ChatWorkerAgent-{self.task_id}",
                f"Task timeout after {self.timeout}s"
            )
            self._final_result = {"status": "timeout", "error": f"Timeout after {self.timeout}s"}

        except Exception as e:
            # Task failed
            agent_logger.error(f"ChatWorkerAgent-{self.task_id} failed: {e}")
            await self._publish_error_event(f"ChatWorkerAgent-{self.task_id}", str(e))
            self._final_result = {"status": "failed", "error": str(e)}

        finally:
            # Mark as completed
            self._completion_event.set()

    async def _on_stop(self):
        """Cleanup on stop"""
        agent_logger.debug(f"ChatWorkerAgent-{self.task_id} stopping")

    async def _execute_with_retry(self) -> Dict[str, Any]:
        """
        Execute task with retry

        Returns:
            Execution result
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    agent_logger.info(f"ChatWorkerAgent-{self.task_id} retry {attempt}/{self.max_retries}")

                result = await self._execute_task()

                # Success, return result
                return {
                    "status": "completed",
                    "output": result,
                    "attempts": attempt + 1,
                }

            except Exception as e:
                last_error = e
                agent_logger.warning(f"ChatWorkerAgent-{self.task_id} attempt {attempt + 1} failed: {e}")

                # If not the last attempt, wait for a while
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

        # All attempts failed
        raise last_error

    async def _execute_task(self) -> Any:
        """
        Execute the chat task

        Returns:
            Task execution result
        """
        start_time = time.time()

        # Extract task data
        task_data = self.task.data
        user_message = task_data.get("message", "")
        user_id = task_data.get("user_id", "unknown")
        session_id = task_data.get("session_id", str(uuid.uuid4()))

        agent_logger.info(
            f"Processing chat task | User: {user_id} | Session: {session_id} | "
            f"Message: {user_message[:50]}..."
        )

        # Generate response
        response_text = await self._generate_response(
            user_id=user_id,
            user_message=user_message,
            session_id=session_id,
        )

        # Clean tool call artifacts
        cleaned_response = clean_tool_artifacts(response_text)
        if cleaned_response != response_text:
            agent_logger.debug("Cleaned tool artifacts from response")
            response_text = cleaned_response

        # Push response via WebSocket
        await self._push_response(user_id, session_id, response_text)

        # Record to memory system
        duration = time.time() - start_time
        await self._record_to_memory(user_id, user_message, response_text, duration)

        # Publish task completed event
        await self._publish_event(
            EventTypes.TASK_COMPLETED,
            {
                "task_id": self.task_id,
                "user_id": user_id,
                "session_id": session_id,
                "result": response_text[:200] if response_text else None,
            }
        )

        return {"response": response_text, "user_id": user_id, "session_id": session_id}

    async def _generate_response(
        self,
        user_id: str,
        user_message: str,
        session_id: str,
    ) -> str:
        """
        Generate LLM response (integrated with tool calls and skill execution)

        Args:
            user_id: User ID
            user_message: User message
            session_id: Session ID

        Returns:
            LLM response
        """
        # Get conversation history
        history_key = f"{user_id}::{session_id}"
        history = self._conversation_history.get(history_key, [])

        # Step 0: Check if it's a direct Skill call
        if self._skill_executor:
            skill_invocation = self._skill_executor.validate_skill_invocation(user_message)
            if skill_invocation:
                skill_name, arguments = skill_invocation
                agent_logger.info(f"Direct skill invocation | Skill: /{skill_name}")

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
                    return f"Skill execution failed: {skill_result.get('error', 'Unknown error')}"

        # Step 1: Context decision - select relevant tools
        import os
        import platform
        context = {
            "os": platform.system(),
            "os_version": platform.release(),
            "current_user": os.getenv("user") or os.getenv("username") or "unknown",
            "home_dir": os.path.expanduser("~"),
            "current_dir": os.getcwd(),
        }

        context_decision = await self.context_decider.decide(user_message, context)
        agent_logger.info(
            f"Context decision | Intent: {context_decision.intent} | "
            f"Tools: {context_decision.tools} | Reasoning: {context_decision.reasoning}"
        )

        # Step 2: Generate response with function calling
        response_text = await self._generate_response_with_function_calling(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            context_decision=context_decision,
            history=history,
        )

        # Save to conversation history
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        self._conversation_history[history_key] = history

        return response_text

    async def _generate_response_with_function_calling(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        context_decision,
        history: List[Dict],
    ) -> str:
        """
        Generate response using function calling executor

        Args:
            user_id: User ID
            session_id: Session ID
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
            )

            # Build system prompt
            system_prompt = await self._build_system_prompt(
                scenario=Scenario.CHAT,
                user_id=user_id,
                task_category=context_decision.intent,
                tool_memory_context=tool_context,
            )

            # If no tools selected, call LLM directly
            if not context_decision.tools:
                agent_logger.debug("No tools selected, using direct LLM response")

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
            agent_logger.info(f"Using function calling with tools: {context_decision.tools}")

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
            agent_logger.error(f"Error in _generate_response_with_function_calling: {e}")

            # Fallback: try simple LLM call
            try:
                messages = [{"role": "user", "content": user_message}]
                system_prompt = await self._build_system_prompt(
                    scenario=Scenario.CHAT,
                    user_id=user_id,
                    task_category="chat",
                    tool_memory_context="",
                )
                return await self._call_llm(system_prompt, messages, disable_thinking=True)
            except Exception as e2:
                agent_logger.error(f"Fallback LLM call also failed: {e2}")
                return "Sorry, I encountered an issue. Please try again later."

    async def _build_system_prompt(
        self,
        scenario: str = Scenario.CHAT,
        user_id: str = None,
        task_category: str = "chat",
        tool_memory_context: str = "",
    ) -> str:
        """
        Build system prompt

        Args:
            scenario: Interaction scenario
            user_id: User ID (optional)
            task_category: Task category
            tool_memory_context: Tool memory context

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
                    tool_memory_context=tool_memory_context,
                )
                if personality_context:
                    agent_logger.debug(f"Personality context loaded | Length: {len(personality_context)}")
                    return personality_context
            except Exception as e:
                agent_logger.warning(f"Failed to build personality context: {e}")

        # Default prompt
        full_prompt = (
            "You are a friendly AI assistant. "
            "Your task is to help users answer questions, provide advice, and execute tasks."
        )

        if tool_memory_context:
            full_prompt += (
                "\n\n## Recent Tool Context\n"
                "Use these recent tool execution facts only when relevant to user's query:\n"
                f"{tool_memory_context}"
            )

        return full_prompt

    async def _call_llm(
        self,
        system_prompt: str,
        messages: List,
        disable_thinking: bool = True,
    ) -> str:
        """
        Call LLM to generate response

        Args:
            system_prompt: System prompt
            messages: Message list
            disable_thinking: Whether to disable thinking mode

        Returns:
            LLM response
        """
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        model_name = self.llm.model_name

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

            duration_ms = int((time.time() - start_time) * 1000)
            agent_logger.debug(f"LLM call completed | Request: {request_id} | Duration: {duration_ms}ms")

            return response_text

        except Exception as e:
            agent_logger.error(f"LLM call failed | Request: {request_id} | Error: {e}")
            raise

    async def _push_response(
        self,
        user_id: str,
        session_id: str,
        response_text: str,
    ):
        """
        Push response via WebSocket

        Args:
            user_id: User ID
            session_id: Session ID
            response_text: Response text
        """
        try:
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
                f"Response pushed | User: {user_id} | Room: {room} | Length: {len(response_text)}"
            )

        except Exception as e:
            agent_logger.error(f"Failed to push response: {e}")

    async def _record_to_memory(
        self,
        user_id: str,
        user_message: str,
        response_text: str,
        duration: float,
    ):
        """
        Record interaction to memory systems

        Args:
            user_id: User ID
            user_message: User message
            response_text: Response text
            duration: Task duration
        """
        if self.memory:
            try:
                await self.memory.record_interaction(
                    user_id=user_id,
                    interaction_type=InteractionType.CHAT,
                    outcome="success",
                    sentiment=0.0,
                    notes=f"Message: {user_message[:100]}..."
                )

                await self.memory.update_after_interaction(
                    outcome=InteractionOutcome.SUCCESS,
                    user_engagement=EngagementLevel.MEDIUM,
                    complexity=0.5
                )

            except Exception as e:
                agent_logger.warning(f"Failed to record interaction to memory: {e}")

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

    async def _execute_skill(
        self,
        skill_name: str,
        arguments: List[str],
        user_id: str,
        user_message: str,
        conversation_history: List[Dict],
    ) -> Dict[str, Any]:
        """
        Execute Skill

        Args:
            skill_name: Skill name (without / prefix)
            arguments: Command line arguments
            user_id: User ID
            user_message: Original user message
            conversation_history: Conversation history

        Returns:
            Execution result
        """
        import os

        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "user_message": user_message,
            "conversation_history": conversation_history,
            "env_vars": {
                "user": os.getenv("user") or os.getenv("username") or "unknown",
                "HOME": os.path.expanduser("~"),
                "PWD": os.getcwd(),
                "CLAUDE_session_id": f"session_{user_id}",
                "user_id": user_id,
            },
        }

        try:
            result = await self._skill_executor.execute(
                skill_name=skill_name,
                arguments=arguments,
                context=skill_context,
            )

            if result.success:
                response_content = result.content or ""

                if result.metadata.get("mode") == "direct":
                    system_prompt = response_content
                    messages = []
                    for msg in conversation_history[-5:]:
                        messages.append(msg)
                    messages.append({"role": "user", "content": user_message})

                    response_text = await self._call_llm(system_prompt, messages)
                    response_text = clean_tool_artifacts(response_text)

                    return {
                        "success": True,
                        "response": response_text,
                        "mode": "direct_with_llm",
                    }
                else:
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
            agent_logger.error(f"Skill execution error: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def _record_tool_interaction(self, payload: Dict[str, Any]) -> None:
        """Record tool execution facts for short-term cross-turn context."""
        user_id = payload.get("user_id")
        if not user_id:
            return
        session_id = payload.get("session_id", str(uuid.uuid4()))

        success = bool(payload.get("success"))
        error_message = payload.get("error") or ""
        error_code = payload.get("error_code") or ""
        data = payload.get("data")
        data_summary = ""
        if data is not None:
            data_summary = str(data)
            if len(data_summary) > 240:
                data_summary = data_summary[:240] + "..."

        tool_name = str(payload.get("tool_name") or "unknown")
        args_text = str(payload.get("arguments") or {})
        if len(args_text) > 160:
            args_text = args_text[:160] + "..."

        record = {
            "timestamp": time.time(),
            "intent": payload.get("intent") or "unknown",
            "tool_name": tool_name,
            "status": "success" if success else "error",
            "error_code": error_code,
            "error_message": error_message,
            "result_summary": data_summary,
            "args_summary": args_text,
            "ttl_seconds": 1800 if success else 86400,
        }

        records_key = f"{user_id}::{session_id}"
        records = self._tool_interactions.setdefault(records_key, [])
        records.append(record)
        if len(records) > 100:
            self._tool_interactions[records_key] = records[-100:]

    def _build_relevant_tool_context(
        self,
        user_id: str,
        session_id: str,
    ) -> str:
        """Include recent tool errors from current session."""
        records = self._tool_interactions.get(f"{user_id}::{session_id}", [])
        if not records:
            return ""

        now = time.time()
        recent_errors: List[Dict] = []
        for record in records:
            age_seconds = now - float(record.get("timestamp", now))
            ttl = int(record.get("ttl_seconds", 0))
            if ttl > 0 and age_seconds > ttl:
                continue
            if str(record.get("status", "success")) == "error":
                recent_errors.append(record)

        if not recent_errors:
            return ""

        recent_errors.sort(key=lambda item: float(item.get("timestamp", 0.0)), reverse=True)
        selected = recent_errors[:3]

        lines: List[str] = []
        for record in selected:
            status = record.get("status", "unknown")
            tool_name = record.get("tool_name", "unknown")
            if status == "error":
                error_code = record.get("error_code") or "UNKNOWN_ERROR"
                error_message = record.get("error_message") or "No error message"
                lines.append(f"- [{status}] {tool_name}: {error_code} | {error_message}")
            else:
                result_summary = record.get("result_summary") or "No result summary"
                lines.append(f"- [{status}] {tool_name}: {result_summary}")

        return "\n".join(lines)

    async def wait_for_completion(self):
        """Wait for task to complete"""
        await self._completion_event.wait()

    async def _publish_event(self, event_type: str, data: dict):
        """Publish event"""
        event = Event(
            type=event_type,
            data=data,
            source=f"ChatWorkerAgent-{self.task_id}",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

    async def _publish_error_event(self, source: str, error_message: str):
        """Publish error event"""
        event = Event(
            type=EventTypes.TASK_FAILED,
            data={
                "source": source,
                "error": error_message,
                "task_id": self.task_id,
            },
            source=source,
            level=EventLevel.ERROR,
        )
        await self.message_bus.publish(event)
