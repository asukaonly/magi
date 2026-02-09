"""
Agent核心 - Master Agent实现
"""
import asyncio
import psutil
import logging
from typing import List, Optional, Dict, Any
from .agent import Agent, AgentState, AgentConfig
from .task_database import TaskDatabase, TaskType, TaskPriority, TaskStatus
from .timeout_calculator import TimeoutCalculator
from ..events.events import Event, EventTypes, EventLevel
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter


logger = logging.getLogger(__name__)


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
        task_database: TaskDatabase,
        llm_adapter: LLMAdapter = None,
    ):
        """
        初始化Master Agent

        Args:
            config: Agent配置
            message_bus: 消息总线
            task_agents: TaskAgent列表
            task_database: 任务数据库
            llm_adapter: LLM适配器（用于任务识别）
        """
        super().__init__(config)
        self.message_bus = message_bus
        self.task_agents = task_agents
        self.task_database = task_database
        self.llm = llm_adapter
        self._main_loop_task: Optional[asyncio.Task] = None
        self._event_subscription_id: Optional[str] = None
        self._system_degraded = False  # 系统是否处于降级状态

    async def _on_start(self):
        """启动Master Agent"""
        # 启动消息总线
        await self.message_bus.start()

        # 初始化任务数据库
        await self.task_database._init_db()

        # 启动所有TaskAgent
        for task_agent in self.task_agents:
            await task_agent.start()

        # 订阅USER_MESSAGE事件用于任务识别
        self._event_subscription_id = await self.message_bus.subscribe(
            EventTypes.USER_MESSAGE,
            self._on_user_message,
            propagation_mode="broadcast",
        )

        # 启动主循环
        self._main_loop_task = asyncio.create_task(self._main_loop())

        # 发布启动事件
        await self._publish_event(
            EventTypes.AGENT_STARTED,
            {"agent_type": "master", "name": self.config.name}
        )

        logger.info("MasterAgent started")

    async def _on_stop(self):
        """停止Master Agent"""
        # 停止主循环
        if self._main_loop_task:
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                pass

        # 取消事件订阅
        if self._event_subscription_id:
            await self.message_bus.unsubscribe(self._event_subscription_id)

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

        logger.info("MasterAgent stopped")

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
                # 1. 健康检查（包括资源告警处理）
                await self._check_system_health()

                # 2. 扫描待处理任务并分发
                if not self._system_degraded:
                    await self._scan_and_dispatch_tasks()

                # 3. 发布心跳事件
                await self._publish_heartbeat_event()

                # 4. 等待一段时间
                await asyncio.sleep(self.config.loop_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MasterAgent main loop error: {e}")
                await self._publish_error_event("MasterAgent", str(e))

    async def _on_user_message(self, event: Event):
        """
        处理用户消息事件，识别并创建任务

        Args:
            event: USER_MESSAGE事件
        """
        if self._system_degraded:
            # 系统降级时不处理新任务
            return

        try:
            message_data = event.data
            user_message = message_data.get("message", "")
            user_id = message_data.get("user_id", "unknown")

            if not user_message:
                return

            # 识别任务
            task = await self._identify_task_from_message(user_message, user_id)

            if task:
                logger.info(f"Task identified: {task.task_id} from user {user_id}")

                # 发布任务创建事件
                await self._publish_event(
                    EventTypes.TASK_CREATED,
                    {
                        "task_id": task.task_id,
                        "task_type": task.type,
                        "user_id": user_id,
                    }
                )

        except Exception as e:
            logger.error(f"Error processing user message: {e}")
            await self._publish_error_event("TaskRecognition", str(e))

    async def _identify_task_from_message(
        self,
        message: str,
        user_id: str,
    ) -> Optional[Any]:
        """
        从用户消息中识别任务

        Args:
            message: 用户消息
            user_id: 用户ID

        Returns:
            识别的任务或None
        """
        # 简化版任务识别：基于关键词
        message_lower = message.lower()

        # 判断任务类型
        task_type = TaskType.QUERY
        priority = TaskPriority.NORMAL
        interaction_level = "none"  # none, low, medium, high

        # 检测关键词
        if any(word in message_lower for word in ["计算", "统计", "分析", "compute", "calculate"]):
            task_type = TaskType.COMPUTATION
        elif any(word in message_lower for word in ["帮我", "请", "能不能", "can you", "help"]):
            task_type = TaskType.INTERACTIVE
            interaction_level = "medium"

        # 检测优先级
        if any(word in message_lower for word in ["紧急", "urgent", "asap", "马上"]):
            priority = TaskPriority.URGENT
        elif any(word in message_lower for word in ["重要", "important", "priority"]):
            priority = TaskPriority.HIGH

        # 计算超时时间
        timeout = TimeoutCalculator.calculate(
            task_type=task_type,
            priority=priority,
        )

        # 创建任务
        task = await self.task_database.create_task(
            task_type=task_type,
            priority=priority,
            data={
                "message": message,
                "user_id": user_id,
                "interaction_level": interaction_level,
            },
            timeout=timeout,
        )

        return task

    async def _scan_and_dispatch_tasks(self):
        """扫描待处理任务并分发"""
        # 获取待处理任务
        pending_tasks = await self.task_database.get_pending_tasks(limit=10)

        for task in pending_tasks:
            # 检查是否已经分配
            if task.assigned_to:
                continue

            # 分发任务
            await self.dispatch_task(task)

    async def dispatch_task(self, task) -> bool:
        """
        分发任务到TaskAgent（负载均衡）

        Args:
            task: 任务对象

        Returns:
            是否成功分发
        """
        # 选择负载最低的TaskAgent
        task_agent = self._select_task_agent_by_load()

        if task_agent is None:
            # 没有可用的TaskAgent
            await self._publish_error_event(
                "TaskDispatch",
                f"No available TaskAgent for task {task.task_id}"
            )
            return False

        try:
            # 更新任务状态为处理中
            await self.task_database.update_task_status(
                task.task_id,
                TaskStatus.PROCESSING,
                assigned_to=str(task_agent.agent_id),
            )

            # 增加TaskAgent的pending计数
            task_agent._pending_count += 1

            # 发布任务分配事件
            await self._publish_event(
                EventTypes.TASK_ASSIGNED,
                {
                    "task_id": task.task_id,
                    "task_agent_id": task_agent.agent_id,
                    "task_type": task.type,
                }
            )

            # 通知TaskAgent处理任务
            await task_agent.assign_task(task)

            logger.info(
                f"Task {task.task_id} dispatched to TaskAgent-{task_agent.agent_id}"
            )

            return True

        except Exception as e:
            # 发生错误，恢复状态
            await self.task_database.update_task_status(
                task.task_id,
                TaskStatus.PENDING,
                assigned_to=None,
            )
            task_agent._pending_count -= 1
            await self._publish_error_event(
                "TaskDispatch",
                f"Failed to dispatch task {task.task_id}: {str(e)}"
            )
            return False

    async def _check_system_health(self):
        """
        系统健康检查

        检查项：
        - CPU使用率
        - 内存使用率
        - TaskAgent状态

        根据检查结果可能触发降级
        """
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # 内存使用率
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # 检查是否告警
        cpu_alert = cpu_percent > 90
        memory_alert = memory_percent > 90

        if cpu_alert or memory_alert:
            # 触发降级
            if not self._system_degraded:
                self._system_degraded = True
                await self._publish_event(
                    EventTypes.HEALTH_WARNING,
                    {
                        "reason": "System degraded",
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                    }
                )
                logger.warning(
                    f"System degraded: CPU={cpu_percent}%, Memory={memory_percent}%"
                )

        if cpu_alert:
            await self._publish_error_event(
                "SystemHealth",
                f"High CPU usage: {cpu_percent}%"
            )

        if memory_alert:
            await self._publish_error_event(
                "SystemHealth",
                f"High memory usage: {memory_percent}%"
            )

        # 资源恢复正常时解除降级
        if self._system_degraded and cpu_percent < 80 and memory_percent < 80:
            self._system_degraded = False
            await self._publish_event(
                EventTypes.HEALTH_WARNING,
                {"reason": "System recovered", "cpu_percent": cpu_percent}
            )
            logger.info("System recovered from degraded state")

    async def _publish_heartbeat_event(self):
        """发布心跳事件"""
        stats = {
            "agent_type": "master",
            "name": self.config.name,
            "state": self.state.value,
            "task_agents": len(self.task_agents),
            "degraded": self._system_degraded,
        }

        await self._publish_event("MasterAgentHeartbeat", stats)

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

    async def get_stats(self) -> Dict[str, Any]:
        """获取MasterAgent统计信息"""
        task_stats = await self.task_database.get_stats()

        return {
            "state": self.state.value,
            "degraded": self._system_degraded,
            "task_agents_load": self.get_task_agents_load(),
            "task_stats": task_stats,
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
