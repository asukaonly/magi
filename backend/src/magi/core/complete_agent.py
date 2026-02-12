"""
Agent - 完整的Agent实现
"""
from typing import List, Optional, Any
from .agent import Agent, AgentConfig
from .master_agent import MasterAgent
from .task_agent import TaskAgent, WorkerAgent
from .loop import LoopEngine
from ..tools.registry import ToolRegistry
from ..awareness.manager import PerceptionManager
from ..processing.processor import SelfProcessingModule
from ..processing.capability_store import CapabilityStore
from ..llm.base import LLMAdapter
from ..events.backend import MessageBusBackend


class CompleteAgent(Agent):
    """
    完整的Agent实现

    整合所有组件：
    - 感知模块
    - 处理模块
    - 工具注册表
    - 循环引擎
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBusBackend,
        llm_adapter: LLMAdapter,
        memory: Optional[Any] = None,
    ):
        """
        初始化Agent

        Args:
            config: Agent配置
            message_bus: 消息总线
            llm_adapter: LLM适配器
            memory: 记忆系统（可选）
        """
        super().__init__(config)

        # 核心组件
        self.message_bus = message_bus
        self.llm = llm_adapter

        # 感知和处理
        self.perception_module = PerceptionManager()
        self.processing_module = SelfProcessingModule(llm_adapter)

        # 工具和记忆
        self.tool_registry = ToolRegistry()
        self.memory = memory  # 可以是 SelfMemory、OtherMemory 等
        self.capability_store = CapabilityStore()

        # 循环引擎
        self.loop_engine = LoopEngine(
            agent=self,
            strategy="continuous",  # 默认持续运行
        )

    async def execute_action(self, action):
        """执行动作"""
        # 临时占位实现
        return {"success": True}

    async def _on_start(self):
        """启动时的处理"""
        # 发布 Agent 启动事件
        from ..events.events import Event, EventTypes, EventLevel

        event = Event(
            type=EventTypes.AGENT_STARTED,
            data={
                "agent_id": self.config.name,
                "agent_type": self.__class__.__name__,
                "config": self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
            },
            source="agent",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

        # 启动循环引擎
        await self.loop_engine.start()

    async def _on_stop(self):
        """停止时的处理"""
        # 停止循环引擎
        await self.loop_engine.stop()

        # 发布 Agent 停止事件
        from ..events.events import Event, EventTypes, EventLevel

        event = Event(
            type=EventTypes.AGENT_STOPPED,
            data={
                "agent_id": self.config.name,
                "loop_count": self.loop_engine.get_stats()["loop_count"],
            },
            source="agent",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)
