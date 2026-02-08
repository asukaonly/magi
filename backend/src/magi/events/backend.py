"""
消息总线 - 抽象后端接口
"""
from abc import ABC, abstractmethod
from typing import Callable, Optional, List
from .events import Event


class MessageBusBackend(ABC):
    """
    消息总线后端抽象接口

    所有消息总线后端必须实现此接口，支持不同的存储实现：
    - MemoryMessageBackend: 基于asyncio.PriorityQueue的内存队列
    - SQLiteMessageBackend: 基于aiosqlite的持久化队列
    - RedisMessageBackend: 基于Redis Streams的分布式队列
    """

    @abstractmethod
    async def publish(self, event: Event) -> bool:
        """
        发布事件到消息总线

        Args:
            event: 要发布的事件

        Returns:
            bool: 是否成功发布
        """
        pass

    @abstractmethod
    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: str = "broadcast",
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """
        订阅事件

        Args:
            event_type: 事件类型（如 "AgentStarted"）
            handler: 事件处理函数（async def handler(event: Event)）
            propagation_mode: 传播模式（"broadcast" | "competing"）
            filter_func: 事件过滤函数（返回True才处理）

        Returns:
            str: 订阅ID
        """
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅

        Args:
            subscription_id: 订阅ID

        Returns:
            bool: 是否成功取消
        """
        pass

    @abstractmethod
    async def start(self):
        """启动消息总线"""
        pass

    @abstractmethod
    async def stop(self):
        """停止消息总线（优雅关闭）"""
        pass

    @abstractmethod
    async def get_stats(self) -> dict:
        """
        获取消息总线统计信息

        Returns:
            dict: 统计信息（队列长度、丢弃事件数、订阅者数量等）
        """
        pass
