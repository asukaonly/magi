"""
Agent动作定义

定义Agent在处理感知后可以执行的各种动作
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatResponseAction:
    """
    聊天响应动作

    当Agent接收到用户消息后，生成此动作以发送回复
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
