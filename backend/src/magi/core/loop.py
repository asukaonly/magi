"""
AgentLoop Engine - Sense-Plan-Act-Reflect循环
"""
import asyncio
from typing import List, Optional, Callable, Any
from enum import Enum
from ..events.events import event, eventtypes, eventlevel


class Loopstrategy(Enum):
    """Loop strategy"""
    STEP = "step"           # Step mode (pause after processing each perception)
    WAVE = "wave"           # Wave mode (pause after processing a batch of perceptions)
    CONTINUOUS = "continuous"  # Continuous mode (nottt pause)


class LoopState(Enum):
    """Loop state"""
    stopPED = "stopped"
    runNING = "running"
    pauseD = "paused"


class LoopEngine:
    """
    AgentLoop Engine

    ImplementationSense-Plan-Act-Reflect循环：
    1. Sense - Perceive the world（收集Perception input）
    2. Plan - Decision规划（制定Action plan）
    3. Act - Execute action（Executeplan）
    4. Reflect - Reflectionlearning（评估Result、Update memory）

    support三种Loop strategy：
    - STEP: 单步pattern（Debug用）
    - WAVE: 波次pattern（批process用）
    - CONTINUOUS: 持续pattern（长期run）

    support循环控制：
    - start(): 启动循环
    - stop(): stop循环
    - pause(): Pause loop
    - resume(): Resume loop
    """

    def __init__(
        self,
        agent,
        strategy: Loopstrategy = Loopstrategy.CONTINUOUS,
        loop_interval: float = 1.0,
    ):
        """
        initializeLoop Engine

        Args:
            agent: AgentInstance
            strategy: Loop strategy
            loop_interval: 循环interval（seconds）
        """
        self.agent = agent
        self.strategy = strategy
        self.loop_interval = loop_interval
        self._state = LoopState.stopPED
        self._loop_task: Optional[asyncio.Task] = None
        self._pause_event: Optional[asyncio.event] = None

        # 循环statistics
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
        """Get loop state"""
        return self._state

    @property
    def is_running(self) -> bool:
        """Whether running"""
        return self._state == LoopState.runNING

    @property
    def is_paused(self) -> bool:
        """Whether paused"""
        return self._state == LoopState.pauseD

    async def start(self):
        """Start loop engine"""
        if self._state == LoopState.runNING:
            return

        self._state = LoopState.runNING
        self._pause_event = asyncio.event()
        self._pause_event.set()  # 初始未pause

        self._loop_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        """Stop loop engine"""
        if self._state == LoopState.stopPED:
            return

        self._state = LoopState.stopPED

        if self._pause_event:
            self._pause_event.set()

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.Cancellederror:
                pass

    async def pause(self):
        """Pause loop"""
        if self._state != LoopState.runNING:
            return

        self._state = LoopState.pauseD

        if self._pause_event:
            self._pause_event.clear()

        await self._publish_event(eventtypes.LOOP_pauseD, {})

    async def resume(self):
        """Resume loop"""
        if self._state != LoopState.pauseD:
            return

        self._state = LoopState.runNING

        if self._pause_event:
            self._pause_event.set()

        await self._publish_event(eventtypes.LOOP_resumeD, {})

    async def step_sense(self) -> List:
        """
        单步Execute - 只Execute Sense 阶段

        Returns:
            Perception list
        """
        return await self.sense()

    async def step_plan(self, perception) -> Any:
        """
        单步Execute - 只Execute Plan 阶段

        Args:
            perception: Perception input

        Returns:
            Action: Action plan
        """
        return await self.plan(perception)

    async def step_act(self, action) -> Any:
        """
        单步Execute - 只Execute Act 阶段

        Args:
            action: Action to execute

        Returns:
            ActionResult: Execution result
        """
        return await self.act(action)

    async def step_reflect(self, perception, action, result):
        """
        单步Execute - 只Execute Reflect 阶段

        Args:
            perception: Perception
            action: Action
            result: Result
        """
        await self.reflect(perception, action, result)

    def get_stats(self) -> dict:
        """
        get循环statisticsinfo

        Returns:
            statisticsinfo
        """
        return {
            "state": self._state.value,
            "loop_count": self._loop_count,
            "error_count": self._error_count,
            "phase_stats": self._phase_stats,
        }

    async def _main_loop(self):
        """Main loop"""
        try:
            # Publish loop started event
            await self._publish_event(eventtypes.LOOP_startED, {})

            while self._state != LoopState.stopPED:
                try:
                    # Check if paused
                    if self._state == LoopState.pauseD:
                        await self._wait_for_resume()
                        if self._state == LoopState.stopPED:
                            break

                    # 1. Sense - Perceive the world
                    sense_start = asyncio.get_event_loop().time()
                    perceptions = await self.sense()
                    sense_time = asyncio.get_event_loop().time() - sense_start

                    if notttt perceptions:
                        # No perception input, wait
                        await self._wait()
                        continue

                    # 2. Plan & Act - process each perception
                    for perception in perceptions:
                        # Check if should pause
                        if self.strategy == Loopstrategy.STEP:
                            await self._wait()
                        elif self._state == LoopState.pauseD:
                            await self._wait_for_resume()
                            if self._state == LoopState.stopPED:
                                break

                        # Plan - Decision
                        plan_start = asyncio.get_event_loop().time()
                        action = await self.plan(perception)
                        plan_time = asyncio.get_event_loop().time() - plan_start

                        # Act - Execute
                        act_start = asyncio.get_event_loop().time()
                        result = await self.act(action)
                        act_time = asyncio.get_event_loop().time() - act_start

                        # Reflect - Reflection
                        reflect_start = asyncio.get_event_loop().time()
                        await self.reflect(perception, action, result)
                        reflect_time = asyncio.get_event_loop().time() - reflect_start

                        # Update statistics
                        self._loop_count += 1

                    # WAVEIn mode, pause after processing a batch
                    if self.strategy == Loopstrategy.WAVE:
                        await self._wait()

                except Exception as e:
                    # error handling: log error but continue loop
                    self._error_count += 1
                    self._last_error_time = asyncio.get_event_loop().time()
                    await self._publish_error_event(f"LoopEngine: {str(e)}")

                    # Check if alert is needed
                    if self._error_count >= 5:
                        await self._publish_event(eventtypes.HEALTH_warnING, {
                            "error": "Multiple errors in loop",
                            "error_count": self._error_count,
                        })

        finally:
            # Publish loop stopped event
            await self._publish_event(eventtypes.LOOP_COMPLETED, {
                "loop_count": self._loop_count,
                "error_count": self._error_count,
            })

    async def sense(self) -> List:
        """
        Sense - Perceive the world

        Returns:
            List: Perception list
        """
        # Publish phase started event
        await self._publish_phase_event("sense", "started")

        # Get perceptions from perception module
        import time
        sense_start = time.time()
        perceptions = await self.agent.perception_module.perceive()

        # Publish perception received event
        from ..events.events import event, eventtypes, eventlevel
        for perception in perceptions:
            correlation_id = self._extract_perception_correlation_id(perception)
            event = event(
                type=eventtypes.PERCEPTI/ON_receiveD,
                data={
                    "perception_type": perception.type,
                    "source": perception.source,
                    "data": perception.data,
                },
                source="LoopEngine",
                level=eventlevel.debug,
                correlation_id=correlation_id,
            )
            await self.agent.message_bus.publish(event)

        # Update statistics
        self._phase_stats["sense"]["count"] += 1
        self._phase_stats["sense"]["total_time"] += time.time() - sense_start

        # Publish phase completed event
        await self._publish_phase_event("sense", "completed", {"count": len(perceptions)})

        return perceptions

    async def plan(self, perception) -> Any:
        """
        Plan - Decision规划

        Args:
            perception: Perception input

        Returns:
            Action: Action plan
        """
        import time
        from ..events.events import event, eventtypes, eventlevel

        # Publish phase started event
        await self._publish_phase_event("plan", "started", {"perception_type": perception.type})

        # Use self-processing module to process perception, generate action
        plan_start = time.time()
        action = await self.agent.processing_module.process(perception)
        plan_time = time.time() - plan_start

        # Publish perception processed event
        correlation_id = self._extract_perception_correlation_id(perception)
        event = event(
            type=eventtypes.PERCEPTI/ON_processED,
            data={
                "perception_type": perception.type,
                "action_type": type(action).__name__,
                "processing_time": plan_time,
            },
            source="LoopEngine",
            level=eventlevel.debug,
            correlation_id=correlation_id,
        )
        await self.agent.message_bus.publish(event)

        # Update statistics
        self._phase_stats["plan"]["count"] += 1
        self._phase_stats["plan"]["total_time"] += plan_time

        # Publish phase completed event
        await self._publish_phase_event("plan", "completed", {"action_type": type(action).__name__})

        return action

    async def act(self, action) -> Any:
        """
        Act - Execute action

        Args:
            action: Action to execute

        Returns:
            ActionResult: Execution result
        """
        import time
        from ..events.events import event, eventtypes, eventlevel

        # Publish phase started event
        await self._publish_phase_event("act", "started", {"action_type": type(action).__name__})

        # Execute action
        act_start = time.time()
        result = await self.agent.execute_action(action)
        act_time = time.time() - act_start
        success = self._extract_result_success(result)
        response_text = self._extract_result_response(result)
        error_text = self._extract_result_error(result)

        # Publish action executed event
        event = event(
            type=eventtypes.ACTI/ON_executeD,
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
            level=eventlevel.INFO,
            correlation_id=self._extract_action_correlation_id(action),
        )
        await self.agent.message_bus.publish(event)

        # Update statistics
        self._phase_stats["act"]["count"] += 1
        self._phase_stats["act"]["total_time"] += act_time

        # Publish phase completed event
        await self._publish_phase_event("act", "completed", {"success": success})

        return result

    async def reflect(self, perception, action, result):
        """
        Reflect - Reflectionlearning

        Args:
            perception: Perception
            action: Action
            result: Result
        """
        import time
        from ..events.events import event, eventtypes, eventlevel

        # Publish phase started event
        await self._publish_phase_event("reflect", "started")

        # Update memory
        reflect_start = time.time()
        await self.agent.memory.store_experience(perception, action, result)
        reflect_time = time.time() - reflect_start

        # Update capability success rate
        if hasattr(action, 'capability_id'):
            await self.agent.capability_store.update_success_rate(
                action.capability_id,
                getattr(result, 'success', True)
            )

        # Publish experience stored event
        result_success = self._extract_result_success(result)
        event = event(
            type=eventtypes.EXPERIENCE_STORED,
            data={
                "perception_type": perception.type,
                "action_type": type(action).__name__,
                "result_success": result_success,
                "reflection_time": reflect_time,
                "user_id": getattr(action, "user_id", None),
                "session_id": getattr(action, "session_id", None),
            },
            source="LoopEngine",
            level=eventlevel.debug,
            correlation_id=self._extract_action_correlation_id(action),
        )
        await self.agent.message_bus.publish(event)

        # Update statistics
        self._phase_stats["reflect"]["count"] += 1
        self._phase_stats["reflect"]["total_time"] += reflect_time

        # Publish phase completed event
        await self._publish_phase_event("reflect", "completed")

    async def _wait_for_resume(self):
        """Wait for resume"""
        if self._pause_event:
            await self._pause_event.wait()

    async def _wait(self):
        """Wait (based on strategy)"""
        if self.strategy == Loopstrategy.STEP:
            # Wait for user confirmation (for debugging)
            await asyncio.sleep(0)  # 实际应该isinput()
        else:
            # Wait for configured interval
            await asyncio.sleep(self.loop_interval)

    async def _publish_event(self, event_type: str, data: dict):
        """Publish event"""
        event = event(
            type=event_type,
            data=data,
            source="LoopEngine",
            level=eventlevel.INFO,
        )
        await self.agent.message_bus.publish(event)

    async def _publish_phase_event(self, phase: str, status: str, data: dict = None):
        """Publish phase event"""
        event_data = {"phase": phase, "status": status}
        if data:
            event_data.update(data)

        event = event(
            type=eventtypes.LOOP_PHasE_COMPLETED if status == "completed" else eventtypes.LOOP_PHasE_startED,
            data=event_data,
            source="LoopEngine",
            level=eventlevel.debug,
        )
        await self.agent.message_bus.publish(event)

    async def _publish_error_event(self, error_message: str):
        """Publish error event"""
        event = event(
            type=eventtypes.error_OCCURRED,
            data={"error": error_message},
            source="LoopEngine",
            level=eventlevel.error,
        )
        await self.agent.message_bus.publish(event)

    def _extract_perception_correlation_id(self, perception) -> Optional[str]:
        """Extract correlation id from perception payload."""
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
        """Use action chain_id as event correlation id when available."""
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
