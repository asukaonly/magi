"""
ChatAgent - 聊天Agent实现

处理用户消息，通过LLM生成回复，通过WebSocket推送
遵循正确的Agent架构：Sense-Plan-Act-Reflect
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
from ..memory.behavior_evolution import SatisfactionLevel
from ..memory.emotional_state import InteractionOutcome, EngagementLevel
from ..memory.growth_memory import InteractionType
from ..memory.context_builder import Scenario
from ..memory.models import TaskBehaviorProfile
from ..utils.runtime import get_runtime_paths

logger = logging.getLogger(__name__)
agent_logger = get_agent_logger('chat')
llm_logger = get_llm_logger('chat')
TOOL_INTERACTION_EVENT_TYPE = "TOOL_INTERACTION"


def clean_tool_artifacts(text: str) -> str:
    """
    清理LLM响应中的工具调用痕迹

    移除类似这样的格式:
    - <antml:function_calls>...</antml:function_calls>
    - <antml:tool_result>...</antml:tool_result>
    - <tool_result>...</tool_result>
    - {"name": "tool", "arguments": {...}}
    - <invoke>...</invoke>

    Args:
        text: 原始LLM响应

    Returns:
        清理后的响应
    """
    # 移除 function_calls 标签及其内容
    text = re.sub(r'<antml:function_calls>.*?</antml:function_calls>', '', text, flags=re.DOTALL)

    # 移除 tool_result 标签及其内容
    text = re.sub(r'<antml:tool_result>.*?</antml:tool_result>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.DOTALL)

    # 移除 invoke 标签及其内容
    text = re.sub(r'<invoke>.*?</invoke>', '', text, flags=re.DOTALL)

    # 仅移除“独占一行”的函数调用JSON，避免误删正常业务JSON内容
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

    # 移除剩余的空行（超过2个连续换行）
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


class ChatAgent(CompleteAgent):
    """
    聊天Agent - 处理用户消息并生成回复

    架构流程：
    1. Sense - 从UserMessageSensor获取用户消息
    2. Plan - ProcessingModule分析消息，生成响应计划
    3. Act - 执行动作：调用LLM生成回复，通过WebSocket发送
    4. Reflect - 保存对话历史到记忆
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
        初始化ChatAgent

        Args:
            config: Agent配置
            message_bus: 消息总线
            llm_adapter: LLM适配器
            memory: 自我记忆系统（可选）
            other_memory: 他人记忆系统（可选）
            unified_memory: 统一记忆存储（可选，L1-L5）
            memory_integration: 记忆集成模块（可选）
        """
        super().__init__(config, message_bus, llm_adapter)

        # 对话历史（按 user_id + session_id 存储）
        self._conversation_history: dict[str, list[dict]] = {}
        self._current_session_by_user: dict[str, str] = {}
        runtime_paths = get_runtime_paths()
        self._session_state_file = runtime_paths.data_dir / "chat_sessions.json"
        self._events_db_path = runtime_paths.events_db_path

        # 工具选择器（五步决策流程）- 保留兼容
        self.tool_selector = ToolSelector(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
        )

        # 上下文决策器 - 新的工具选择方式
        self.context_decider = ContextDecider(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
        )

        # 函数调用执行器 - 支持连续工具调用
        self.function_calling_executor = FunctionCallingExecutor(
            llm_adapter=llm_adapter,
            tool_registry=tool_registry,
            skill_executor=None,  # Will set after skill_executor is initialized
            tool_result_callback=self._record_tool_interaction,
        )

        # 工具交互历史（按 user_id + session_id 存储）
        self._tool_interactions: dict[str, list[dict]] = {}
        self._load_session_state()
        self._restore_conversation_from_events()

        # 自我记忆系统
        self.memory = memory

        # 他人记忆系统
        self.other_memory = other_memory

        # 统一记忆存储（L1-L5）
        self.unified_memory = unified_memory

        # 记忆集成模块
        self.memory_integration = memory_integration

        # Skill 执行器
        from ..skills.indexer import SkillIndexer
        from ..skills.loader import SkillLoader
        from ..skills.executor import SkillExecutor

        self._skill_indexer = SkillIndexer()
        self._skill_loader = SkillLoader(self._skill_indexer)
        self._skill_executor = SkillExecutor(self._skill_loader, llm_adapter)

        # 更新函数调用执行器的skill_executor
        self.function_calling_executor.skill_executor = self._skill_executor

        # 初始化 skills 索引
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
        Act阶段 - 执行动作

        Args:
            action: 要执行的动作（ChatResponseAction）

        Returns:
            执行结果
        """
        from ..processing.actions import ChatResponseAction

        if not isinstance(action, ChatResponseAction):
            return {"success": False, "error": "Unknown action type"}

        chain_id = action.chain_id
        user_id = action.user_id
        user_message = action.user_message
        session_id = self._resolve_session_id(user_id, action.session_id)

        log_chain_step(agent_logger, chain_id, "ACT", "Generating LLM response", "DEBUG")

        try:
            # 生成LLM回复
            response_text = await self._generate_response(user_id, user_message, session_id)

            log_chain_step(
                agent_logger,
                chain_id,
                "ACT",
                f"Response generated | Length: {len(response_text)} chars",
                "DEBUG"
            )

            # 清理工具调用痕迹
            cleaned_response = clean_tool_artifacts(response_text)
            if cleaned_response != response_text:
                agent_logger.info("🧹 Cleaned tool artifacts from response")
                response_text = cleaned_response

            # 发送回复通过WebSocket
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
        生成LLM回复（集成工具调用和技能执行）

        流程：
        1. 检查是否为直接 Skill 调用 (/skill-name)
        2. 使用上下文决策器选择相关工具
        3. 使用函数调用执行器进行连续工具调用
        4. 将执行结果反馈给LLM生成最终回复

        Args:
            user_id: 用户ID
            user_message: 用户消息

        Returns:
            LLM回复
        """
        start_time = time.time()

        # 获取对话历史
        history_key = self._history_key(user_id, session_id)
        history = self._conversation_history.get(history_key, [])

        # Step 0: 检查是否为直接 Skill 调用
        skill_invocation = self._skill_executor.validate_skill_invocation(user_message)
        if skill_invocation:
            skill_name, arguments = skill_invocation
            agent_logger.info(f"🎯 Direct skill invocation | Skill: /{skill_name} | Arguments: {arguments}")

            # 执行 Skill
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
                # Skill 执行失败，返回错误信息
                return f"Skill execution failed: {skill_result.get('error', 'Unknown error')}"

        # Step 1: 上下文决策 - 选择相关工具
        import os
        import platform
        context = {
            "os": platform.system(),
            "os_version": platform.release(),
            "current_user": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
            "home_dir": os.path.expanduser("~"),
            "current_dir": os.getcwd(),
        }

        context_decision = await self.context_decider.decide(user_message, context)
        agent_logger.info(
            f"🎯 Context decision | Intent: {context_decision.intent} | "
            f"Tools: {context_decision.tools} | Reasoning: {context_decision.reasoning}"
        )

        # Step 2: 使用函数调用执行器处理
        response_text = await self._generate_response_with_function_calling(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            context_decision=context_decision,
            history=history,
        )

        # 计算任务持续时间
        duration = time.time() - start_time

        # 保存到对话历史
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        self._conversation_history[history_key] = history

        # 记录交互到记忆系统
        if self.memory:
            try:
                outcome = InteractionOutcome.SUCCESS
                await self.memory.record_interaction(
                    user_id=user_id,
                    interaction_type=InteractionType.CHAT,
                    outcome="success",
                    sentiment=0.0,
                    notes=f"Message: {user_message[:100]}..."
                )

                await self.memory.update_after_interaction(
                    outcome=outcome,
                    user_engagement=EngagementLevel.MEDIUM,
                    complexity=0.5
                )

                task_id = f"chat_{int(start_time)}_{user_id}"
                await self.memory.record_task_outcome(
                    task_id=task_id,
                    task_category=context_decision.intent,
                    user_satisfaction=SatisfactionLevel.NEUTRAL,
                    accepted=True,
                    task_complexity=0.5,
                    task_duration=duration,
                )

            except Exception as e:
                agent_logger.warning(f"Failed to record interaction: {e}")

        # 更新他人记忆
        if self.other_memory:
            try:
                self.other_memory.update_interaction(
                    user_id=user_id,
                    interaction_type="chat",
                    outcome="positive",
                    notes=f"消息: {user_message[:100]}{'...' if len(user_message) > 100 else ''}",
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
        使用函数调用执行器生成回复

        Args:
            user_id: 用户ID
            user_message: 用户消息
            context_decision: 上下文决策结果
            history: 对话历史

        Returns:
            LLM回复
        """
        try:
            tool_context = self._build_relevant_tool_context(
                user_id=user_id,
                session_id=session_id,
                user_message=user_message,
                intent=context_decision.intent,
            )

            # 构建系统提示
            system_prompt = await self._build_system_prompt(
                tool_decision=None,  # 不再需要 tool_decision
                scenario=Scenario.CHAT,
                user_id=user_id,
                task_category=context_decision.intent,
                tool_memory_context=tool_context,
            )

            # 如果没有选择工具，直接调用LLM
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

            # 使用函数调用执行器
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
            agent_logger.error(f"❌ Error in _generate_response_with_function_calling: {e}")
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
                return "抱歉，我遇到了一些问题，请稍后再试。"

    async def _build_system_prompt(
        self,
        tool_decision: Optional[Dict],
        scenario: str = Scenario.CHAT,
        user_id: str = None,
        task_category: str = "chat",
        tool_memory_context: str = "",
    ) -> str:
        """
        构建系统提示

        Args:
            tool_decision: 工具决策信息
            scenario: 交互场景
            user_id: 用户ID（可选，用于获取关系信息）
            task_category: 任务类别

        Returns:
            系统提示
        """
        # 如果有记忆系统，使用人格上下文
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

        # 基础提示（不重复身份信息，identity已包含在 personality_context 中）
        base_prompt = (
            "请始终以上述身份回应用户。"
            "你的任务是帮助用户解答问题、提供建议和执行任务。"
        )

        # 组装提示
        if personality_context:
            full_prompt = personality_context  # 已包含完整身份信息，不再添加 base_prompt
        else:
            # 没有人格上下文时的默认提示
            full_prompt = (
                "你是一个友好的AI助手。"
                "你的任务是帮助用户解答问题、提供建议和执行任务。"
            )

        # 添加工具相关提示
        if tool_decision and tool_decision.get("tool"):
            tool_name = tool_decision.get("tool")
            full_prompt += (
                f"\n\n[系统提示] 已为用户调用工具: {tool_name}"
                f"\n如果下方有工具调用结果，请基于结果回答用户问题。"
                f"\n如果没有工具调用结果，说明工具执行失败，请告知用户。"
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

        tool_name = str(payload.get("tool_name") or "unknown")
        args_text = str(payload.get("arguments") or {})
        if len(args_text) > 160:
            args_text = args_text[:160] + "..."

        combined_text = f"{tool_name} {error_code} {error_message} {data_summary} {args_text}".lower()
        tags: list[str] = []
        for keyword, tag in (
            ("weather", "weather"),
            ("天气", "weather"),
            ("api_key", "api_key"),
            ("api key", "api_key"),
            ("qweather", "weather_provider"),
            ("missing", "missing"),
            ("not set", "missing"),
            ("配置", "config"),
            ("环境变量", "env"),
        ):
            if keyword in combined_text:
                tags.append(tag)

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
        """Persist tool interaction record into event_store for restart recovery."""
        try:
            if not self._events_db_path.exists():
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
                INSERT INTO event_store (
                    id, type, data, media_path, timestamp, source,
                    level, correlation_id, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    TOOL_INTERACTION_EVENT_TYPE,
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

        now = time.time()
        recent_errors: list[dict] = []
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

        lines: list[str] = []
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

    def _extract_query_tokens(self, text: str) -> list[str]:
        """Extract lightweight tokens for relevance matching."""
        tokens = set(re.findall(r"[a-z0-9_]{2,}", text))
        for phrase in [
            "天气",
            "报错",
            "错误",
            "失败",
            "故障",
            "怎么回事",
            "为什么",
            "为啥",
            "原因",
            "问题",
            "配置",
            "环境变量",
            "api",
            "key",
            "没配置",
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
                """
                ,
                (TOOL_INTERACTION_EVENT_TYPE,)
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
            if event_type == "USER_INPUT":
                content = payload.get("message", "")
                if content:
                    history.append({"role": "user", "content": str(content)})
                    restored += 1
            elif event_type == "AI_RESPONSE":
                content = payload.get("response", "")
                if content:
                    history.append({"role": "assistant", "content": str(content)})
                    restored += 1
            elif event_type == TOOL_INTERACTION_EVENT_TYPE:
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
        调用LLM生成回复

        Args:
            system_prompt: 系统提示
            messages: 消息列表

        Returns:
            LLM回复
        """
        import time
        import uuid

        # 生成请求ID
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        model_name = self.llm.model_name

        # 记录请求日志
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

            # 清理工具调用痕迹
            response_text = clean_tool_artifacts(response_text)

            # 记录响应日志
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
            # 记录错误日志
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
        执行工具

        Args:
            tool_name: 工具名称
            parameters: 工具参数
            user_id: 用户ID

        Returns:
            执行结果
        """
        try:
            # 确定所需权限
            permissions = ["authenticated"]

            # 检查工具是否需要危险操作权限
            tool_info = tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")

            # 创建执行上下文
            context = ToolExecutionContext(
                agent_id=self.config.name,  # 使用 Agent 配置中的名称
                user_id=user_id,
                workspace="/tmp",  # 使用 /tmp 作为默认工作目录
                env_vars={},
                permissions=permissions,
            )

            # 执行工具
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
        执行 Skill

        Args:
            skill_name: Skill 名称（不带 / 前缀）
            arguments: 命令行参数
            user_id: 用户ID
            user_message: 原始用户消息
            conversation_history: 对话历史

        Returns:
            执行结果 {"success": bool, "response": str, "error": ...}
        """
        import os

        # 构建 Skill 执行上下文
        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "user_message": user_message,
            "conversation_history": conversation_history,
            "env_vars": {
                "USER": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
                "HOME": os.path.expanduser("~"),
                "PWD": os.getcwd(),
                "CLAUDE_SESSION_ID": f"session_{user_id}",
                "USER_ID": user_id,
            },
        }

        try:
            # 执行 Skill
            result = await self._skill_executor.execute(
                skill_name=skill_name,
                arguments=arguments,
                context=skill_context,
            )

            if result.success:
                # 如果 Skill 执行成功，返回内容
                response_content = result.content or ""

                # 如果 Skill 返回的是指令（direct mode），需要通过 LLM 生成最终回复
                if result.metadata.get("mode") == "direct":
                    # 使用 Skill 内容作为系统提示
                    system_prompt = response_content

                    messages = []
                    # 添加历史对话
                    for msg in conversation_history[-5:]:
                        messages.append(msg)
                    # 添加当前用户消息
                    messages.append({"role": "user", "content": user_message})

                    response_text = await self._call_llm(system_prompt, messages)
                    # 清理工具调用痕迹
                    response_text = clean_tool_artifacts(response_text)

                    return {
                        "success": True,
                        "response": response_text,
                        "mode": "direct_with_llm",
                    }
                else:
                    # Sub-agent 模式，清理工具调用痕迹后返回结果
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
        获取对话历史

        Args:
            user_id: 用户ID

        Returns:
            对话历史
        """
        active_session = self._resolve_session_id(user_id, session_id)
        return self._conversation_history.get(self._history_key(user_id, active_session), [])

    def clear_conversation_history(self, user_id: str, session_id: Optional[str] = None):
        """
        清空对话历史

        Args:
            user_id: 用户ID
        """
        active_session = self._resolve_session_id(user_id, session_id)
        key = self._history_key(user_id, active_session)
        self._conversation_history[key] = []
        self._tool_interactions[key] = []
        agent_logger.info(f"🗑️ Conversation history cleared | User: {user_id} | Session: {active_session}")
