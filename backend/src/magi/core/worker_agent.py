"""
WorkerAgent - 轻量级任务执行Agent

职责：
- 执行具体任务
- 超时控制
- 重试机制
- 执行完成后自动销毁
"""
import asyncio
import time
from typing import Dict, Any, Optional, Callable
from .agent import Agent, AgentConfig, AgentState
from .task_database import Task, TaskStatus
from .timeout import TimeoutCalculator, TaskType, TaskPriority
from .monitoring import AgentMetrics


class WorkerAgentConfig(AgentConfig):
    """WorkerAgent配置"""

    def __init__(
        self,
        name: str,
        llm_config: Dict[str, Any],
        task: Task,
        tool_registry=None,
        max_retries: int = 3,
        timeout: Optional[float] = None,
        on_complete: Optional[Callable] = None,
        on_failure: Optional[Callable] = None,
    ):
        """
        初始化WorkerAgent配置

        Args:
            name: Agent名称
            llm_config: LLM配置
            task: 要执行的任务
            tool_registry: 工具注册表
            max_retries: 最大重试次数
            timeout: 超时时间（秒），None表示自动计算
            on_complete: 完成回调
            on_failure: 失败回调
        """
        super().__init__(name=name, llm_config=llm_config)
        self.task = task
        self.tool_registry = tool_registry
        self.max_retries = max_retries
        self.timeout = timeout
        self.on_complete = on_complete
        self.on_failure = on_failure


