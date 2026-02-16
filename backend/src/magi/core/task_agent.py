"""
Agent Core - TaskAgent and WorkerAgent Implementation
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List
from .agent import Agent, AgentState, AgentConfig
from .task_database import Task, TaskStatus, Taskdatabase
from .timeout_calculator import TimeoutCalculator
from ..events.events import event, eventtypes, eventlevel
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter
from ..tools.registry import ToolRegistry, ToolExecutionContext

logger = logging.getLogger(__name__)


class Subtask:
    """Subtask"""

    def __init__(
        self,
        subtask_id: str,
        parent_task_id: str,
        description: str,
        tool_name: str = None,
        parameters: Dict[str, Any] = None,
        dependencies: List[str] = None,
    ):
        self.subtask_id = subtask_id
        self.parent_task_id = parent_task_id
        self.description = description
        self.tool_name = tool_name
        self.parameters = parameters or {}
        self.dependencies = dependencies or []
        self.status = "pending"
        self.result = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "parent_task_id": self.parent_task_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "status": self.status,
        }


class TaskAgent(Agent):
    """
    TaskAgent - Task Orchestration and Execution

    Responsibilities:
    - Scan task database
    - Task decomposition
    - Tool matching
    - Create WorkerAgent to execute tasks
    """

    def __init__(
        self,
        agent_id: int,
        config: AgentConfig,
        message_bus: MessageBusBackend,
        task_database: Taskdatabase,
        llm_adapter: LLMAdapter,
        tool_registry: ToolRegistry,
    ):
        """
        initialize TaskAgent

        Args:
            agent_id: TaskAgent id
            config: Agent configuration
            message_bus: Message bus
            task_database: Task database
            llm_adapter: LLM adapter
            tool_registry: Tool registry
        """
        super().__init__(config)
        self.agent_id = agent_id
        self.message_bus = message_bus
        self.task_database = task_database
        self.llm = llm_adapter
        self.tool_registry = tool_registry
        self._pending_count = 0  # Current pending task count
        self._scan_task: Optional[asyncio.Task] = None
        self._running_workers: Dict[str, WorkerAgent] = {}

    async def _on_start(self):
        """Start TaskAgent"""
        self._scan_task = asyncio.create_task(self._scan_tasks())
        logger.info(f"TaskAgent-{self.agent_id} started")

    async def _on_stop(self):
        """Stop TaskAgent"""
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.Cancellederror:
                pass

        # Wait for all WorkerAgents to finish
        if self._running_workers:
            logger.info(f"TaskAgent-{self.agent_id} waiting for workers to finish...")
            for worker in self._running_workers.values():
                await worker.stop()

        logger.info(f"TaskAgent-{self.agent_id} stopped")

    async def _scan_tasks(self):
        """
        Scan task database

        Continuously scan for pending tasks assigned to self and execute them
        """
        while self.state == AgentState.runNING:
            try:
                # Get pending tasks assigned to this TaskAgent
                pending_tasks = await self.task_database.get_pending_tasks(
                    limit=5,
                    assigned_to=str(self.agent_id),
                )

                for task in pending_tasks:
                    if task.status == TaskStatus.pending.value:
                        await self._process_task(task)

                # Wait for a while
                await asyncio.sleep(1.0)

            except asyncio.Cancellederror:
                break
            except Exception as e:
                logger.error(f"TaskAgent-{self.agent_id} scan error: {e}")
                await self._publish_error_event(f"TaskAgent-{self.agent_id}", str(e))

    async def assign_task(self, task: Task):
        """
        Assign task (called by MasterAgent)

        Args:
            task: Task object
        """
        # Task has already been updated to processING status in MasterAgent
        # Start processing directly here
        await self._process_task(task)

    async def _process_task(self, task: Task):
        """
        process task

        Args:
            task: Task object
        """
        try:
            # Increment pending count
            self._pending_count += 1

            # Publish task started event
            await self._publish_event(
                eventtypes.task_startED,
                {
                    "task_id": task.task_id,
                    "task_agent_id": self.agent_id,
                }
            )

            # 1. Task decomposition
            subtasks = await self._decompose_task(task)

            # 2. Tool matching
            await self._match_tools(subtasks)

            # 3. Create WorkerAgent to execute
            worker = await self._create_and_run_worker(task, subtasks)

            if worker:
                self._running_workers[task.task_id] = worker

        except Exception as e:
            logger.error(f"TaskAgent-{self.agent_id} process task error: {e}")
            await self._publish_error_event(f"TaskAgent-{self.agent_id}", str(e))

            # Mark task as failed
            await self.task_database.update_task_status(
                task.task_id,
                TaskStatus.failED,
                error_message=str(e),
            )

        finally:
            # Decrement pending count
            self._pending_count -= 1

    async def _decompose_task(self, task: Task) -> List[Subtask]:
        """
        Decompose task into subtasks

        Use LLM to analyze task and generate subtask DAG

        Args:
            task: Parent task

        Returns:
            List of subtasks
        """
        # Simplified version: decide whether decomposition is needed based on task type
        if task.type == "query":
            # query tasks don't need decomposition
            return [
                Subtask(
                    subtask_id=f"{task.task_id}_0",
                    parent_task_id=task.task_id,
                    description=task.data.get("message", ""),
                )
            ]

        # For complex tasks, use LLM for decomposition
        if self.llm:
            try:
                subtasks = await self._llm_decompose(task)
                if subtasks:
                    return subtasks
            except Exception as e:
                logger.warning(f"LLM decomposition failed, using fallback: {e}")

        # Default decomposition: single subtask
        return [
            Subtask(
                subtask_id=f"{task.task_id}_0",
                parent_task_id=task.task_id,
                description=task.data.get("message", "process task"),
            )
        ]

    async def _llm_decompose(self, task: Task) -> List[Subtask]:
        """
        Use LLM to decompose task

        Args:
            task: Task object

        Returns:
            List of subtasks
        """
        prompt = f"""Decompose the following task into subtasks.

