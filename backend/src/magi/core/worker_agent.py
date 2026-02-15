"""
WorkerAgent - 轻量级任务ExecuteAgent

职责：
- Execute具体任务
- timeout控制
- 重试机制
- Executecomplete后自动destroy
"""
import asyncio
import time
from typing import Dict, Any, Optional, Callable
from .agent import Agent, AgentConfig, AgentState
from .task_database import Task, TaskStatus
from .timeout import TimeoutCalculator, Tasktype, Taskpriority
from .monitoring import AgentMetrics


class WorkerAgentConfig(AgentConfig):
    """WorkerAgentConfiguration"""

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
        initializeWorkerAgentConfiguration

        Args:
            name: AgentName
            llm_config: LLMConfiguration
            task: 要Execute的任务
            tool_registry: toolRegistry
            max_retries: maximum重试count
            timeout: timeout时间（seconds），Nonetable示自动calculate
            on_complete: completecallback
            on_failure: failurecallback
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
    WorkerAgent - 轻量级任务ExecuteAgent

    特点：
    - 轻量级，用完即destroy
    - timeout控制
    - 自动重试
    - Executecomplete后调用callback
    """

    def __init__(self, config: WorkerAgentConfig):
        """
        initializeWorkerAgent

        Args:
            config: WorkerAgentConfiguration
        """
        super().__init__(config)

        # 任务related
        self.task = config.task
        self.tool_registry = config.tool_registry
        self.max_retries = config.max_retries
        self.timeout = config.timeout
        self.on_complete = config.on_complete
        self.on_failure = config.on_failure

        # timeoutcalculate器
        self.timeout_calculator = TimeoutCalculator()

        # metric收集
        self.metrics = AgentMetrics(agent_id=config.name)

        # Execution result
        self._result: Any = None
        self._error: Optional[Exception] = None

        # 任务completeflag
        self._task_completed = False

    async def start(self):
        """
        启动WorkerAgent

        WorkerAgent的特殊启动逻辑：
        1. 启动后立即Execute任务
        2. 任务complete后自动stop
        """
        if self.state == AgentState.runNING:
            raise Runtimeerror(f"Agent {self.config.name} is already running")

        self.state = AgentState.startING
        self._start_time = asyncio.get_event_loop().time()
        self.metrics.start()

        try:
            # Execute任务（带重试）
            await self._execute_with_retry()

            # 任务complete后，根据ResultSettingState
            if self._error is None:
                self.state = AgentState.stopPED
            else:
                self.state = AgentState.error

            self._stop_time = asyncio.get_event_loop().time()

        except Exception as e:
            self.state = AgentState.error
            self._error = e
            raise

    async def stop(self):
        """
        stopWorkerAgent

        WorkerAgent在任务complete后会自动stop，不需要手动调用
        """
        # WorkerAgent通常在任务complete后自动stop
        # 如果需要手动stop，直接清理资源
        await self._cleanup()
        self.state = AgentState.stopPED
        self._stop_time = asyncio.get_event_loop().time()

    async def _execute_with_retry(self):
        """
        带重试的任务Execute

        Executeprocess：
        1. calculatetimeout时间
        2. 尝试Execute任务
        3. 如果failure且未达到maximum重试count，重试
        4. 调用相应的callback
        """
        retry_count = 0

        while retry_count <= self.max_retries:
            try:
                # calculatetimeout时间
                timeout = self._calculate_timeout(retry_count)

                # recordStart时间
                loop_start = time.time()

                # Execute任务
                self._result = await asyncio.wait_for(
                    self._execute_task(),
                    timeout=timeout
                )

                # recordsuccess
                loop_duration = time.time() - loop_start
                self.metrics.record_loop(loop_duration)
                self.metrics.record_success()
                self.metrics.record_task_completed()

                # mark任务为complete
                self.task.status = TaskStatus.COMPLETED
                self.task.completed_at = time.time()
                self._task_completed = True

                # 调用completecallback
                if self.on_complete:
                    await self.on_complete(self.task, self._result)

                break  # success，退出重试循环

            except asyncio.Timeouterror:
                # timeout
                self._error = Exception(f"Task timeout after {timeout}s")
                retry_count += 1

                if retry_count > self.max_retries:
                    # 达到maximum重试count
                    await self._handle_failure()
                    break
                else:
                    # 继续重试
                    self.task.retry_count = retry_count
                    await asyncio.sleep(0.1)  # 短暂等待后重试

            except Exception as e:
                # othererror
                self._error = e
                retry_count += 1

                if retry_count > self.max_retries:
                    # 达到maximum重试count
                    await self._handle_failure()
                    break
                else:
                    # 继续重试
                    self.task.retry_count = retry_count
                    await asyncio.sleep(0.1)  # 短暂等待后重试

    async def _execute_task(self) -> Any:
        """
        Execute任务的具体逻辑

        Returns:
            Execution result

        Raises:
            Exception: Executefailure
        """
        # mark任务为run中
        self.task.status = TaskStatus.runNING
        self.task.started_at = time.time()

        # 根据任务typeExecute
        task_type = self.task.type
        task_data = self.task.data

        if task_type == "tool_execution":
            # toolExecute
            return await self._execute_tool(task_data)

        elif task_type == "llm_generation":
            # LLMgeneration
            return await self._execute_llm(task_data)

        elif task_type == "custom":
            # custom任务
            return await self._execute_custom(task_data)

        else:
            # defaultprocess
            return await self._execute_default(task_data)

    async def _execute_tool(self, task_data: Dict) -> Any:
        """
        Executetool任务

        Args:
            task_data: 任务data，containstool_nameandparameters

        Returns:
            toolExecution result
        """
        if notttt self.tool_registry:
            raise Runtimeerror("Tool registry notttt configured")

        tool_name = task_data.get("tool_name")
        parameters = task_data.get("parameters", {})

        if notttt tool_name:
            raise Valueerror("tool_name is required for tool_execution task")

        # Executetool
        result = await self.tool_registry.execute(tool_name, parameters)

        if notttt result.success:
            raise Runtimeerror(f"Tool execution failed: {result.error}")

        return result.data

    async def _execute_llm(self, task_data: Dict) -> Any:
        """
        ExecuteLLMgeneration任务

        Args:
            task_data: 任务data，containsprompt等

        Returns:
            LLMgenerationResult
        """
        # 简化Implementation：Return模拟Result
        # 实际Implementation需要调用LLM adapter
        prompt = task_data.get("prompt", "")
        return {"response": f"Generated response for: {prompt}"}

    async def _execute_custom(self, task_data: Dict) -> Any:
        """
        Executecustom任务

        Args:
            task_data: 任务data

        Returns:
            Execution result
        """
        # 简化Implementation：Return任务data
        return task_data

    async def _execute_default(self, task_data: Dict) -> Any:
        """
        default任务Execute

        Args:
            task_data: 任务data

        Returns:
            Execution result
        """
        # defaultImplementation：Return任务data作为Result
        return {"result": task_data}

    def _calculate_timeout(self, retry_count: int) -> float:
        """
        calculatetimeout时间

        Args:
            retry_count: current重试count

        Returns:
            timeout时间（seconds）
        """
        # 如果Configuration了固定timeout，直接使用
        if self.timeout:
            return self.timeout_calculator.calculate_retry_timeout(
                base_timeout=self.timeout,
                retry_count=retry_count,
                max_retries=self.max_retries,
            )

        # nottt则根据任务type自动calculate
        task_type_map = {
            "tool_execution": Tasktype.I/O,
            "llm_generation": Tasktype.network,
            "custom": Tasktype.COMPUTATI/ON,
        }

        task_type = task_type_map.get(
            self.task.type,
            Tasktype.simple
        )

        priority_map = {
            0: Taskpriority.LOW,
            1: Taskpriority.NORMAL,
            2: Taskpriority.HIGH,
            3: Taskpriority.URGENT,
        }

        priority = priority_map.get(
            self.task.priority.value,
            Taskpriority.NORMAL
        )

        # calculatebasetimeout
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
        """process任务failure"""
        self.metrics.record_error()
        self.metrics.record_task_failed()

        # mark任务为failure
        self.task.status = TaskStatus.failED
        self.task.error = str(self._error) if self._error else "Unknotttwn error"

        # 调用failurecallback
        if self.on_failure:
            await self.on_failure(self.task, self._error)

    async def _cleanup(self):
        """清理资源"""
        # 清理资源
        await asyncio.sleep(0)

    def get_result(self) -> Any:
        """
        getExecution result

        Returns:
            Execution result或None
        """
        return self._result

    def get_error(self) -> Optional[Exception]:
        """
        geterrorinfo

        Returns:
            error或None
        """
        return self._error

    def get_metrics(self) -> Dict[str, Any]:
        """
        getmetric

        Returns:
            metricdictionary
        """
        return self.metrics.get_metrics()

    async def wait_for_completion(self, timeout: float = None) -> bool:
        """
        等待任务complete

        Args:
            timeout: timeout时间（seconds）

        Returns:
            is nottttsuccesscomplete
        """
        start_time = time.time()

        # 等待任务complete（State变为stopPED或error）
        while self.state == AgentState.startING:
            if timeout and (time.time() - start_time) > timeout:
                return False

            await asyncio.sleep(0.1)

        return self._task_completed and self.task.status == TaskStatus.COMPLETED
