"""
ChatAgent - 聊天Agent实现

处理用户消息，通过LLM生成回复，通过WebSocket推送
遵循正确的Agent架构：Sense-Plan-Act-Reflect
"""
import time
import logging
from typing import Any, Optional, Dict
from ..core.complete_agent import CompleteAgent
from ..core.agent import AgentConfig
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter
from ..utils.agent_logger import get_agent_logger, log_chain_start, log_chain_step, log_chain_end
from ..utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response
from ..tools.registry import ToolRegistry, tool_registry
from ..tools.selector import ToolSelector
from ..tools.schema import ToolExecutionContext

logger = logging.getLogger(__name__)
agent_logger = get_agent_logger('chat')
llm_logger = get_llm_logger('chat')


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
    ):
        """
        初始化ChatAgent

        Args:
            config: Agent配置
            message_bus: 消息总线
            llm_adapter: LLM适配器
        """
        super().__init__(config, message_bus, llm_adapter)

        # 对话历史（内存存储）
        self._conversation_history: dict[str, list[dict]] = {}

        # 工具选择器（五步决策流程）
        self.tool_selector = ToolSelector(
            tool_registry=tool_registry,
            llm_adapter=llm_adapter,
        )

        agent_logger.info(f"🤖 ChatAgent initialized | Name: {config.name}")

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
        生成LLM回复（集成工具调用）

        流程：
        1. 工具选择（五步决策）
        2. 如果需要工具，执行工具并获取结果
        3. 将工具结果反馈给LLM生成最终回复

        Args:
            user_id: 用户ID
            user_message: 用户消息

        Returns:
            LLM回复
        """
        # 获取对话历史
        history = self._conversation_history.get(user_id, [])

        # Step 1: 工具选择（五步决策流程）
        # 构建环境上下文
        import os
        import platform
        selector_context = {
            "os": platform.system(),  # Darwin, Linux, Windows
            "os_version": platform.release(),
            "current_user": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
            "home_dir": os.path.expanduser("~"),  # 自动检测正确的 home 目录
            "current_dir": os.getcwd(),
        }

        tool_decision = await self.tool_selector.select_tool(user_message, selector_context)

        agent_logger.info(f"🔍 Tool decision result: {tool_decision}")

        tool_result = None
        if tool_decision and tool_decision.get("tool"):
            # Step 2: 执行工具
            agent_logger.info(f"🔧 Tool selected | Tool: {tool_decision['tool']} | Parameters: {tool_decision.get('parameters', {})}")

            try:
                tool_result = await self._execute_tool(
                    tool_decision["tool"],
                    tool_decision.get("parameters", {}),
                    user_id
                )

                if tool_result["success"]:
                    agent_logger.info(f"✅ Tool executed | Result: {str(tool_result['data'])[:100]}...")
                else:
                    agent_logger.error(f"❌ Tool failed | Error: {tool_result.get('error', 'Unknown')}")
            except Exception as e:
                agent_logger.error(f"❌ Tool execution exception: {e}")
                import traceback
                agent_logger.error(f"Traceback: {traceback.format_exc()}")
                tool_result = {"success": False, "error": str(e), "data": None}
        else:
            agent_logger.info("ℹ️  No tool selected, using direct LLM response")

        # Step 3: 构建LLM消息
        system_prompt = self._build_system_prompt(tool_decision)

        messages = []

        # 添加历史对话（最近10轮）
        for msg in history[-10:]:
            messages.append(msg)

        # 添加当前用户消息
        messages.append({
            "role": "user",
            "content": user_message,
        })

        # 如果有工具结果，添加工具调用信息
        if tool_result and tool_result["success"]:
            tool_info = (
                f"\n\n[工具执行结果]\n"
                f"工具: {tool_decision['tool']}\n"
                f"参数: {tool_decision.get('parameters', {})}\n"
                f"执行结果: {tool_result['data']}"
            )
            messages.append({
                "role": "system",
                "content": tool_info
            })
        elif tool_decision and tool_decision.get("tool"):
            # 工具选择存在但没有成功执行
            if tool_result and not tool_result["success"]:
                error_info = (
                    f"\n\n[工具执行失败]\n"
                    f"工具: {tool_decision['tool']}\n"
                    f"错误: {tool_result.get('error', 'Unknown error')}"
                )
                messages.append({
                    "role": "system",
                    "content": error_info
                })

        # Step 4: 调用LLM生成最终回复
        response_text = await self._call_llm(system_prompt, messages)

        # 保存到对话历史
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": response_text})
        self._conversation_history[user_id] = history

        return response_text

    def _build_system_prompt(self, tool_decision: Optional[Dict]) -> str:
        """
        构建系统提示

        Args:
            tool_decision: 工具决策信息

        Returns:
            系统提示
        """
        base_prompt = (
            "你是 Magi AI Agent Framework 的智能助手。"
            "你的任务是帮助用户解答问题、提供建议和执行任务。"
            "请用简洁、友好的方式回复。"
        )

        if tool_decision and tool_decision.get("tool"):
            tool_name = tool_decision.get("tool")
            base_prompt += (
                f"\n\n[系统提示] 已为用户调用工具: {tool_name}"
                f"\n如果下方有工具调用结果，请基于结果回答用户问题。"
                f"\n如果没有工具调用结果，说明工具执行失败，请告知用户。"
            )

        return base_prompt

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
