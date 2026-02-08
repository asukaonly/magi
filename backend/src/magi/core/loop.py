"""
Agent循环引擎 - Sense-Plan-Act-Reflect循环
"""
import asyncio
from typing import List, Optional, Callable, Any
from enum import Enum
from ..events.events import Event, EventTypes, EventLevel


class LoopStrategy(Enum):
    """循环策略"""
    STEP = "step"           # 单步模式（每次处理一个感知后暂停）
    WAVE = "wave"           # 波次模式（处理一批感知后暂停）
    CONTINUOUS = "continuous"  # 持续模式（不暂停）


class LoopEngine:
    """
    Agent循环引擎

    实现Sense-Plan-Act-Reflect循环：
    1. Sense - 感知世界（收集感知输入）
    2. Plan - 决策规划（制定行动计划）
    3. Act - 执行动作（执行计划）
    4. Reflect - 反思学习（评估结果、更新记忆）

    支持三种循环策略：
    - STEP: 单步模式（调试用）
    - WAVE: 波次模式（批处理用）
    - CONTINUOUS: 持续模式（长期运行）
    """

    def __init__(
        self,
        agent,
        strategy: LoopStrategy = LoopStrategy.CONTINUOUS,
        loop_interval: float = 1.0,
    ):
        """
        初始化循环引擎

        Args:
            agent: Agent实例
            strategy: 循环策略
            loop_interval: 循环间隔（秒）
        """
        self.agent = agent
        self.strategy = strategy
        self.loop_interval = loop_interval
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动循环引擎"""
        if self._running:
            return

        self._running = True
        self._loop_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        """停止循环引擎"""
        if not self._running:
            return

        self._running = False

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def _main_loop(self):
        """主循环"""
        try:
            # 发布循环启动事件
            await self._publish_event(EventTypes.LOOP_STARTED, {})

            while self._running:
                try:
                    # 1. Sense - 感知世界
                    perceptions = await self.sense()

                    if not perceptions:
                        # 无感知输入，等待
                        await self._wait()
                        continue

                    # 2. Plan & Act - 处理每个感知
                    for perception in perceptions:
                        # 检查是否应该暂停
                        if self.strategy == LoopStrategy.STEP:
                            await self._wait()

                        # Plan - 决策
                        action = await self.plan(perception)

                        # Act - 执行
                        result = await self.act(action)

                        # Reflect - 反思
                        await self.reflect(perception, action, result)

                    # WAVE模式下处理完一批后暂停
                    if self.strategy == LoopStrategy.WAVE:
                        await self._wait()

                except Exception as e:
                    # 错误处理：记录错误但继续循环
                    await self._publish_error_event(f"LoopEngine: {str(e)}")

        finally:
            # 发布循环停止事件
            await self._publish_event(EventTypes.LOOP_COMPLETED, {})

    async def sense(self) -> List:
        """
        Sense - 感知世界

        Returns:
            List: 感知列表
        """
        # 发布阶段开始事件
        await self._publish_phase_event("sense", "started")

        # 从感知模块获取感知
        perceptions = await self.agent.perception_module.perceive()

        # 发布阶段完成事件
        await self._publish_phase_event("sense", "completed", {"count": len(perceptions)})

        return perceptions

    async def plan(self, perception) -> Any:
        """
        Plan - 决策规划

        Args:
            perception: 感知输入

        Returns:
            Action: 行动计划
        """
        # 发布阶段开始事件
        await self._publish_phase_event("plan", "started", {"perception_type": type(perception).__name__})

        # 使用自处理模块处理感知，生成行动
        action = await self.agent.processing_module.process(perception)

        # 发布阶段完成事件
        await self._publish_phase_event("plan", "completed", {"action_type": type(action).__name__})

        return action

    async def act(self, action) -> Any:
        """
        Act - 执行动作

        Args:
            action: 要执行的动作

        Returns:
            ActionResult: 执行结果
        """
        # 发布阶段开始事件
        await self._publish_phase_event("act", "started", {"action_type": type(action).__name__})

        # 执行动作
        result = await self.agent.execute_action(action)

        # 发布阶段完成事件
        await self._publish_phase_event("act", "completed", {"success": getattr(result, 'success', True)})

        return result

    async def reflect(self, perception, action, result):
        """
        Reflect - 反思学习

        Args:
            perception: 感知
            action: 行动
            result: 结果
        """
        # 发布阶段开始事件
        await self._publish_phase_event("reflect", "started")

        # 更新记忆
        await self.agent.memory.store_experience(perception, action, result)

        # 更新能力成功率
        if hasattr(action, 'capability_id'):
            await self.agent.capability_store.update_success_rate(
                action.capability_id,
                getattr(result, 'success', True)
            )

        # 发布阶段完成事件
        await self._publish_phase_event("reflect", "completed")

    async def _wait(self):
        """等待（根据策略）"""
        if self.strategy == LoopStrategy.STEP:
            # 等待用户确认（调试用）
            await asyncio.sleep(0)  # 实际应该是input()
        else:
            # 按配置的间隔等待
            await asyncio.sleep(self.loop_interval)

    async def _publish_event(self, event_type: str, data: dict):
        """发布事件"""
        event = Event(
            type=event_type,
            data=data,
            source="LoopEngine",
            level=EventLevel.INFO,
        )
        await self.agent.message_bus.publish(event)

    async def _publish_phase_event(self, phase: str, status: str, data: dict = None):
        """发布阶段事件"""
        event_data = {"phase": phase, "status": status}
        if data:
            event_data.update(data)

        event = Event(
            type=EventTypes.LOOP_PHASE_COMPLETED if status == "completed" else EventTypes.LOOP_PHASE_STARTED,
            data=event_data,
            source="LoopEngine",
            level=EventLevel.DEBUG,
        )
        await self.agent.message_bus.publish(event)

    async def _publish_error_event(self, error_message: str):
        """发布错误事件"""
        event = Event(
            type=EventTypes.ERROR_OCCURRED,
            data={"error": error_message},
            source="LoopEngine",
            level=EventLevel.ERROR,
        )
        await self.agent.message_bus.publish(event)
