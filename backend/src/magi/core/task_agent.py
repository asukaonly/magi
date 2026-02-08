"""
Agent核心 - TaskAgent和WorkerAgent实现
"""
import asyncio
from typing import Optional, Dict, Any
from .agent import Agent, AgentState, AgentConfig
from ..events.events import Event, EventTypes, EventLevel
from ..events.backend import MessageBusBackend


class TaskAgent(Agent):
    """
    TaskAgent - 任务编排和执行

    职责：
    - 扫描任务数据库
    - 任务分解
    - 工具匹配
    - 创建WorkerAgent执行任务
    """

    def __init__(
        self,
        agent_id: int,
        config: AgentConfig,
        message_bus: MessageBusBackend,
        llm_adapter,
    ):
        """
        初始化TaskAgent

        Args:
            agent_id: TaskAgent ID
            config: Agent配置
            message_bus: 消息总线
            llm_adapter: LLM适配器
        """
        super().__init__(config)
        self.agent_id = agent_id
        self.message_bus = message_bus
        self.llm = llm_adapter
        self._pending_count = 0  # 当前pending任务数
        self._scan_task: Optional[asyncio.Task] = None

    async def _on_start(self):
        """启动TaskAgent"""
        self._scan_task = asyncio.create_task(self._scan_tasks())

    async def _on_stop(self):
        """停止TaskAgent"""
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

    async def _scan_tasks(self):
        """
        扫描任务数据库

        循环扫描待处理任务并执行
        """
        while self.state == AgentState.RUNNING:
            try:
                # 这里应该从任务数据库获取任务
                # 暂时模拟
                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                # 发布错误事件
                await self._publish_error_event(f"TaskAgent-{self.agent_id}", str(e))

    def get_pending_count(self) -> int:
        """获取当前pending任务数"""
        return self._pending_count

    async def _publish_error_event(self, source: str, error_message: str):
        """发布错误事件"""
        event = Event(
            type=EventTypes.ERROR_OCCURRED,
            data={
                "source": source,
                "error": error_message,
            },
            source=f"TaskAgent-{self.agent_id}",
            level=EventLevel.ERROR,
        )
        await self.message_bus.publish(event)


class WorkerAgent(Agent):
    """
    WorkerAgent - 任务执行

    特点：
    - 轻量级、无状态
    - 执行完任务后销毁
    - 支持超时和重试
    """

    def __init__(
        self,
        task_id: str,
        task_data: Dict[str, Any],
        message_bus: MessageBusBackend,
        llm_adapter,
        timeout: float = 60.0,
    ):
        """
        初始化WorkerAgent

        Args:
            task_id: 任务ID
            task_data: 任务数据
            message_bus: 消息总线
            llm_adapter: LLM适配器
            timeout: 超时时间（秒）
        """
        config = AgentConfig(name=f"Worker-{task_id}", llm_config={})
        super().__init__(config)
        self.task_id = task_id
        self.task_data = task_data
        self.message_bus = message_bus
        self.llm = llm_adapter
        self.timeout = timeout

    async def _on_start(self):
        """执行任务"""
        try:
            # 使用asyncio.wait_for实现超时
            result = await asyncio.wait_for(
                self._execute_task(),
                timeout=self.timeout
            )

            # 任务完成
            await self._publish_event(
                EventTypes.TASK_COMPLETED,
                {
                    "task_id": self.task_id,
                    "result": result,
                }
            )

        except asyncio.TimeoutError:
            # 任务超时
            await self._publish_error_event(
                f"WorkerAgent-{self.task_id}",
                f"Task timeout after {self.timeout}s"
            )

        except Exception as e:
            # 任务失败
            await self._publish_error_event(
                f"WorkerAgent-{self.task_id}",
                str(e)
            )

    async def _execute_task(self) -> Dict[str, Any]:
        """
        执行任务

        Returns:
            任务执行结果
        """
        # 这里应该根据任务类型执行相应逻辑
        # 暂时返回模拟结果
        await asyncio.sleep(0.1)
        return {"status": "completed", "output": "Task executed"}

    async def _publish_event(self, event_type: str, data: dict):
        """发布事件"""
        event = Event(
            type=event_type,
            data=data,
            source=f"WorkerAgent-{self.task_id}",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

    async def _publish_error_event(self, source: str, error_message: str):
        """发布错误事件"""
        event = Event(
            type=EventTypes.TASK_FAILED,
            data={
                "source": source,
                "error": error_message,
            },
            source=source,
            level=EventLevel.ERROR,
        )
        await self.message_bus.publish(event)
