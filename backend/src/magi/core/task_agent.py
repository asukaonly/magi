"""
Agent核心 - TaskAgent和WorkerAgent实现
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List
from .agent import Agent, AgentState, AgentConfig
from .task_database import Task, TaskStatus, TaskDatabase
from .timeout_calculator import TimeoutCalculator
from ..events.events import Event, EventTypes, EventLevel
from ..events.backend import MessageBusBackend
from ..llm.base import LLMAdapter
from ..tools.registry import ToolRegistry, ToolExecutionContext


logger = logging.getLogger(__name__)


class Subtask:
    """子任务"""

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
        task_database: TaskDatabase,
        llm_adapter: LLMAdapter,
        tool_registry: ToolRegistry,
    ):
        """
        初始化TaskAgent

        Args:
            agent_id: TaskAgent ID
            config: Agent配置
            message_bus: 消息总线
            task_database: 任务数据库
            llm_adapter: LLM适配器
            tool_registry: 工具注册表
        """
        super().__init__(config)
        self.agent_id = agent_id
        self.message_bus = message_bus
        self.task_database = task_database
        self.llm = llm_adapter
        self.tool_registry = tool_registry
        self._pending_count = 0  # 当前pending任务数
        self._scan_task: Optional[asyncio.Task] = None
        self._running_workers: Dict[str, WorkerAgent] = {}

    async def _on_start(self):
        """启动TaskAgent"""
        self._scan_task = asyncio.create_task(self._scan_tasks())
        logger.info(f"TaskAgent-{self.agent_id} started")

    async def _on_stop(self):
        """停止TaskAgent"""
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        # 等待所有WorkerAgent完成
        if self._running_workers:
            logger.info(f"TaskAgent-{self.agent_id} waiting for workers to finish...")
            for worker in self._running_workers.values():
                await worker.stop()

        logger.info(f"TaskAgent-{self.agent_id} stopped")

    async def _scan_tasks(self):
        """
        扫描任务数据库

        循环扫描分配给自己的待处理任务并执行
        """
        while self.state == AgentState.RUNNING:
            try:
                # 获取分配给此TaskAgent的待处理任务
                pending_tasks = await self.task_database.get_pending_tasks(
                    limit=5,
                    assigned_to=str(self.agent_id),
                )

                for task in pending_tasks:
                    if task.status == TaskStatus.PENDING.value:
                        await self._process_task(task)

                # 等待一段时间
                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TaskAgent-{self.agent_id} scan error: {e}")
                await self._publish_error_event(f"TaskAgent-{self.agent_id}", str(e))

    async def assign_task(self, task: Task):
        """
        分配任务（由MasterAgent调用）

        Args:
            task: 任务对象
        """
        # 任务已经在MasterAgent中更新为PROCESSING状态
        # 这里直接开始处理
        await self._process_task(task)

    async def _process_task(self, task: Task):
        """
        处理任务

        Args:
            task: 任务对象
        """
        try:
            # 增加pending计数
            self._pending_count += 1

            # 发布任务开始事件
            await self._publish_event(
                EventTypes.TASK_STARTED,
                {
                    "task_id": task.task_id,
                    "task_agent_id": self.agent_id,
                }
            )

            # 1. 任务分解
            subtasks = await self._decompose_task(task)

            # 2. 工具匹配
            await self._match_tools(subtasks)

            # 3. 创建WorkerAgent执行
            worker = await self._create_and_run_worker(task, subtasks)

            if worker:
                self._running_workers[task.task_id] = worker

        except Exception as e:
            logger.error(f"TaskAgent-{self.agent_id} process task error: {e}")
            await self._publish_error_event(f"TaskAgent-{self.agent_id}", str(e))

            # 标记任务失败
            await self.task_database.update_task_status(
                task.task_id,
                TaskStatus.FAILED,
                error_message=str(e),
            )

        finally:
            # 减少pending计数
            self._pending_count -= 1

    async def _decompose_task(self, task: Task) -> List[Subtask]:
        """
        分解任务为子任务

        使用LLM分析任务并生成子任务DAG

        Args:
            task: 父任务

        Returns:
            子任务列表
        """
        # 简化版：根据任务类型决定是否需要分解
        if task.type == "query":
            # 查询类任务不需要分解
            return [
                Subtask(
                    subtask_id=f"{task.task_id}_0",
                    parent_task_id=task.task_id,
                    description=task.data.get("message", ""),
                )
            ]

        # 对于复杂任务，使用LLM分解
        if self.llm:
            try:
                subtasks = await self._llm_decompose(task)
                if subtasks:
                    return subtasks
            except Exception as e:
                logger.warning(f"LLM decomposition failed, using fallback: {e}")

        # 默认分解：单个子任务
        return [
            Subtask(
                subtask_id=f"{task.task_id}_0",
                parent_task_id=task.task_id,
                description=task.data.get("message", "Process task"),
            )
        ]

    async def _llm_decompose(self, task: Task) -> List[Subtask]:
        """
        使用LLM分解任务

        Args:
            task: 任务对象

        Returns:
            子任务列表
        """
        prompt = f"""Decompose the following task into subtasks.