class WorkerAgent(Agent):
    """
    WorkerAgent - 轻量级任务执行Agent

    特点：
    - 轻量级，用完即销毁
    - 超时控制
    - 自动重试
    - 执行完成后调用回调
    """

    def __init__(self, config: WorkerAgentConfig):
        """
        初始化WorkerAgent

        Args:
            config: WorkerAgent配置
        """
        super().__init__(config)

        # 任务相关
        self.task = config.task
        self.tool_registry = config.tool_registry
        self.max_retries = config.max_retries
        self.timeout = config.timeout
        self.on_complete = config.on_complete
        self.on_failure = config.on_failure

        # 超时计算器
        self.timeout_calculator = TimeoutCalculator()

        # 指标收集
        self.metrics = AgentMetrics(agent_id=config.name)

        # 执行结果
        self._result: Any = None
        self._error: Optional[Exception] = None

        # 任务完成标志
        self._task_completed = False

    async def start(self):
        """
        启动WorkerAgent

        WorkerAgent的特殊启动逻辑：
        1. 启动后立即执行任务
        2. 任务完成后自动停止
        """
        if self.state == AgentState.RUNNING:
            raise RuntimeError(f"Agent {self.config.name} is already running")

        self.state = AgentState.STARTING
        self._start_time = asyncio.get_event_loop().time()
        self.metrics.start()

        try:
            # 执行任务（带重试）
            await self._execute_with_retry()

            # 任务完成后，根据结果设置状态
            if self._error is None:
                self.state = AgentState.STOPPED
            else:
                self.state = AgentState.ERROR

            self._stop_time = asyncio.get_event_loop().time()

        except Exception as e:
            self.state = AgentState.ERROR
            self._error = e
            raise

    async def stop(self):
        """
        停止WorkerAgent

        WorkerAgent在任务完成后会自动停止，不需要手动调用
        """
        # WorkerAgent通常在任务完成后自动停止
        # 如果需要手动停止，直接清理资源
        await self._cleanup()
        self.state = AgentState.STOPPED
        self._stop_time = asyncio.get_event_loop().time()

    async def _execute_with_retry(self):
        """
        带重试的任务执行

        执行流程：
        1. 计算超时时间
        2. 尝试执行任务
        3. 如果失败且未达到最大重试次数，重试
        4. 调用相应的回调
        """
        retry_count = 0

        while retry_count <= self.max_retries:
            try:
                # 计算超时时间
                timeout = self._calculate_timeout(retry_count)

                # 记录开始时间
                loop_start = time.time()

                # 执行任务
                self._result = await asyncio.wait_for(
                    self._execute_task(),
                    timeout=timeout
                )

                # 记录成功
                loop_duration = time.time() - loop_start
                self.metrics.record_loop(loop_duration)
                self.metrics.record_success()
                self.metrics.record_task_completed()

                # 标记任务为完成
                self.task.status = TaskStatus.COMPLETED
                self.task.completed_at = time.time()
                self._task_completed = True

                # 调用完成回调
                if self.on_complete:
                    await self.on_complete(self.task, self._result)

                break  # 成功，退出重试循环

            except asyncio.TimeoutError:
                # 超时
                self._error = Exception(f"Task timeout after {timeout}s")
                retry_count += 1

                if retry_count > self.max_retries:
                    # 达到最大重试次数
                    await self._handle_failure()
                    break
                else:
                    # 继续重试
                    self.task.retry_count = retry_count
                    await asyncio.sleep(0.1)  # 短暂等待后重试

            except Exception as e:
                # 其他错误
                self._error = e
                retry_count += 1

                if retry_count > self.max_retries:
                    # 达到最大重试次数
                    await self._handle_failure()
                    break
                else:
                    # 继续重试
                    self.task.retry_count = retry_count
                    await asyncio.sleep(0.1)  # 短暂等待后重试

    async def _execute_task(self) -> Any:
        """
        执行任务的具体逻辑

        Returns:
            执行结果

        Raises:
            Exception: 执行失败
        """
        # 标记任务为运行中
        self.task.status = TaskStatus.RUNNING
        self.task.started_at = time.time()

        # 根据任务类型执行
        task_type = self.task.type
        task_data = self.task.data

        if task_type == "tool_execution":
            # 工具执行
            return await self._execute_tool(task_data)

        elif task_type == "llm_generation":
            # LLM生成
            return await self._execute_llm(task_data)

        elif task_type == "custom":
            # 自定义任务
            return await self._execute_custom(task_data)

        else:
            # 默认处理
            return await self._execute_default(task_data)

    async def _execute_tool(self, task_data: Dict) -> Any:
        """
        执行工具任务

        Args:
            task_data: 任务数据，包含tool_name和parameters

        Returns:
            工具执行结果
        """
        if not self.tool_registry:
            raise RuntimeError("Tool registry not configured")

        tool_name = task_data.get("tool_name")
        parameters = task_data.get("parameters", {})

        if not tool_name:
            raise ValueError("tool_name is required for tool_execution task")

        # 执行工具
        result = await self.tool_registry.execute(tool_name, parameters)

        if not result.success:
            raise RuntimeError(f"Tool execution failed: {result.error}")

        return result.data

    async def _execute_llm(self, task_data: Dict) -> Any:
        """
        执行LLM生成任务

        Args:
            task_data: 任务数据，包含prompt等

        Returns:
            LLM生成结果
        """
        # 简化实现：返回模拟结果
        # 实际实现需要调用LLM adapter
        prompt = task_data.get("prompt", "")
        return {"response": f"Generated response for: {prompt}"}

    async def _execute_custom(self, task_data: Dict) -> Any:
        """
        执行自定义任务

        Args:
            task_data: 任务数据

        Returns:
            执行结果
        """
        # 简化实现：返回任务数据
        return task_data

    async def _execute_default(self, task_data: Dict) -> Any:
        """
        默认任务执行

        Args:
            task_data: 任务数据

        Returns:
            执行结果
        """
        # 默认实现：返回任务数据作为结果
        return {"result": task_data}

    def _calculate_timeout(self, retry_count: int) -> float:
        """
        计算超时时间

        Args:
            retry_count: 当前重试次数

        Returns:
            超时时间（秒）
        """
        # 如果配置了固定超时，直接使用
        if self.timeout:
            return self.timeout_calculator.calculate_retry_timeout(
                base_timeout=self.timeout,
                retry_count=retry_count,
                max_retries=self.max_retries,
            )

        # 否则根据任务类型自动计算
        task_type_map = {
            "tool_execution": TaskType.IO,
            "llm_generation": TaskType.NETWORK,
            "custom": TaskType.COMPUTATION,
        }

        task_type = task_type_map.get(
            self.task.type,
            TaskType.SIMPLE
        )

        priority_map = {
            0: TaskPriority.LOW,
            1: TaskPriority.NORMAL,
            2: TaskPriority.HIGH,
            3: TaskPriority.URGENT,
        }

        priority = priority_map.get(
            self.task.priority.value,
            TaskPriority.NORMAL
        )

        # 计算基础超时
        base_timeout = self.timeout_calculator.calculate_timeout(
            task_type=task_type,
            priority=priority,
        )

        # 应用重试退避
        return self.timeout_calculator.calculate_retry_timeout(
            base_timeout=base_timeout,
            retry_count=retry_count,
            max_retries=self.max_retries,
        )

    async def _handle_failure(self):
        """处理任务失败"""
        self.metrics.record_error()
        self.metrics.record_task_failed()

        # 标记任务为失败
        self.task.status = TaskStatus.FAILED
        self.task.error = str(self._error) if self._error else "Unknown error"

        # 调用失败回调
        if self.on_failure:
            await self.on_failure(self.task, self._error)

    async def _cleanup(self):
        """清理资源"""
        # 清理资源
        await asyncio.sleep(0)

    def get_result(self) -> Any:
        """
        获取执行结果

        Returns:
            执行结果或None
        """
        return self._result

    def get_error(self) -> Optional[Exception]:
        """
        获取错误信息

        Returns:
            错误或None
        """
        return self._error

    def get_metrics(self) -> Dict[str, Any]:
        """
        获取指标

        Returns:
            指标字典
        """
        return self.metrics.get_metrics()

    async def wait_for_completion(self, timeout: float = None) -> bool:
        """
        等待任务完成

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否成功完成
        """
        start_time = time.time()

        # 等待任务完成（状态变为STOPPED或ERROR）
        while self.state == AgentState.STARTING:
            if timeout and (time.time() - start_time) > timeout:
                return False

            await asyncio.sleep(0.1)

        return self._task_completed and self.task.status == TaskStatus.COMPLETED
