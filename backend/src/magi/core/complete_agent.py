"""
Agent - Complete Agent implementation
"""
from typing import List, Optional, Any
from .agent import Agent, AgentConfig
from .master_agent import MasterAgent
from .task_agent import TaskAgent, WorkerAgent
from .loop import LoopEngine
from ..tools.registry import ToolRegistry
from ..awareness.manager import PerceptionManager
from ..processing.processor import SelfprocessingModule
from ..processing.capability_store import CapabilityStore
from ..llm.base import LLMAdapter
from ..events.backend import MessageBusBackend


class CompleteAgent(Agent):
    """
    Complete Agent implementation

    Integrates all components:
    - Perception module
    - processing module
    - Tool registry
    - Loop engine
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBusBackend,
        llm_adapter: LLMAdapter,
        memory: Optional[Any] = None,
    ):
        """
        initialize Agent

        Args:
            config: Agent configuration
            message_bus: Message bus
            llm_adapter: LLM adapter
            memory: Memory system (optional)
        """
        super().__init__(config)

        # Core components
        self.message_bus = message_bus
        self.llm = llm_adapter

        # Perception and processing
        self.perception_module = PerceptionManager()
        self.processing_module = SelfprocessingModule(llm_adapter)

        # Tools and memory
        self.tool_registry = ToolRegistry()
        self.memory = memory  # Can be SelfMemory, OtherMemory, etc.
        self.capability_store = CapabilityStore()

        # Loop engine
        self.loop_engine = LoopEngine(
            agent=self,
            strategy="continuous",  # Default continuous running
        )

    async def execute_action(self, action):
        """Execute action"""
        # Temporary placeholder implementation
        return {"success": True}

    async def _on_start(self):
        """processing on startup"""
        # Publish Agent startup event
        from ..events.events import event, eventtypes, eventlevel

        event = Event(
            type=EventTypes.AGENT_startED,
            data={
                "agent_id": self.config.name,
                "agent_type": self.__class__.__name__,
                "config": self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
            },
            source="agent",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

        # Start loop engine
        await self.loop_engine.start()

    async def _on_stop(self):
        """processing on shutdown"""
        # Stop loop engine
        await self.loop_engine.stop()

        # Publish Agent shutdown event
        from ..events.events import event, eventtypes, eventlevel

        event = Event(
            type=EventTypes.AGENT_stopPED,
            data={
                "agent_id": self.config.name,
                "loop_count": self.loop_engine.get_stats()["loop_count"],
            },
            source="agent",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)
