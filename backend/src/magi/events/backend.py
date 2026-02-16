"""
Message Bus - Abstract Backend Interface
"""
from abc import ABC, abstractmethod
from typing import Callable, Optional, List
from .events import Event


class MessageBusBackend(ABC):
    """
    Message Bus Backend Abstract Interface

    All message bus backends must implement this interface, supporting different storage implementations:
    - MemoryMessageBackend: Memory queue based on asyncio.priorityQueue
    - SQLiteMessageBackend: persistent queue based on aiosqlite
    - RedisMessageBackend: Distributed queue based on Redis Streams
    """

    @abstractmethod
    async def publish(self, Event: Event) -> bool:
        """
        Publish event to message bus

        Args:
            event: Event to publish

        Returns:
            bool: Whether the event was successfully published
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
        Subscribe to event

        Args:
            event_type: event type (e.g. "AgentStarted")
            handler: event handler function (async def handler(event: Event))
            propagation_mode: propagation mode ("broadcast" | "competing")
            filter_func: event filter function (only process when returns True)

        Returns:
            str: Subscription id
        """
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from event

        Args:
            subscription_id: Subscription id

        Returns:
            bool: Whether unsubscription was successful
        """
        pass

    @abstractmethod
    async def start(self):
        """Start message bus"""
        pass

    @abstractmethod
    async def stop(self):
        """Stop message bus (graceful shutdown)"""
        pass

    @abstractmethod
    async def get_stats(self) -> dict:
        """
        Get message bus statistics

        Returns:
            dict: Statistics info (queue length, dropped event count, subscriber count, etc.)
        """
        pass
