"""
ChatAgent - 聊天Agent实现

处理用户消息，通过LLM生成回复，通过WebSocket推送
遵循正确的Agent架构：Sense-Plan-Act-Reflect
"""
import time
import logging
import re
from typing import Any, Optional, Dict, List
from ..core.complete_agent import CompleteAgent
from ..core.agent import AgentConfig
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter
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

logger = logging.getLogger(__name__)
agent_logger = get_agent_logger('chat')
llm_logger = get_llm_logger('chat')


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

    # 移除 {"name": "xxx", "arguments": {...}} 格式的工具调用
    text = re.sub(r'\s*{"name":\s*"[^"]+",\s*"arguments":\s*{[^}]*}}\s*', '', text)

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

        # 对话历史（内存存储）
        self._conversation_history: dict[str, list[dict]] = {}

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
        )

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

        log_chain_step(agent_logger, chain_id, "ACT", "Generating LLM response", "DEBUG")

        try:
            # 生成LLM回复
            response_text = await self._generate_response(user_id, user_message)

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
            }

            await manager.broadcast("agent_response", response_data, room=room)

            agent_logger.info(
                f"📤 Response delivered | User: {user_id} | Room: {room} | Length: {len(response_text)}"
            )

            return {
                "success": True,
                "response": response_text,
                "user_id": user_id,
            }

        except Exception as e:
            agent_logger.error(f"❌ Failed to generate response: {e}")
            return {"success": False, "error": str(e)}

    async def _generate_response(self, user_id: str, user_message: str) -> str:
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
        history = self._conversation_history.get(user_id, [])

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
            user_message=user_message,
            context_decision=context_decision,
            history=history,
        )

        # 计算任务持续时间
        duration = time.time() - start_time

        # 保存到对话历史
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        self._conversation_history[user_id] = history

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
            # 构建系统提示
            system_prompt = await self._build_system_prompt(
                tool_decision=None,  # 不再需要 tool_decision
                scenario=Scenario.CHAT,
                user_id=user_id,
                task_category=context_decision.intent,
            )

            # 如果没有选择工具，直接调用LLM
            if not context_decision.tools:
                agent_logger.info("ℹ️  No tools selected, using direct LLM response")

                messages = []
                for msg in history[-10:]:
                    messages.append(msg)
                messages.append({"role": "user", "content": user_message})

                response_text = await self._call_llm(system_prompt, messages)
                return clean_tool_artifacts(response_text)

            # 使用函数调用执行器
            agent_logger.info(f"🔧 Using function calling with tools: {context_decision.tools}")

            response_text = await self.function_calling_executor.execute_with_tools(
                user_message=user_message,
                system_prompt=system_prompt,
                selected_tools=context_decision.tools,
                user_id=user_id,
                conversation_history=history,
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
                )
                return await self._call_llm(system_prompt, messages)
            except Exception as e2:
                agent_logger.error(f"❌ Fallback LLM call also failed: {e2}")
                return "抱歉，我遇到了一些问题，请稍后再试。"

    async def _build_system_prompt(
        self,
        tool_decision: Optional[Dict],
        scenario: str = Scenario.CHAT,
        user_id: str = None,
        task_category: str = "chat"
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

        return full_prompt

    async def _call_llm(self, system_prompt: str, messages: list) -> str:
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

        # 判断LLM类型
        is_anthropic = hasattr(self.llm, '__class__') and 'anthropic' in self.llm.__class__.__module__.lower()
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
            if is_anthropic:
                # Anthropic API: 使用 system 参数
                response = await self.llm._client.messages.create(
                    model=model_name,
                    max_tokens=1000,
                    temperature=0.7,
                    system=system_prompt,
                    messages=messages,
                )
                response_text = response.content[0].text

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
            else:
                # OpenAI API: 添加 system 消息到消息列表
                full_messages = [{"role": "system", "content": system_prompt}] + messages
                response_text = await self.llm.chat(
                    messages=full_messages,
                    max_tokens=1000,
                    temperature=0.7,
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

    def get_conversation_history(self, user_id: str) -> list[dict]:
        """
        获取对话历史

        Args:
            user_id: 用户ID

        Returns:
            对话历史
        """
        return self._conversation_history.get(user_id, [])

    def clear_conversation_history(self, user_id: str):
        """
        清空对话历史

        Args:
            user_id: 用户ID
        """
        self._conversation_history[user_id] = []
        agent_logger.info(f"🗑️ Conversation history cleared | User: {user_id}")