Task: {task.data.get("message", "")}

Return a JSON array of subtasks, each with:
- subtask_id: unique ID
- description: what to do
- dependencies: array of subtask_ids this depends on

Format: [{{"subtask_id": "1", "description": "...", "dependencies": []}}]"""

        response = await self.llm.generate(prompt, max_tokens=1000, temperature=0.3)

        # 简化的解析
        import json
        import re

        try:
            # 尝试提取JSON
            json_match = re.search(r'\[.*?\]', response, re.DOTALL)
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
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM decomposition: {e}")

        return None

    async def _match_tools(self, subtasks: List[Subtask]):
        """
        为子任务匹配工具

        Args:
            subtasks: 子任务列表
        """
        for subtask in subtasks:
            if subtask.tool_name:
                continue  # 已指定工具

            # 简化版：根据关键词匹配工具
            description_lower = subtask.description.lower()

            # 获取所有可用工具
            available_tools = self.tool_registry.list_tools()

            for tool_name in available_tools:
                tool_info = self.tool_registry.get_tool_info(tool_name)
                if not tool_info:
                    continue

                # 检查工具关键词
                tool_keywords = tool_info.get("tags", [])
                tool_keywords.append(tool_info.get("name", ""))

                # 简单匹配：如果描述包含工具关键词
                if any(kw in description_lower for kw in tool_keywords if kw):
                    subtask.tool_name = tool_name
                    break

            # 如果没有匹配到工具，使用默认
            if not subtask.tool_name:
                # 对于聊天类任务，不需要工具
                if any(word in description_lower for word in ["你好", "hello", "help", "帮助"]):
                    subtask.tool_name = "chat"
                else:
                    # 尝试使用LLM选择工具
                    if self.llm:
                        subtask.tool_name = await self._llm_select_tool(subtask, available_tools)

    async def _llm_select_tool(self, subtask: Subtask, available_tools: List[str]) -> str:
        """使用LLM选择工具"""
        tools_str = ", ".join(available_tools)

        prompt = f"""Select the best tool for this task.

Task: {subtask.description}

Available tools: {tools_str}

