"""
AgentAction definitions

Defines various actions that Agent can execute after processing perceptions
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatResponseAction:
    """
    Chat response action

    Generated when Agent receives user message to send a reply
    """
    chain_id: str
    user_id: str
    user_message: str
    session_id: Optional[str] = None
    intent: Optional[str] = None
    timestamp: float = 0

    def __post_init__(self):
        if self.timestamp == 0:
            import time
            self.timestamp = time.time()