Task: {task.data.get("message", "")}

Return a JSON array of subtasks, each with:
- subtask_id: unique id
- description: what to do
- dependencies: array of subtask_ids this depends on

Format: [{{"subtask_id": "1", "description": "...", "dependencies": []}}]"""

        response = await self.llm.generate(prompt, max_tokens=1000, temperature=0.3)

        # Simplified parsing
        import json
        import re

        try:
            # Try to extract JSON
            json_match = re.search(r'\[.*?\]', response, re.DOTall)
            if json_match:
                subtasks_data = json.loads(json_match.group())
                return [
                    Subtask(
                        subtask_id=s["subtask_id"],
                        parent_task_id=task.task_id,
                        description=s["description"],
                        dependencies=s.get("dependencies", []),
                    )
                    for s in subtasks_data
                ]
        except (json.JSONDecodeerror, Keyerror) as e:
            logger.warning(f"Failed to parse LLM decomposition: {e}")

        return None

    async def _match_tools(self, subtasks: List[Subtask]):
        """
        Match tools for subtasks

        Args:
            subtasks: List of subtasks
        """
        for subtask in subtasks:
            if subtask.tool_name:
                continue  # Tool already specified

            # Simplified version: match tools by keywords
            description_lower = subtask.description.lower()

            # Get all available tools
            available_tools = self.tool_registry.list_tools()

            for tool_name in available_tools:
                tool_info = self.tool_registry.get_tool_info(tool_name)
                if not tool_info:
                    continue

                # Check tool keywords
                tool_keywords = tool_info.get("tags", [])
                tool_keywords.append(tool_info.get("name", ""))

                # Simple matching: if description contains tool keywords
                if any(kw in description_lower for kw in tool_keywords if kw):
                    subtask.tool_name = tool_name
                    break

            # If nottt tool matched, use default
            if not subtask.tool_name:
                # For chat tasks, nottt tool needed
                if any(word in description_lower for word in ["你好", "hello", "help", "帮助"]):
                    subtask.tool_name = "chat"
                else:
                    # Try to use LLM to select tool
                    if self.llm:
                        subtask.tool_name = await self._llm_select_tool(subtask, available_tools)

    async def _llm_select_tool(self, subtask: Subtask, available_tools: List[str]) -> str:
        """Use LLM to select tool"""
        tools_str = ", ".join(available_tools)

        prompt = f"""Select the best tool for this task.

