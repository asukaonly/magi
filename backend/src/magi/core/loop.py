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


class LoopState(Enum):
    """循环状态"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


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

    支持循环控制：
    - start(): 启动循环
    - stop(): 停止循环
    - pause(): 暂停循环
    - resume(): 恢复循环
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
        self._state = LoopState.STOPPED
        self._loop_task: Optional[asyncio.Task] = None
        self._pause_event: Optional[asyncio.Event] = None

        # 循环统计
        self._loop_count = 0
        self._phase_stats = {
            "sense": {"count": 0, "total_time": 0.0},
            "plan": {"count": 0, "total_time": 0.0},
            "act": {"count": 0, "total_time": 0.0},
            "reflect": {"count": 0, "total_time": 0.0},
        }
        self._error_count = 0
        self._last_error_time = None

    @property
    def state(self) -> LoopState:
        """获取循环状态"""
        return self._state

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._state == LoopState.RUNNING

    @property
    def is_paused(self) -> bool:
        """是否已暂停"""
        return self._state == LoopState.PAUSED

    async def start(self):
        """启动循环引擎"""
        if self._state == LoopState.RUNNING:
            return

        self._state = LoopState.RUNNING
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 初始未暂停

        self._loop_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        """停止循环引擎"""
        if self._state == LoopState.STOPPED:
            return

        self._state = LoopState.STOPPED

        if self._pause_event:
            self._pause_event.set()

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    async def pause(self):
        """暂停循环"""
        if self._state != LoopState.RUNNING:
            return

        self._state = LoopState.PAUSED

        if self._pause_event:
            self._pause_event.clear()

        await self._publish_event(EventTypes.LOOP_PAUSED, {})

    async def resume(self):
        """恢复循环"""
        if self._state != LoopState.PAUSED:
            return

        self._state = LoopState.RUNNING

        if self._pause_event:
            self._pause_event.set()

        await self._publish_event(EventTypes.LOOP_RESUMED, {})

    async def step_sense(self) -> List:
        """
        单步执行 - 只执行 Sense 阶段

        Returns:
            感知列表
        """
        return await self.sense()

    async def step_plan(self, perception) -> Any:
        """
        单步执行 - 只执行 Plan 阶段

        Args:
            perception: 感知输入

        Returns:
            Action: 行动计划
        """
        return await self.plan(perception)

    async def step_act(self, action) -> Any:
        """
        单步执行 - 只执行 Act 阶段

        Args:
            action: 要执行的动作

        Returns:
            ActionResult: 执行结果
        """
        return await self.act(action)

    async def step_reflect(self, perception, action, result):
        """
        单步执行 - 只执行 Reflect 阶段

        Args:
            perception: 感知
            action: 行动
            result: 结果
        """
        await self.reflect(perception, action, result)

    def get_stats(self) -> dict:
        """
        获取循环统计信息

        Returns:
            统计信息
        """
        return {
            "state": self._state.value,
            "loop_count": self._loop_count,
            "error_count": self._error_count,
            "phase_stats": self._phase_stats,
        }

    async def _main_loop(self):
        """主循环"""
        try:
            # 发布循环启动事件
            await self._publish_event(EventTypes.LOOP_STARTED, {})

            while self._state != LoopState.STOPPED:
                try:
                    # 检查是否暂停
                    if self._state == LoopState.PAUSED:
                        await self._wait_for_resume()
                        if self._state == LoopState.STOPPED:
                            break

                    # 1. Sense - 感知世界
                    sense_start = asyncio.get_event_loop().time()
                    perceptions = await self.sense()
                    sense_time = asyncio.get_event_loop().time() - sense_start

                    if not perceptions:
                        # 无感知输入，等待
                        await self._wait()
                        continue

                    # 2. Plan & Act - 处理每个感知
                    for perception in perceptions:
                        # 检查是否应该暂停
                        if self.strategy == LoopStrategy.STEP:
                            await self._wait()
                        elif self._state == LoopState.PAUSED:
                            await self._wait_for_resume()
                            if self._state == LoopState.STOPPED:
                                break

                        # Plan - 决策
                        plan_start = asyncio.get_event_loop().time()
                        action = await self.plan(perception)
                        plan_time = asyncio.get_event_loop().time() - plan_start

                        # Act - 执行
                        act_start = asyncio.get_event_loop().time()
                        result = await self.act(action)
                        act_time = asyncio.get_event_loop().time() - act_start

                        # Reflect - 反思
                        reflect_start = asyncio.get_event_loop().time()
                        await self.reflect(perception, action, result)
                        reflect_time = asyncio.get_event_loop().time() - reflect_start

                        # 更新统计
                        self._loop_count += 1

                    # WAVE模式下处理完一批后暂停
                    if self.strategy == LoopStrategy.WAVE:
                        await self._wait()

                except Exception as e:
                    # 错误处理：记录错误但继续循环
                    self._error_count += 1
                    self._last_error_time = asyncio.get_event_loop().time()
                    await self._publish_error_event(f"LoopEngine: {str(e)}")

                    # 检查是否需要告警
                    if self._error_count >= 5:
                        await self._publish_event(EventTypes.HEALTH_WARNING, {
                            "error": "Multiple errors in loop",
                            "error_count": self._error_count,
                        })

        finally:
            # 发布循环停止事件
            await self._publish_event(EventTypes.LOOP_COMPLETED, {
                "loop_count": self._loop_count,
                "error_count": self._error_count,
            })

    async def sense(self) -> List:
        """
        Sense - 感知世界

        Returns:
            List: 感知列表
        """
        # 发布阶段开始事件
        await self._publish_phase_event("sense", "started")

        # 从感知模块获取感知
        import time
        sense_start = time.time()
        perceptions = await self.agent.perception_module.perceive()

        # 发布感知接收事件
        from ..events.events import Event, EventTypes, EventLevel
        for perception in perceptions:
            correlation_id = self._extract_perception_correlation_id(perception)
            event = Event(
                type=EventTypes.PERCEPTION_RECEIVED,
                data={
                    "perception_type": perception.type,
                    "source": perception.source,
                    "data": perception.data,
                },
                source="LoopEngine",
                level=EventLevel.DEBUG,
                correlation_id=correlation_id,
            )
            await self.agent.message_bus.publish(event)

        # 更新统计
        self._phase_stats["sense"]["count"] += 1
        self._phase_stats["sense"]["total_time"] += time.time() - sense_start

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
        import time
        from ..events.events import Event, EventTypes, EventLevel

        # 发布阶段开始事件
        await self._publish_phase_event("plan", "started", {"perception_type": perception.type})

        # 使用自处理模块处理感知，生成行动
        plan_start = time.time()
        action = await self.agent.processing_module.process(perception)
        plan_time = time.time() - plan_start

        # 发布感知处理事件
        correlation_id = self._extract_perception_correlation_id(perception)
        event = Event(
            type=EventTypes.PERCEPTION_PROCESSED,
            data={
                "perception_type": perception.type,
                "action_type": type(action).__name__,
                "processing_time": plan_time,
            },
            source="LoopEngine",
            level=EventLevel.DEBUG,
            correlation_id=correlation_id,
        )
        await self.agent.message_bus.publish(event)

        # 更新统计
        self._phase_stats["plan"]["count"] += 1
        self._phase_stats["plan"]["total_time"] += plan_time

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
        import time
        from ..events.events import Event, EventTypes, EventLevel

        # 发布阶段开始事件
        await self._publish_phase_event("act", "started", {"action_type": type(action).__name__})

        # 执行动作
        act_start = time.time()
        result = await self.agent.execute_action(action)
        act_time = time.time() - act_start
        success = self._extract_result_success(result)
        response_text = self._extract_result_response(result)
        error_text = self._extract_result_error(result)

        # 发布动作执行事件
        event = Event(
            type=EventTypes.ACTION_EXECUTED,
            data={
                "action_type": type(action).__name__,
                "success": success,
                "execution_time": act_time,
                "response": response_text,
                "error": error_text,
                "user_id": getattr(action, "user_id", None),
                "session_id": getattr(action, "session_id", None),
            },
            source="LoopEngine",
            level=EventLevel.INFO,
            correlation_id=self._extract_action_correlation_id(action),
        )
        await self.agent.message_bus.publish(event)

        # 更新统计
        self._phase_stats["act"]["count"] += 1
        self._phase_stats["act"]["total_time"] += act_time

        # 发布阶段完成事件
        await self._publish_phase_event("act", "completed", {"success": success})

        return result

    async def reflect(self, perception, action, result):
        """
        Reflect - 反思学习

        Args:
            perception: 感知
            action: 行动
            result: 结果
        """
        import time
        from ..events.events import Event, EventTypes, EventLevel

        # 发布阶段开始事件
        await self._publish_phase_event("reflect", "started")

        # 更新记忆
        reflect_start = time.time()
        await self.agent.memory.store_experience(perception, action, result)
        reflect_time = time.time() - reflect_start

        # 更新能力成功率
        if hasattr(action, 'capability_id'):
            await self.agent.capability_store.update_success_rate(
                action.capability_id,
                getattr(result, 'success', True)
            )

        # 发布经验存储事件
        result_success = self._extract_result_success(result)
        event = Event(
            type=EventTypes.EXPERIENCE_STORED,
            data={
                "perception_type": perception.type,
                "action_type": type(action).__name__,
                "result_success": result_success,
                "reflection_time": reflect_time,
                "user_id": getattr(action, "user_id", None),
                "session_id": getattr(action, "session_id", None),
            },
            source="LoopEngine",
            level=EventLevel.DEBUG,
            correlation_id=self._extract_action_correlation_id(action),
        )
        await self.agent.message_bus.publish(event)

        # 更新统计
        self._phase_stats["reflect"]["count"] += 1
        self._phase_stats["reflect"]["total_time"] += reflect_time

        # 发布阶段完成事件
        await self._publish_phase_event("reflect", "completed")

    async def _wait_for_resume(self):
        """等待恢复"""
        if self._pause_event:
            await self._pause_event.wait()

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

    def _extract_perception_correlation_id(self, perception) -> Optional[str]:
        """Extract correlation ID from perception payload."""
        try:
            if getattr(perception, "type", "") == "text":
                msg = perception.data.get("message", {})
                if isinstance(msg, dict):
                    cid = msg.get("correlation_id")
                    if cid:
                        return cid
        except Exception:
            pass
        return None

    def _extract_action_correlation_id(self, action) -> Optional[str]:
        """Use action chain_id as event correlation ID when available."""
        cid = getattr(action, "chain_id", None)
        if isinstance(cid, str) and cid:
            return cid
        return None

    def _extract_result_success(self, result: Any) -> bool:
        """Support dict/object result structures."""
        if isinstance(result, dict):
            return bool(result.get("success", True))
        return bool(getattr(result, "success", True))

    def _extract_result_response(self, result: Any) -> str:
        """Extract response text from action result."""
        if isinstance(result, dict):
            value = result.get("response", "")
        else:
            value = getattr(result, "response", "")
        return value if isinstance(value, str) else str(value)

    def _extract_result_error(self, result: Any) -> str:
        """Extract error text from action result."""
        if isinstance(result, dict):
            value = result.get("error", "")
        else:
            value = getattr(result, "error", "")
        return value if isinstance(value, str) else str(value)