Return only the tool name."""

        response = await self.llm.generate(prompt, max_tokens=50, temperature=0.1)

        # 清理响应
        selected = response.strip().strip('"').strip("'")

        if selected in available_tools:
            return selected

        # 默认返回第一个工具
        return available_tools[0] if available_tools else "chat"

    async def _create_and_run_worker(
        self,
        task: Task,
        subtasks: List[Subtask],
    ) -> Optional['WorkerAgent']:
        """
        创建并运行WorkerAgent

        Args:
            task: 父任务
            subtasks: 子任务列表

        Returns:
            WorkerAgent实例
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

        # 在后台启动worker
        asyncio.create_task(worker.start())

        # 设置完成回调
        asyncio.create_task(self._wait_for_worker_completion(worker))

        return worker

    async def _wait_for_worker_completion(self, worker: 'WorkerAgent'):
        """等待WorkerAgent完成"""
        try:
            await worker.wait_for_completion()
        finally:
            # 清理
            if worker.task_id in self._running_workers:
                del self._running_workers[worker.task_id]

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

    async def _publish_event(self, event_type: str, data: dict):
        """发布事件"""
        event = Event(
            type=event_type,
            data=data,
            source=f"TaskAgent-{self.agent_id}",
            level=EventLevel.INFO,
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
        task: Task,
        subtasks: List[Subtask],
        message_bus: MessageBusBackend,
        llm_adapter: LLMAdapter,
        tool_registry: ToolRegistry,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        """
        初始化WorkerAgent

        Args:
            task_id: 任务ID
            task: 任务对象
            subtasks: 子任务列表
            message_bus: 消息总线
            llm_adapter: LLM适配器
            tool_registry: 工具注册表
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
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
        self._completion_event = asyncio.Event()
        self._final_result = None

    async def _on_start(self):
        """执行任务"""
        try:
            # 使用asyncio.wait_for实现超时
            result = await asyncio.wait_for(
                self._execute_with_retry(),
                timeout=self.timeout
            )

            self._final_result = result

            # 任务完成
            await self.task_database.update_task_status(
                self.task_id,
                TaskStatus.COMPLETED,
                result=result,
            )

            await self._publish_event(
                EventTypes.TASK_COMPLETED,
                {
                    "task_id": self.task_id,
                    "result": result,
                }
            )

            logger.info(f"WorkerAgent-{self.task_id} completed successfully")

        except asyncio.TimeoutError:
            # 任务超时
            await self.task_database.update_task_status(
                self.task_id,
                TaskStatus.TIMEOUT,
                error_message=f"Task timeout after {self.timeout}s",
            )

            await self._publish_error_event(
                f"WorkerAgent-{self.task_id}",
                f"Task timeout after {self.timeout}s"
            )

        except Exception as e:
            # 任务失败
            await self.task_database.update_task_status(
                self.task_id,
                TaskStatus.FAILED,
                error_message=str(e),
            )

            await self._publish_error_event(
                f"WorkerAgent-{self.task_id}",
                str(e)
            )

        finally:
            # 标记完成
            self._completion_event.set()

    async def _execute_with_retry(self) -> Dict[str, Any]:
        """
        执行任务（带重试）

        Returns:
            执行结果

        Raises:
            Exception: 最后一次执行的异常
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"WorkerAgent-{self.task_id} retry {attempt}/{self.max_retries}")

                result = await self._execute_task()

                # 成功，返回结果
                return {
                    "status": "completed",
                    "output": result,
                    "attempts": attempt + 1,
                }

            except Exception as e:
                last_error = e
                logger.warning(f"WorkerAgent-{self.task_id} attempt {attempt + 1} failed: {e}")

                # 增加重试计数
                await self.task_database.increment_retry_count(self.task_id)

                # 如果不是最后一次尝试，等待一段时间
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)  # 指数退避

        # 所有尝试都失败
        raise last_error

    async def _execute_task(self) -> Any:
        """
        执行任务

        Returns:
            任务执行结果
        """
        results = []

        for subtask in self.subtasks:
            # 检查依赖
            if not self._check_dependencies(subtask, results):
                logger.warning(f"Subtask {subtask.subtask_id} dependencies not met")
                continue

            # 执行子任务
            subtask.status = "running"

            if subtask.tool_name and subtask.tool_name != "chat":
                # 使用工具执行
                result = await self._execute_tool(subtask)
            else:
                # 直接使用LLM处理
                result = await self._execute_with_llm(subtask)

            subtask.status = "completed"
            subtask.result = result
            results.append(result)

        return results

    def _check_dependencies(self, subtask: Subtask, results: List) -> bool:
        """检查子任务依赖是否满足"""
        if not subtask.dependencies:
            return True

        # 简化版：假设依赖的子任务已按顺序执行
        return True

    async def _execute_tool(self, subtask: Subtask) -> Any:
        """使用工具执行子任务"""
        from ..tools.schema import ToolExecutionContext

        context = ToolExecutionContext(
            agent_id=f"WorkerAgent-{self.task_id}",
            session_id=self.task_id,
            user_id=self.task.data.get("user_id", "unknown"),
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
        """使用LLM执行子任务"""
        if not self.llm:
            return f"Processed: {subtask.description}"

        prompt = f"""Process the following request:

{subtask.description}

Provide a helpful response."""

        response = await self.llm.generate(prompt, max_tokens=1000)

        return response

    async def wait_for_completion(self):
        """等待任务完成"""
        await self._completion_event.wait()

    async def _publish_event(self, event_type: str, data: dict):
        """发布事件"""
        from ..events.events import Event, EventLevel

        event = Event(
            type=event_type,
            data=data,
            source=f"WorkerAgent-{self.task_id}",
            level=EventLevel.INFO,
        )
        await self.message_bus.publish(event)

    async def _publish_error_event(self, source: str, error_message: str):
        """发布错误事件"""
        from ..events.events import Event, EventLevel

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