Task: {subtask.description}

Available tools: {tools_str}

Return only the tool name."""

        response = await self.llm.generate(prompt, max_tokens=50, temperature=0.1)

        # Clean up response
        selected = response.strip().strip('"').strip("'")

        if selected in available_tools:
            return selected

        # Default return first tool
        return available_tools[0] if available_tools else "chat"

    async def _create_and_run_worker(
        self,
        task: Task,
        subtasks: List[Subtask],
    ) -> Optional['WorkerAgent']:
        """
        Create and run WorkerAgent

        Args:
            task: Parent task
            subtasks: List of subtasks

        Returns:
            WorkerAgent instance
        """
        worker = WorkerAgent(
            task_id=task.task_id,
            task=task,
            subtasks=subtasks,
            message_bus=self.message_bus,
            llm_adapter=self.llm,
            tool_registry=self.tool_registry,
            timeout=task.timeout,
            max_retries=task.max_retries,
        )

        # Start worker in background
        asyncio.create_task(worker.start())

        # Set completion callback
        asyncio.create_task(self._wait_for_worker_completion(worker))

        return worker

    async def _wait_for_worker_completion(self, worker: 'WorkerAgent'):
        """Wait for WorkerAgent to complete"""
        try:
            await worker.wait_for_completion()
        finally:
            # Cleanup
            if worker.task_id in self._running_workers:
                del self._running_workers[worker.task_id]

    def get_pending_count(self) -> int:
        """Get current pending task count"""
        return self._pending_count

    async def _publish_error_event(self, source: str, error_message: str):
        """Publish error event"""
        event = event(
            type=eventtypes.error_OCCURRED,
            data={
                "source": source,
                "error": error_message,
            },
            source=f"TaskAgent-{self.agent_id}",
            level=eventlevel.error,
        )
        await self.message_bus.publish(event)

    async def _publish_event(self, event_type: str, data: dict):
        """Publish event"""
        event = event(
            type=event_type,
            data=data,
            source=f"TaskAgent-{self.agent_id}",
            level=eventlevel.INFO,
        )
        await self.message_bus.publish(event)


class WorkerAgent(Agent):
    """
    WorkerAgent - Task Execution

    Features:
    - Lightweight, stateless
    - Destroyed after task completion
    - Supports timeout and retry
    """

    def __init__(
        self,
        task_id: str,
        task: Task,
        subtasks: List[Subtask],
        message_bus: MessageBusBackend,
        llm_adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        """
        initialize WorkerAgent

        Args:
            task_id: Task id
            task: Task object
            subtasks: List of subtasks
            message_bus: Message bus
            llm_adapter: LLM adapter
            tool_registry: Tool registry
            timeout: Timeout in seconds
            max_retries: Maximum retry count
        """
        config = AgentConfig(name=f"Worker-{task_id}", llm_config={})
        super().__init__(config)
        self.task_id = task_id
        self.task = task
        self.subtasks = subtasks
        self.message_bus = message_bus
        self.llm = llm_adapter
        self.tool_registry = tool_registry
        self.timeout = timeout
        self.max_retries = max_retries
        self._completion_event = asyncio.event()
        self._final_result = None

    async def _on_start(self):
        """Execute task"""
        try:
            # Use asyncio.wait_for for timeout
            result = await asyncio.wait_for(
                self._execute_with_retry(),
                timeout=self.timeout
            )

            self._final_result = result

            # Task completed
            await self.task_database.update_task_status(
                self.task_id,
                TaskStatus.COMPLETED,
                result=result,
            )

            await self._publish_event(
                eventtypes.task_COMPLETED,
                {
                    "task_id": self.task_id,
                    "result": result,
                }
            )

            logger.info(f"WorkerAgent-{self.task_id} completed successfully")

        except asyncio.Timeouterror:
            # Task timeout
            await self.task_database.update_task_status(
                self.task_id,
                TaskStatus.timeout,
                error_message=f"Task timeout after {self.timeout}s",
            )

            await self._publish_error_event(
                f"WorkerAgent-{self.task_id}",
                f"Task timeout after {self.timeout}s"
            )

        except Exception as e:
            # Task failed
            await self.task_database.update_task_status(
                self.task_id,
                TaskStatus.failED,
                error_message=str(e),
            )

            await self._publish_error_event(
                f"WorkerAgent-{self.task_id}",
                str(e)
            )

        finally:
            # Mark as completed
            self._completion_event.set()

    async def _execute_with_retry(self) -> Dict[str, Any]:
        """
        Execute task (with retry)

        Returns:
            Execution result

        Raises:
            Exception: Exception from the last execution
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"WorkerAgent-{self.task_id} retry {attempt}/{self.max_retries}")

                result = await self._execute_task()

                # Success, return result
                return {
                    "status": "completed",
                    "output": result,
                    "attempts": attempt + 1,
                }

            except Exception as e:
                last_error = e
                logger.warning(f"WorkerAgent-{self.task_id} attempt {attempt + 1} failed: {e}")

                # Increment retry count
                await self.task_database.increment_retry_count(self.task_id)

                # If not the last attempt, wait for a while
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

        # All attempts failed
        raise last_error

    async def _execute_task(self) -> Any:
        """
        Execute task

        Returns:
            Task execution result
        """
        results = []

        for subtask in self.subtasks:
            # Check dependencies
            if not self._check_dependencies(subtask, results):
                logger.warning(f"Subtask {subtask.subtask_id} dependencies not met")
                continue

            # Execute subtask
            subtask.status = "running"

            if subtask.tool_name and subtask.tool_name != "chat":
                # Execute with tool
                result = await self._execute_tool(subtask)
            else:
                # process directly with LLM
                result = await self._execute_with_llm(subtask)

            subtask.status = "completed"
            subtask.result = result
            results.append(result)

        return results

    def _check_dependencies(self, subtask: Subtask, results: List) -> bool:
        """Check if subtask dependencies are satisfied"""
        if not subtask.dependencies:
            return True

        # Simplified version: assume dependent subtasks are executed in order
        return True

    async def _execute_tool(self, subtask: Subtask) -> Any:
        """Execute subtask using tool"""
        from ..tools.schema import ToolExecutionContext

        context = ToolExecutionContext(
            agent_id=f"WorkerAgent-{self.task_id}",
            session_id=self.task_id,
            user_id=self.task.data.get("user_id", "unknotttwn"),
            permissions=["authenticated"],
            env_vars={
                "task_id": self.task_id,
                "subtask_id": subtask.subtask_id,
            },
        )

        result = await self.tool_registry.execute(
            subtask.tool_name,
            subtask.parameters,
            context,
        )

        if not result.success:
            raise Exception(f"Tool execution failed: {result.error}")

        return result.data

    async def _execute_with_llm(self, subtask: Subtask) -> str:
        """Execute subtask using LLM"""
        if not self.llm:
            return f"processed: {subtask.description}"

        prompt = f"""process the following request:

{subtask.description}

Provide a helpful response."""

        response = await self.llm.generate(prompt, max_tokens=1000)

        return response

    async def wait_for_completion(self):
        """Wait for task to complete"""
        await self._completion_event.wait()

    async def _publish_event(self, event_type: str, data: dict):
        """Publish event"""
        from ..events.events import event, eventlevel

        event = event(
            type=event_type,
            data=data,
            source=f"WorkerAgent-{self.task_id}",
            level=eventlevel.INFO,
        )
        await self.message_bus.publish(event)

    async def _publish_error_event(self, source: str, error_message: str):
        """Publish error event"""
        from ..events.events import event, eventlevel

        event = event(
            type=eventtypes.task_failED,
            data={
                "source": source,
                "error": error_message,
            },
            source=source,
            level=eventlevel.error,
        )
        await self.message_bus.publish(event)
