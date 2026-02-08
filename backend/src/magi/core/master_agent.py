"""
Agent核心 - Master Agent实现
"""
import asyncio
import psutil
from typing import List, Optional
from .agent import Agent, AgentState, AgentConfig
from ..events.events import Event, EventTypes, EventLevel
from ..events.backend import MessageBusBackend


class MasterAgent(Agent):
    """
    Master Agent - 系统管理和任务分发

    职责：
    - 任务识别和分发
    - 系统健康检查
    - TaskAgent管理
    - 整体协调
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBusBackend,
        task_agents: List,
    ):
        """
        初始化Master Agent

        Args:
            config: Agent配置
            message_bus: 消息总线
            task_agents: TaskAgent列表
        """
        super().__init__(config)
        self.message_bus = message_bus
        self.task_agents = task_agents
        self._main_loop_task: Optional[asyncio.Task] = None

    async def _on_start(self):
        """启动Master Agent"""
        # 启动消息总线
        await self.message_bus.start()

        # 启动所有TaskAgent
        for task_agent in self.task_agents:
            await task_agent.start()

        # 启动主循环
        self._main_loop_task = asyncio.create_task(self._main_loop())

        # 发布启动事件
        await self._publish_event(
            EventTypes.AGENT_STARTED,
            {"agent_type": "master", "name": self.config.name}
        )

    async def _on_stop(self):
        """停止Master Agent"""
        # 停止主循环
        if self._main_loop_task:
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                pass

        # 停止所有TaskAgent（逆序）
        for task_agent in reversed(self.task_agents):
            await task_agent.stop()

        # 停止消息总线
        await self.message_bus.stop()

        # 发布停止事件
        await self._publish_event(
            EventTypes.AGENT_STOPPED,
            {"agent_type": "master", "name": self.config.name}
        )

    async def _main_loop(self):
        """
        主循环

        步骤：
        1. 获取感知
        2. 识别任务
        3. 分发任务
        4. 健康检查
        """
        while self.state == AgentState.RUNNING:
            try:
                # 1. 健康检查
                await self._check_system_health()

                # 2. 等待一段时间
                await asyncio.sleep(self.config.loop_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                # 发布错误事件
                await self._publish_error_event("MasterAgent", str(e))

    async def _check_system_health(self):
        """
        系统健康检查

        检查项：
        - CPU使用率
        - 内存使用率
        - TaskAgent状态
        """
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # 内存使用率
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # 检查是否告警
        if cpu_percent > 90:
            await self._publish_error_event(
                "SystemHealth",
                f"High CPU usage: {cpu_percent}%"
            )

        if memory_percent > 90:
            await self._publish_error_event(
                "SystemHealth",
                f"High memory usage: {memory_percent}%"
            )

    async def _publish_event(self, event_type: str, data: dict):
        """发布事件"""
        event = Event(
            type=event_type,
            data=data,
            source="MasterAgent",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

    async def _publish_error_event(self, source: str, error_message: str):
        """发布错误事件"""
        event = Event(
            type=EventTypes.ERROR_OCCURRED,
            data={
                "source": source,
                "error": error_message,
            },
            source="MasterAgent",
            level=EventLevel.ERROR,
        )
        await self.message_bus.publish(event)
