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

    def _select_task_agent_by_load(self) -> Optional['TaskAgent']:
        """
        基于负载选择TaskAgent（负载均衡）

        选择pending任务数最少的TaskAgent

        Returns:
            选中的TaskAgent或None
        """
        if not self.task_agents:
            return None

        # 过滤出正在运行的TaskAgent
        running_agents = [
            agent for agent in self.task_agents
            if agent.state == AgentState.RUNNING
        ]

        if not running_agents:
            return None

        # 选择pending最少的TaskAgent
        selected = min(
            running_agents,
            key=lambda agent: agent.get_pending_count()
        )

        return selected

    async def dispatch_task(self, task: dict):
        """
        分发任务到TaskAgent（负载均衡）

        Args:
            task: 任务字典，包含task_id、type、data等
        """
        # 选择负载最低的TaskAgent
        task_agent = self._select_task_agent_by_load()

        if task_agent is None:
            # 没有可用的TaskAgent
            await self._publish_error_event(
                "TaskDispatch",
                f"No available TaskAgent for task {task.get('task_id')}"
            )
            return False

        # 增加TaskAgent的pending计数
        task_agent._pending_count += 1

        try:
            # 发布任务分配事件
            await self._publish_event(
                EventTypes.TASK_ASSIGNED,
                {
                    "task_id": task.get("task_id"),
                    "task_agent_id": task_agent.agent_id,
                    "task_type": task.get("type"),
                }
            )

            # TODO: 这里应该调用TaskAgent的方法来处理任务
            # 目前简化为事件发布
            # await task_agent.assign_task(task)

            return True

        except Exception as e:
            # 发生错误，减少pending计数
            task_agent._pending_count -= 1
            await self._publish_error_event(
                "TaskDispatch",
                f"Failed to dispatch task {task.get('task_id')}: {str(e)}"
            )
            return False

    def get_task_agents_load(self) -> dict:
        """
        获取所有TaskAgent的负载情况

        Returns:
            负载信息字典 {agent_id: pending_count}
        """
        return {
            agent.agent_id: agent.get_pending_count()
            for agent in self.task_agents
            if agent.state == AgentState.RUNNING
        }

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
