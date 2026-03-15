"""
Agent Loop Engine - Sense-Plan-Act-Reflect loop
"""
import asyncio
import time
from typing import List, Optional, Callable, Any
from enum import Enum
from ..events.events import Event, EventTypes, EventLevel


class LoopStrategy(Enum):
    """Loop strategy"""
    STEP = "step"           # Step mode (pause after processing each perception)
    WAVE = "wave"           # Wave mode (pause after processing a batch of perceptions)
    CONTINUOUS = "continuous"  # Continuous mode (not pause)


class LoopState(Enum):
    """Loop state"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class LoopEngine:
    """
    Agent Loop Engine

    Implements the Sense-Plan-Act-Reflect loop:
    1. Sense - Perceive the world (collect perceptual input)
    2. Plan - Decision planning (formulate action plan)
    3. Act - Execute action (carry out the plan)
    4. Reflect - Reflection and learning (evaluate results, update memory)

    Supports three loop strategies:
    - STEP: Single-step mode (for debugging)
    - WAVE: Wave mode (for batch processing)
    - CONTINUOUS: Continuous mode (for long-running execution)

    Supports loop control:
    - start(): Start the loop
    - stop(): Stop the loop
    - pause(): Pause loop
    - resume(): Resume loop
    """

    def __init__(
        self,
        agent,
        strategy: LoopStrategy = LoopStrategy.CONTINUOUS,
        loop_interval: float = 1.0,
    ):
        """
        Initialize Loop Engine

        Args:
            agent: Agent instance
            strategy: Loop strategy
            loop_interval: Loop interval in seconds
        """
        self.agent = agent
        self.strategy = strategy
        self.loop_interval = loop_interval
        self._state = LoopState.STOPPED
        self._loop_task: Optional[asyncio.Task] = None
        self._pause_event: Optional[asyncio.Event] = None

        # Loop statistics
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
        return self._state == LoopState.RUNNING

    @property
    def is_paused(self) -> bool:
        """Whether paused"""
        return self._state == LoopState.PAUSED

    async def start(self):
        """Start loop engine"""
        if self._state == LoopState.RUNNING:
            return

        self.reset_stats()
        self._state = LoopState.RUNNING
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Initially not paused

        self._loop_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        """Stop loop engine"""
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
        """Pause loop"""
        if self._state != LoopState.RUNNING:
            return

        self._state = LoopState.PAUSED

        if self._pause_event:
            self._pause_event.clear()

        await self._publish_event(EventTypes.LOOP_PAUSED, {})

    async def resume(self):
        """Resume loop"""
        if self._state != LoopState.PAUSED:
            return

        self._state = LoopState.RUNNING

        if self._pause_event:
            self._pause_event.set()

        await self._publish_event(EventTypes.LOOP_RESUMED, {})

    async def step_sense(self) -> List:
        """
        Single-step execution - execute only the Sense phase

        Returns:
            Perception list
        """
        return await self.sense()

    async def step_plan(self, perception) -> Any:
        """
        Single-step execution - execute only the Plan phase

        Args:
            perception: Perception input

        Returns:
            Action: Action plan
        """
        return await self.plan(perception)

    async def step_act(self, action) -> Any:
        """
        Single-step execution - execute only the Act phase

        Args:
            action: Action to execute

        Returns:
            ActionResult: Execution result
        """
        return await self.act(action)

    async def step_reflect(self, perception, action, result):
        """
        Single-step execution - execute only the Reflect phase

        Args:
            perception: Perception
            action: Action
            result: Result
        """
        await self.reflect(perception, action, result)

    def get_stats(self) -> dict:
        """
        Get loop statistics

        Returns:
            Statistics dictionary
        """
        return {
            "state": self._state.value,
            "loop_count": self._loop_count,
            "error_count": self._error_count,
            "phase_stats": self._phase_stats,
        }

    def reset_stats(self) -> None:
        """Reset accumulated statistics to prevent unbounded growth."""
        self._loop_count = 0
        self._error_count = 0
        for phase in self._phase_stats.values():
            phase["count"] = 0
            phase["total_time"] = 0.0

    async def _main_loop(self):
        """Main loop"""
        try:
            # Publish loop started event
            await self._publish_event(EventTypes.LOOP_STARTED, {})

            while self._state != LoopState.STOPPED:
                try:
                    # Check if paused
                    if self._state == LoopState.PAUSED:
                        await self._wait_for_resume()
                        if self._state == LoopState.STOPPED:
                            break

                    # 1. Sense - Perceive the world
                    sense_start = asyncio.get_event_loop().time()
                    perceptions = await self.sense()
                    sense_time = asyncio.get_event_loop().time() - sense_start

                    if not perceptions:
                        # No perception input, wait
                        await self._wait()
                        continue

                    # 2. Plan & Act - process each perception
                    for perception in perceptions:
                        # Check if should pause
                        if self.strategy == LoopStrategy.STEP:
                            await self._wait()
                        elif self._state == LoopState.PAUSED:
                            await self._wait_for_resume()
                            if self._state == LoopState.STOPPED:
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
                    if self.strategy == LoopStrategy.WAVE:
                        await self._wait()

                except Exception as e:
                    # error handling: log error but continue loop
                    self._error_count += 1
                    self._last_error_time = asyncio.get_event_loop().time()
                    await self._publish_error_event(f"LoopEngine: {str(e)}")

                    # Check if alert is needed
                    if self._error_count >= 5:
                        await self._publish_event(EventTypes.HEALTH_WARNING, {
                            "error": "Multiple errors in loop",
                            "error_count": self._error_count,
                        })

        finally:
            # Publish loop stopped event
            await self._publish_event(EventTypes.LOOP_COMPLETED, {
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
        sense_start = time.time()
        perceptions = await self.agent.perception_module.perceive()

        # Publish perception received event
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

        # Update statistics
        self._phase_stats["sense"]["count"] += 1
        self._phase_stats["sense"]["total_time"] += time.time() - sense_start

        # Publish phase completed event
        await self._publish_phase_event("sense", "completed", {"count": len(perceptions)})

        return perceptions

    async def plan(self, perception) -> Any:
        """
        Plan - Decision planning

        Args:
            perception: Perception input

        Returns:
            Action: Action plan
        """

        # Publish phase started event
        await self._publish_phase_event("plan", "started", {"perception_type": perception.type})

        # Use self-processing module to process perception, generate action
        plan_start = time.time()
        action = await self.agent.processing_module.process(perception)
        plan_time = time.time() - plan_start

        # Publish perception processed event
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

        # Update statistics
        self._phase_stats["act"]["count"] += 1
        self._phase_stats["act"]["total_time"] += act_time

        # Publish phase completed event
        await self._publish_phase_event("act", "completed", {"success": success})

        return result

    async def reflect(self, perception, action, result):
        """
        Reflect - Reflection and learning

        Args:
            perception: Perception
            action: Action
            result: Result
        """

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
        if self.strategy == LoopStrategy.STEP:
            # Wait for user confirmation (for debugging)
            await asyncio.sleep(0)  # In practice should wait for input()
        else:
            # Wait for configured interval
            await asyncio.sleep(self.loop_interval)

    async def _publish_event(self, event_type: str, data: dict):
        """Publish event"""
        event = Event(
            type=event_type,
            data=data,
            source="LoopEngine",
            level=EventLevel.INFO,
        )
        await self.agent.message_bus.publish(event)

    async def _publish_phase_event(self, phase: str, status: str, data: dict = None):
        """Publish phase event"""
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
        """Publish error event"""
        event = Event(
            type=EventTypes.ERROR_OCCURRED,
            data={"error": error_message},
            source="LoopEngine",
            level=EventLevel.ERROR,
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
