"""
自处理模块 - 处理感知并生成行动

负责分析Perception并生成对应的Action
"""
from typing import Any, Optional
import logging
from ..awareness.base import Perception
from .actions import ChatResponseAction

logger = logging.getLogger(__name__)


class SelfProcessingModule:
    """
    自处理模块

    分析感知输入，生成对应的行动计划
    """

    def __init__(self, llm_adapter):
        """
        初始化处理模块

        Args:
            llm_adapter: LLM适配器
        """
        self.llm = llm_adapter

    async def process(self, perception: Perception) -> Any:
        """
        处理感知，生成行动

        Args:
            perception: 感知输入

        Returns:
            Action: 行动计划
        """
        if not perception:
            return None

        # 根据感知类型分发处理
        if perception.type == "text":
            return await self._process_text_perception(perception)
        elif perception.type == "event":
            return await self._process_event_perception(perception)
        elif perception.type == "sensor":
            return await self._process_sensor_perception(perception)
        else:
            logger.warning(f"Unknown perception type: {perception.type}")
            return None

    async def _process_text_perception(self, perception: Perception) -> Optional[ChatResponseAction]:
        """
        处理文本感知（用户消息）

        Args:
            perception: 文本感知

        Returns:
            ChatResponseAction: 聊天响应动作
        """
        import uuid

        # 从perception.data中提取消息数据
        message_data = perception.data.get("message", {})
        if not message_data:
            logger.warning("Text perception has no message data")
            return None

        user_message = message_data.get("message", "")
        user_id = message_data.get("user_id", "unknown")

        if not user_message:
            logger.warning("User message is empty")
            return None

        # 生成链路ID用于追踪
        chain_id = str(uuid.uuid4())[:8]

        # 意图识别（简化版）
        intent = self._recognize_intent(user_message)

        logger.info(f"📝 Processing text message | User: {user_id} | Intent: {intent} | Content: '{user_message[:50]}...'")

        # 生成聊天响应动作
        return ChatResponseAction(
            chain_id=chain_id,
            user_id=user_id,
            user_message=user_message,
            intent=intent,
            timestamp=perception.timestamp,
        )

    async def _process_event_perception(self, perception: Perception) -> Any:
        """
        处理事件感知

        Args:
            perception: 事件感知

        Returns:
            Action or None
        """
        # 事件类型的处理（待实现）
        logger.debug(f"Processing event perception: {perception.data}")
        return None

    async def _process_sensor_perception(self, perception: Perception) -> Any:
        """
        处理传感器感知

        Args:
            perception: 传感器感知

        Returns:
            Action or None
        """
        # 传感器数据的处理（待实现）
        logger.debug(f"Processing sensor perception: {perception.data}")
        return None

    def _recognize_intent(self, message: str) -> str:
        """
        识别用户意图（简化版）

        Args:
            message: 用户消息

        Returns:
            意图类型
        """
        message_lower = message.lower()

        # 问候
        if any(word in message_lower for word in ["你好", "hello", "hi", "嗨"]):
            return "GREETING"

        # 能力询问
        if any(word in message_lower for word in ["你能做什么", "你会什么", "能力", "help"]):
            return "CAPABILITY_INQUIRY"

        # 默认为一般查询
        return "GENERAL_QUERY"
