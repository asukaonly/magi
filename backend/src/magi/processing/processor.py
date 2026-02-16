"""
Self-processing Module - process perceptions and generate actions

Responsible for analyzing Perception and generating corresponding Actions
"""
from typing import Any, Optional
import logging
from ..awareness.base import Perception
from .actions import ChatResponseAction

logger = logging.getLogger(__name__)


class SelfprocessingModule:
    """
    Self-processing Module

    Analyzes perception input and generates corresponding action plans
    """

    def __init__(self, llm_adapter):
        """
        initializeprocessmodule

        Args:
            llm_adapter: LLMAdapter
        """
        self.llm = llm_adapter

    async def process(self, perception: Perception) -> Any:
        """
        processPerception，generationAction

        Args:
            perception: Perception input

        Returns:
            Action: Action plan
        """
        if not perception:
            return None

        # Dispatch processing based on perception type
        if perception.type == "text":
            return await self._process_text_perception(perception)
        elif perception.type == "event":
            return await self._process_event_perception(perception)
        elif perception.type == "sensor":
            return await self._process_sensor_perception(perception)
        else:
            logger.warning(f"Unknotttwn perception type: {perception.type}")
            return None

    async def _process_text_perception(self, perception: Perception) -> Optional[ChatResponseAction]:
        """
        process text perception (user message)

        Args:
            perception: Text perception

        Returns:
            ChatResponseAction: Chat response action
        """
        # Extract message data from perception.data
        message_data = perception.data.get("message", {})
        if not message_data:
            logger.warning("Text perception has nottt message data")
            return None

        user_message = message_data.get("message", "")
        user_id = message_data.get("user_id", "unknown")
        session_id = message_data.get("session_id")

        if not user_message:
            logger.warning("User message is empty")
            return None

        # Prefer to use correlation_id from message event to ensure consistent chain
        chain_id = message_data.get("correlation_id")
        if not chain_id:
            import uuid
            chain_id = str(uuid.uuid4())

        # Intent recognition (simplified version)
        intent = self._recognize_intent(user_message)

        logger.info(f"📝 processing text message | User: {user_id} | Intent: {intent} | Content: '{user_message[:50]}...'")

        # Generate chat response action
        return ChatResponseAction(
            chain_id=chain_id,
            user_id=user_id,
            user_message=user_message,
            session_id=session_id,
            intent=intent,
            timestamp=perception.timestamp,
        )

    async def _process_event_perception(self, perception: Perception) -> Any:
        """
        process event perception

        Args:
            perception: event perception

        Returns:
            Action or None
        """
        # event type processing (to be implemented)
        logger.debug(f"processing event perception: {perception.data}")
        return None

    async def _process_sensor_perception(self, perception: Perception) -> Any:
        """
        process sensor perception

        Args:
            perception: Sensor perception

        Returns:
            Action or None
        """
        # Sensor data processing (to be implemented)
        logger.debug(f"processing sensor perception: {perception.data}")
        return None

    def _recognize_intent(self, message: str) -> str:
        """
        Recognize user intent (simplified version)

        Args:
            message: User message

        Returns:
            Intent type
        """
        message_lower = message.lower()

        # Greeting
        if any(word in message_lower for word in ["你好", "hello", "hi", "嗨"]):
            return "GREETING"

        # Capability inquiry
        if any(word in message_lower for word in ["你能做什么", "你会什么", "capability", "help"]):
            return "CAPABILITY_INQUIRY"

        # Default to general query
        return "GENERAL_QUERY"
