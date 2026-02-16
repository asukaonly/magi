"""
Agent Core - Master Agent Implementation
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
    Master Agent - System Management and Task Dispatch

    Responsibilities:
    - Task recognition and dispatch
    - System health check
    - TaskAgent management
    - Overall coordination
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
        initialize Master Agent

        Args:
            config: Agent configuration
            message_bus: Message bus
            task_agents: List of TaskAgents
            task_database: Task database
            llm_adapter: LLM adapter (for task recognition)
        """
        super().__init__(config)
        self.message_bus = message_bus
        self.task_agents = task_agents
        self.task_database = task_database
        self.llm = llm_adapter
        self._main_loop_task: Optional[asyncio.Task] = None
        self._event_subscription_id: Optional[str] = None
        self._system_degraded = False  # Whether system is in degraded state

    async def _on_start(self):
        """Start Master Agent"""
        # Start message bus
        await self.message_bus.start()

        # initialize task database
        await self.task_database._init_db()

        # Start all TaskAgents
        for task_agent in self.task_agents:
            await task_agent.start()

        # Subscribe to user_MESSAGE events for task recognition
        self._event_subscription_id = await self.message_bus.subscribe(
            EventTypes.USER_MESSAGE,
            self._on_user_message,
            propagation_mode="broadcast",
        )

        # Start main loop
        self._main_loop_task = asyncio.create_task(self._main_loop())

        # Publish startup event
        await self._publish_event(
            EventTypes.AGENT_STARTED,
            {"agent_type": "master", "name": self.config.name}
        )

        logger.info("MasterAgent started")

    async def _on_stop(self):
        """Stop Master Agent"""
        # Stop main loop
        if self._main_loop_task:
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                pass

        # Cancel event subscription
        if self._event_subscription_id:
            await self.message_bus.unsubscribe(self._event_subscription_id)

        # Stop all TaskAgents (in reverse order)
        for task_agent in reversed(self.task_agents):
            await task_agent.stop()

        # Stop message bus
        await self.message_bus.stop()

        # Publish stop event
        await self._publish_event(
            EventTypes.AGENT_STOPPED,
            {"agent_type": "master", "name": self.config.name}
        )

        logger.info("MasterAgent stopped")

    async def _main_loop(self):
        """
        Main loop

        Steps:
        1. Get perception
        2. Recognize tasks
        3. Dispatch tasks
        4. Health check
        """
        while self.state == AgentState.runNING:
            try:
                # 1. Health check (including resource alert handling)
                await self._check_system_health()

                # 2. Scan pending tasks and dispatch
                if not self._system_degraded:
                    await self._scan_and_dispatch_tasks()

                # 3. Publish heartbeat event
                await self._publish_heartbeat_event()

                # 4. Wait for a while
                await asyncio.sleep(self.config.loop_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MasterAgent main loop error: {e}")
                await self._publish_error_event("MasterAgent", str(e))

    async def _on_user_message(self, Event: Event):
        """
        Handle user message event, recognize and create task

        Args:
            event: user_MESSAGE event
        """
        if self._system_degraded:
            # Do not process new tasks when system is degraded
            return

        try:
            message_data = event.data
            user_message = message_data.get("message", "")
            user_id = message_data.get("user_id", "unknown")

            if not user_message:
                return

            # Recognize task
            task = await self._identify_task_from_message(user_message, user_id)

            if task:
                logger.info(f"Task identified: {task.task_id} from user {user_id}")

                # Publish task created event
                await self._publish_event(
                    EventTypes.TASK_CREATED,
                    {
                        "task_id": task.task_id,
                        "task_type": task.type,
                        "user_id": user_id,
                    }
                )

        except Exception as e:
            logger.error(f"error processing user message: {e}")
            await self._publish_error_event("TaskRecognition", str(e))

    async def _identify_task_from_message(
        self,
        message: str,
        user_id: str,
    ) -> Optional[Any]:
        """
        Recognize task from user message

        Args:
            message: User message
            user_id: User id

        Returns:
            Recognized task or None
        """
        # Simplified task recognition: based on keywords
        message_lower = message.lower()

        # Determine task type
        task_type = TaskType.QUERY
        priority = TaskPriority.NORMAL
        interaction_level = "notttne"  # notttne, low, medium, high

        # Detect keywords
        if any(word in message_lower for word in ["calculate", "statistics", "analysis", "compute", "calculate"]):
            task_type = TaskType.COMPUTATION
        elif any(word in message_lower for word in ["帮我", "请", "能不能", "can you", "help"]):
            task_type = TaskType.INTERACTIVE
            interaction_level = "medium"

        # Detect priority
        if any(word in message_lower for word in ["紧急", "urgent", "asap", "马上"]):
            priority = TaskPriority.URGENT
        elif any(word in message_lower for word in ["重要", "important", "priority"]):
            priority = TaskPriority.HIGH

        # Calculate timeout
        timeout = TimeoutCalculator.calculate(
            task_type=task_type,
            priority=priority,
        )

        # Create task
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
        """Scan pending tasks and dispatch"""
        # Get pending tasks
        pending_tasks = await self.task_database.get_pending_tasks(limit=10)

        for task in pending_tasks:
            # Check if already assigned
            if task.assigned_to:
                continue

            # Dispatch task
            await self.dispatch_task(task)

    async def dispatch_task(self, task) -> bool:
        """
        Dispatch task to TaskAgent (load balancing)

        Args:
            task: Task object

        Returns:
            Whether dispatch was successful
        """
        # Select TaskAgent with lowest load
        task_agent = self._select_task_agent_by_load()

        if task_agent is None:
            # No available TaskAgent
            await self._publish_error_event(
                "TaskDispatch",
                f"No available TaskAgent for task {task.task_id}"
            )
            return False

        try:
            # Update task status to processing
            await self.task_database.update_task_status(
                task.task_id,
                TaskStatus.processING,
                assigned_to=str(task_agent.agent_id),
            )

            # Increment TaskAgent's pending count
            task_agent._pending_count += 1

            # Publish task assigned event
            await self._publish_event(
                EventTypes.task_assignED,
                {
                    "task_id": task.task_id,
                    "task_agent_id": task_agent.agent_id,
                    "task_type": task.type,
                }
            )

            # Notify TaskAgent to process task
            await task_agent.assign_task(task)

            logger.info(
                f"Task {task.task_id} dispatched to TaskAgent-{task_agent.agent_id}"
            )

            return True

        except Exception as e:
            # error occurred, restore state
            await self.task_database.update_task_status(
                task.task_id,
                TaskStatus.pending,
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
        System health check

        Checks:
        - CPU usage
        - Memory usage
        - TaskAgent status

        May trigger degradation based on check results
        """
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # Check for alerts
        cpu_alert = cpu_percent > 90
        memory_alert = memory_percent > 90

        if cpu_alert or memory_alert:
            # Trigger degradation
            if not self._system_degraded:
                self._system_degraded = True
                await self._publish_event(
                    EventTypes.HEALTH_warnING,
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

        # Recover from degradation when resources return to notttrmal
        if self._system_degraded and cpu_percent < 80 and memory_percent < 80:
            self._system_degraded = False
            await self._publish_event(
                EventTypes.HEALTH_warnING,
                {"reason": "System recovered", "cpu_percent": cpu_percent}
            )
            logger.info("System recovered from degraded state")

    async def _publish_heartbeat_event(self):
        """Publish heartbeat event"""
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
        Select TaskAgent based on load (load balancing)

        Selects TaskAgent with the fewest pending tasks

        Returns:
            Selected TaskAgent or None
        """
        if not self.task_agents:
            return None

        # Filter running TaskAgents
        running_agents = [
            agent for agent in self.task_agents
            if agent.state == AgentState.runNING
        ]

        if not running_agents:
            return None

        # Select TaskAgent with fewest pending tasks
        selected = min(
            running_agents,
            key=lambda agent: agent.get_pending_count()
        )

        return selected

    def get_task_agents_load(self) -> dict:
        """
        Get load status of all TaskAgents

        Returns:
            Load info dict {agent_id: pending_count}
        """
        return {
            agent.agent_id: agent.get_pending_count()
            for agent in self.task_agents
            if agent.state == AgentState.runNING
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Get MasterAgent statistics"""
        task_stats = await self.task_database.get_stats()

        return {
            "state": self.state.value,
            "degraded": self._system_degraded,
            "task_agents_load": self.get_task_agents_load(),
            "task_stats": task_stats,
        }

    async def _publish_event(self, event_type: str, data: dict):
        """Publish event"""
        event = Event(
            type=event_type,
            data=data,
            source="MasterAgent",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

    async def _publish_error_event(self, source: str, error_message: str):
        """Publish error event"""
        event = Event(
            type=EventTypes.ERROR_OCCURRED,
            data={
                "source": source,
                "error": error_message,
            },
            source="MasterAgent",
            level=EventLevel.error,
        )
        await self.message_bus.publish(event)
