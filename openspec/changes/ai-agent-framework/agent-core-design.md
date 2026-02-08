# Agent Core（三层Agent架构）完整设计

## 核心架构

```
┌─────────────────────────────────────────────┐
│  第一层：Master Agent（主Agent）            │
│  - 任务识别与分发                          │
│  - 系统监控与自愈                          │
│  - 任务数据库管理                          │
└─────────────────────────────────────────────┘
                    ↓ 创建任务
┌─────────────────────────────────────────────┐
│  任务数据库（Task Database）                │
│  - 持久化任务队列                           │
│  - 任务状态跟踪                             │
│  - 优先级调度                               │
└─────────────────────────────────────────────┘
                    ↓ 扫描任务
┌─────────────────────────────────────────────┐
│  第二层：TaskAgent（固定数量，配置化）      │
│  - 任务识别与拆解                          │
│  - 记忆和工具匹配                          │
│  - 子任务编排与超时控制                    │
│  - WorkerAgent生命周期管理                 │
└─────────────────────────────────────────────┘
                    ↓ 创建Worker
┌─────────────────────────────────────────────┐
│  第三层：WorkerAgent（无状态，用完即销）   │
│  - 轻量级执行单元                           │
│  - 接收记忆、工具、输入                      │
│  - 执行并输出                               │
│  - 独立超时控制                             │
└─────────────────────────────────────────────┘
```

---

## 1. Master Agent（主Agent）

### 核心职责
1. **任务识别**：从感知输入中识别任务
2. **任务分发**：将任务记录到数据库
3. **系统监控**：监控系统健康状态
4. **异常恢复**：重启异常的TaskAgent
5. **内务管理**：周期性维护任务（整理记忆等）

### 完整实现

```python
class MasterAgent:
    """主Agent - 系统管理与任务分发"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.state = AgentState.IDLE
        self.llm = config.llm

        # 核心组件
        self.perception_manager = PerceptionManager(config.perception)
        self.task_database = TaskDatabase(config.database)
        self.system_monitor = SystemMonitor()

        # TaskAgent管理（固定数量，从配置读取）
        self.task_agents: Dict[str, TaskAgent] = {}
        self.num_task_agents = config.get("num_task_agents", 3)

        # WorkerAgent跟踪（用于超时清理）
        self.worker_agents: Dict[str, WorkerInfo] = {}

    async def start(self):
        """启动主Agent"""
        logger.info("Master Agent 启动中...")
        self.state = AgentState.INITIALIZING

        # 1. 启动系统监控
        await self.system_monitor.start()

        # 2. 启动感知器
        await self.perception_manager.start()

        # 3. 初始化任务数据库
        await self.task_database.initialize()

        # 4. 启动固定数量的TaskAgent
        for i in range(self.num_task_agents):
            task_agent = TaskAgent(
                id=f"task_agent_{i}",
                config=self.config,
                task_database=self.task_database,
                master_agent=self  # 引用，用于异常通知
            )
            await task_agent.start()
            self.task_agents[task_agent.id] = task_agent

        # 5. 启动内务任务（周期性整理记忆等）
        asyncio.create_task(self._internal_tasks_loop())

        # 6. 进入主循环
        self.state = AgentState.RUNNING
        await self._main_loop()

    async def _main_loop(self):
        """主循环"""
        while self.state == AgentState.RUNNING:
            try:
                # 1. 获取感知输入
                perceptions = await self.perception_manager.perceive()

                # 2. 任务识别
                for perception in perceptions:
                    tasks = await self._recognize_tasks(perception)

                    # 3. 记录到任务数据库
                    for task in tasks:
                        await self.task_database.add(task)

                        logger.info(
                            f"任务已创建: {task.id}, "
                            f"类型: {task.type}, "
                            f"优先级: {task.priority}"
                        )

                # 4. 系统监控检查
                await self._check_system_health()

                # 5. 短暂休眠
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"主循环异常: {e}", exc_info=True)
                await asyncio.sleep(1)  # 异常后休眠再继续

    async def _recognize_tasks(
        self,
        perception: Perception
    ) -> List[Task]:
        """从感知输入识别任务"""

        tasks = []

        try:
            # 根据感知类型识别
            if perception.type == PerceptionType.TEXT:
                # 用户消息 → 可能是用户任务
                user_task = await self._recognize_user_task(perception)
                if user_task:
                    tasks.append(user_task)

            elif perception.type == PerceptionType.EVENT:
                # 事件 → 可能是周期性任务
                event_task = await self._recognize_event_task(perception)
                if event_task:
                    tasks.append(event_task)

            # 内在任务（整理记忆等）
            internal_tasks = await self._generate_internal_tasks()
            tasks.extend(internal_tasks)

        except Exception as e:
            logger.error(f"任务识别异常: {e}")

        return tasks

    async def _recognize_user_task(
        self,
        perception: Perception
    ) -> Optional[Task]:
        """识别用户任务"""

        try:
            prompt = f"""
            用户输入：{perception.data}

            请判断这是一个用户任务吗？
            如果是，提取：
            1. 任务描述
            2. 任务类型（如：information_retrieval, communication, task_execution等）
            3. 优先级（0-5，5最高）
            4. 是否需要用户交互

            格式：JSON
            {{
                "is_task": true/false,
                "description": "任务描述",
                "type": "information_retrieval",
                "priority": 3,
                "requires_user_interaction": false
            }}
            """

            response = await self.llm.generate(prompt)
            result = json.loads(response)

            if result.get("is_task", False):
                return Task(
                    id=str(uuid.uuid4()),
                    type=result["type"],
                    description=result["description"],
                    priority=result.get("priority", 3),
                    source="user",
                    requires_user_interaction=result.get("requires_user_interaction", False),
                    metadata={"perception_id": perception.id}
                )

        except Exception as e:
            logger.error(f"用户任务识别失败: {e}")

        return None

    async def _recognize_event_task(
        self,
        perception: Perception
    ) -> Optional[Task]:
        """识别事件任务"""

        # 事件类型任务通常有明确的触发条件
        event_data = perception.data

        # 检查是否是定时任务
        if "schedule" in event_data:
            return Task(
                id=str(uuid.uuid4()),
                type="scheduled_task",
                description=event_data.get("description"),
                priority=event_data.get("priority", 2),
                source="event",
                schedule=event_data.get("schedule"),
                metadata=event_data
            )

        return None

    async def _generate_internal_tasks(self) -> List[Task]:
        """生成内在任务（内务管理）"""

        tasks = []

        try:
            # 检查是否需要整理记忆
            if await self._should_organize_memory():
                tasks.append(Task(
                    id=str(uuid.uuid4()),
                    type="memory_organization",
                    description="整理和总结记忆",
                    priority=2,
                    source="internal",
                    requires_user_interaction=False,
                    timeout=300,  # 5分钟超时
                    metadata={"task_type": "maintenance"}
                ))

            # 检查是否需要健康检查
            if await self._should_health_check():
                tasks.append(Task(
                    id=str(uuid.uuid4()),
                    type="health_check",
                    description="系统健康检查",
                    priority=1,
                    source="internal",
                    requires_user_interaction=False,
                    timeout=60,
                    metadata={"task_type": "maintenance"}
                ))

        except Exception as e:
            logger.error(f"内在任务生成失败: {e}")

        return tasks

    async def _should_organize_memory(self) -> bool:
        """判断是否需要整理记忆"""
        # 简化实现：每天凌晨3点整理
        now = datetime.now()
        if now.hour == 3 and now.minute < 5:
            # 检查今天是否已经整理过
            last_organized = await self.task_database.get_last_internal_task("memory_organization")
            if not last_organized or (now - last_organized.created_at).days >= 1:
                return True
        return False

    async def _should_health_check(self) -> bool:
        """判断是否需要健康检查"""
        # 每小时检查一次
        now = time.time()
        last_check = getattr(self, '_last_health_check', 0)

        if now - last_check >= 3600:
            self._last_health_check = now
            return True

        return False

    async def _check_system_health(self):
        """检查系统健康"""

        try:
            # 1. 获取系统监控数据
            metrics = await self.system_monitor.get_metrics()

            logger.debug(
                f"系统监控: CPU={metrics.cpu_usage}%, "
                f"内存={metrics.memory_usage}MB"
            )

            # 2. 检查TaskAgent是否存活
            for agent_id, agent in list(self.task_agents.items()):
                if not agent.is_alive():
                    logger.warning(f"TaskAgent {agent_id} 异常退出，正在重启...")
                    await self._restart_task_agent(agent_id)

            # 3. 清理僵尸WorkerAgent
            await self._cleanup_zombie_workers()

        except Exception as e:
            logger.error(f"系统健康检查异常: {e}")

    async def _restart_task_agent(self, agent_id: str):
        """重启TaskAgent"""

        try:
            old_agent = self.task_agents.get(agent_id)
            if old_agent:
                await old_agent.stop()
                del self.task_agents[agent_id]

            # 创建新的TaskAgent
            new_agent = TaskAgent(
                id=agent_id,
                config=self.config,
                task_database=self.task_database,
                master_agent=self
            )

            await new_agent.start()
            self.task_agents[agent_id] = new_agent

            logger.info(f"TaskAgent {agent_id} 已重启")

        except Exception as e:
            logger.error(f"重启TaskAgent {agent_id} 失败: {e}")

    async def _cleanup_zombie_workers(self):
        """清理僵尸WorkerAgent"""

        now = time.time()
        zombie_ids = []

        for worker_id, worker_info in list(self.worker_agents.items()):
            # 检查是否超时
            if now - worker_info.last_heartbeat > 600:  # 10分钟无心跳
                logger.warning(f"WorkerAgent {worker_id} 超时，清理中...")
                zombie_ids.append(worker_id)

            # 检查TaskAgent是否还引用这个Worker
            if not self._is_worker_referenced(worker_id):
                del self.worker_agents[worker_id]

    def _is_worker_referenced(self, worker_id: str) -> bool:
        """检查Worker是否被TaskAgent引用"""
        for task_agent in self.task_agents.values():
            if worker_id in task_agent.worker_agents:
                return True
        return False

    async def stop(self):
        """停止主Agent"""
        logger.info("Master Agent 停止中...")
        self.state = AgentState.STOPPING

        # 停止所有TaskAgent
        for agent in list(self.task_agents.values()):
            await agent.stop()

        # 停止组件
        await self.perception_manager.stop()
        await self.system_monitor.stop()

        self.state = AgentState.STOPPED
        logger.info("Master Agent 已停止")
```

---

## 2. Task Database（任务数据库）

### 数据库结构

```python
class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"          # 待处理
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"           # 失败
    TIMEOUT = "timeout"         # 超时
    CANCELLED = "cancelled"      # 已取消


@dataclass
class Task:
    """任务"""
    id: str                          # 任务ID
    type: str                        # 任务类型
    description: str                 # 任务描述
    priority: int                    # 优先级（0-5）
    status: TaskStatus               # 任务状态
    source: str                      # 任务来源（user/internal/event）
    requires_user_interaction: bool # 是否需要用户交互
    timeout: Optional[int]           # 总超时时间（秒）
    created_at: float                # 创建时间
    updated_at: float                # 更新时间
    scheduled_at: Optional[float]    # 计划执行时间
    parent_id: Optional[str]         # 父任务ID
    metadata: Dict = None             # 额外元数据

    # 输入数据
    input_data: Any = None


@dataclass
class SubTask:
    """子任务"""
    id: str                          # 子任务ID
    parent_id: str                   # 父任务ID
    description: str                 # 子任务描述
    tool_name: str                   # 工具名称
    memory_required: List[str]      # 需要的记忆
    input_data: Any                  # 输入数据
    status: TaskStatus               # 状态
    result: Optional[Any]            # 执行结果
    error: Optional[str]             # 错误信息
    timeout: Optional[int]           # 超时时间（秒）
    retry_count: int = 0             # 重试次数
    max_retries: int = 3             # 最大重试次数
    depends_on: List[int] = None     # 依赖的子任务索引列表
    created_at: float = None          # 创建时间
    completed_at: Optional[float] = None  # 完成时间


class TaskDatabase:
    """任务数据库"""

    def __init__(self, config: dict):
        self.db_path = config.get("db_path", "./data/tasks.db")
        self.db = None
        self.max_retries = config.get("max_retries", 3)

    async def initialize(self):
        """初始化数据库"""
        self.db = await aiosqlite.connect(self.db_path)
        await self._create_tables()

    async def _create_tables(self):
        """创建表结构"""

        # 任务表
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                requires_user_interaction INTEGER DEFAULT 0,
                timeout INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                scheduled_at REAL,
                parent_id TEXT,
                input_data TEXT,
                metadata TEXT,
                FOREIGN KEY (parent_id) REFERENCES tasks(id)
            )
        """)

        # 子任务表
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS subtasks (
                id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                description TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                memory_required TEXT,
                input_data TEXT,
                status TEXT NOT NULL,
                result TEXT,
                error TEXT,
                timeout INTEGER,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                depends_on TEXT,
                created_at REAL NOT NULL,
                completed_at REAL,
                FOREIGN KEY (parent_id) REFERENCES tasks(id)
            )
        """)

        # 索引
        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status)
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_priority
            ON tasks(priority DESC, created_at ASC)
        """)

        await self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_subtasks_status
            ON subtasks(status)
        """)

    async def add(self, task: Task) -> str:
        """添加任务"""
        await self.db.execute(
            """INSERT INTO tasks (
                id, type, description, priority, status, source,
                requires_user_interaction, timeout, created_at, updated_at,
                input_data, metadata, parent_id, scheduled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id, task.type, task.description,
                task.priority, task.status.value,
                task.source, int(task.requires_user_interaction),
                task.timeout, task.created_at, task.updated_at,
                json.dumps(task.input_data) if task.input_data else None,
                json.dumps(task.metadata) if task.metadata else None,
                task.parent_id, task.scheduled_at
            )
        )
        return task.id

    async def get_pending_tasks(self) -> List[Task]:
        """获取待处理任务"""
        cursor = await self.db.execute("""
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT 100
        """)

        rows = await cursor.fetchall()
        return [Task.from_row(row) for row in rows]

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: str = None
    ):
        """更新任务状态"""
        await self.db.execute(
            """UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?""",
            (status.value, time.time(), task_id)
        )

    async def save_subtask_result(
        self,
        subtask_id: str,
        result: Any,
        success: bool
    ):
        """保存子任务结果"""
        if success:
            await self.db.execute(
                """UPDATE subtasks SET status = ?, result = ?, completed_at = ? WHERE id = ?""",
                (TaskStatus.COMPLETED.value, json.dumps(result), time.time(), subtask_id)
            )
        else:
            await self.db.execute(
                """UPDATE subtasks SET status = ?, completed_at = ? WHERE id = ?""",
                (TaskStatus.FAILED.value, time.time(), subtask_id)
            )

    async def get_subtasks(self, parent_id: str) -> List[SubTask]:
        """获取任务的所有子任务"""
        cursor = await self.db.execute(
            """SELECT * FROM subtasks WHERE parent_id = ? ORDER BY id""",
            (parent_id,)
        )

        rows = await cursor.fetchall()
        return [SubTask.from_row(row) for row in rows]

    async def get_last_internal_task(self, task_type: str) -> Optional[Task]:
        """获取最近的内在任务"""
        cursor = await self.db.execute("""
            SELECT * FROM tasks
            WHERE source = 'internal' AND type = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (task_type,))

        row = await cursor.fetchone()
        return Task.from_row(row) if row else None
```

---

## 3. TaskAgent（任务Agent）

### 核心职责
1. **扫描任务数据库**：定期获取待处理任务
2. **任务拆解**：将复杂任务拆分为子任务
3. **工具匹配**：判断需要什么工具和记忆
4. **超时控制**：计算任务总超时时间
5. **Worker管理**：创建和清理WorkerAgent

### 完整实现

```python
class TaskAgent:
    """任务Agent - 任务识别与拆解"""

    def __init__(
        self,
        id: str,
        config: AgentConfig,
        task_database: TaskDatabase,
        master_agent: 'MasterAgent'
    ):
        self.id = id
        self.config = config
        self.task_database = task_database
        self.master_agent = master_agent
        self.llm = config.llm

        # 核心组件
        self.tool_decision_engine = ToolDecisionEngine(config.llm)
        self.memory_store = config.memory_store
        self.tool_registry = config.tool_registry

        # 管理的WorkerAgent
        self.worker_agents: Dict[str, WorkerAgent] = {}

        # 运行标志
        self.is_running = False

    async def start(self):
        """启动任务Agent"""
        logger.info(f"TaskAgent {self.id} 启动中...")
        self.is_running = True

        # 启动任务扫描循环
        asyncio.create_task(self._task_loop())

    async def stop(self):
        """停止任务Agent"""
        logger.info(f"TaskAgent {self.id} 停止中...")
        self.is_running = False

        # 停止所有WorkerAgent
        for worker in list(self.worker_agents.values()):
            await worker.stop()

        self.worker_agents.clear()

    async def _task_loop(self):
        """任务循环"""
        while self.is_running:
            try:
                # 1. 扫描任务数据库
                tasks = await self.task_database.get_pending_tasks()

                if not tasks:
                    await asyncio.sleep(1)
                    continue

                # 2. 处理每个任务
                for task in tasks:
                    if not self.is_running:
                        break

                    try:
                        await self._process_task(task)
                    except Exception as e:
                        logger.error(f"处理任务 {task.id} 失败: {e}")
                        await self.task_database.update_status(
                            task.id,
                            TaskStatus.FAILED,
                            error=str(e)
                        )

            except Exception as e:
                logger.error(f"TaskAgent {self.id} 循环异常: {e}")
                await asyncio.sleep(5)

    async def _process_task(self, task: Task):
        """处理任务"""

        logger.info(f"处理任务: {task.id} - {task.description}")

        # 1. 更新任务状态为处理中
        await self.task_database.update_status(task.id, TaskStatus.PROCESSING)

        # 2. 计算任务总超时时间
        total_timeout = await self._calculate_timeout(task)

        # 3. 任务拆解
        subtasks = await self._decompose_task(task)

        if len(subtasks) == 0:
            # 无法拆解，直接标记完成
            await self.task_database.update_status(task.id, TaskStatus.COMPLETED)
            return

        # 4. 执行子任务
        try:
            await asyncio.wait_for(
                self._execute_subtasks(subtasks),
                timeout=total_timeout
            )
            await self.task_database.update_status(task.id, TaskStatus.COMPLETED)

        except asyncio.TimeoutError:
            logger.warning(f"任务 {task.id} 超时，执行兜底流程")
            await self._handle_task_timeout(task, subtasks)

        except Exception as e:
            logger.error(f"任务 {task.id} 执行异常: {e}")
            await self.task_database.update_status(
                task.id,
                TaskStatus.FAILED,
                error=str(e)
            )

    async def _calculate_timeout(self, task: Task) -> int:
        """计算任务总超时时间"""

        # 基础超时
        base_timeout = 300  # 5分钟

        # 根据优先级调整
        priority_multiplier = {
            0: 2.0,  # 最低优先级，最长超时
            1: 1.5,
            2: 1.0,
            3: 0.8,
            4: 0.5,
            5: 0.3   # 最高优先级，最短超时
        }

        # 根据是否用户交互调整
        interaction_multiplier = 2.0 if task.requires_user_interaction else 1.0

        # 根据任务类型调整
        type_multiplier = {
            "information_retrieval": 1.0,
            "communication": 1.5,
            "task_execution": 2.0,
            "memory_organization": 3.0,
        }

        timeout = base_timeout
        timeout *= priority_multiplier.get(task.priority, 1.0)
        timeout *= interaction_multiplier
        timeout *= type_multiplier.get(task.type, 1.0)

        return int(timeout)

    async def _decompose_task(self, task: Task) -> List[SubTask]:
        """拆解任务"""

        try:
            # 获取可用工具
            available_tools = self.tool_registry.list_public()

            prompt = f"""
            任务描述：{task.description}
            任务类型：{task.type}
            任务输入：{task.input_data}

            可用工具：
            {[f"{t.name}: {t.description}" for t in available_tools]}

            请将任务拆解为子任务：
            1. 每个子任务需要什么工具
            2. 每个子任务需要什么记忆（上下文）
            3. 子任务之间的依赖关系（数组索引）

            格式：JSON
            [
                {{
                    "description": "搜索最新AI新闻",
                    "tool": "web_search",
                    "memory": ["user_preferences", "search_history"],
                    "input": {{"query": "AI news"}},
                    "depends_on": [],
                    "timeout": 30
                }},
                {{
                    "description": "总结新闻内容",
                    "tool": "summarize",
                    "memory": ["search_results"],
                    "input": {{}},
                    "depends_on": [0],
                    "timeout": 60
                }}
            ]
            """

            response = await self.llm.generate(prompt)
            subtask_data = json.loads(response)

            subtasks = []
            for i, data in enumerate(subtask_data):
                subtasks.append(SubTask(
                    id=f"{task.id}_sub_{i}",
                    parent_id=task.id,
                    description=data["description"],
                    tool_name=data["tool"],
                    memory_required=data.get("memory", []),
                    input_data=data.get("input", {}),
                    depends_on=data.get("depends_on", []),
                    timeout=data.get("timeout", 60),
                    created_at=time.time()
                ))

            return subtasks

        except Exception as e:
            logger.error(f"任务拆解失败: {e}")
            return []

    async def _execute_subtasks(self, subtasks: List[SubTask]):
        """执行子任务（支持并行）"""

        # 构建DAG
        dag = self._build_dag(subtasks)

        # 拓扑排序执行
        for subtask in dag.topological_sort():
            # 检查依赖是否满足
            if not self._dependencies_satisfied(subtask, subtasks):
                logger.warning(f"子任务 {subtask.id} 依赖未满足，等待...")
                await asyncio.sleep(1)
                continue

            # 创建WorkerAgent执行
            worker = WorkerAgent(
                id=subtask.id,
                config=self.config,
                tool_registry=self.tool_registry,
                memory_store=self.memory_store
            )

            self.worker_agents[subtask.id] = worker

            # 执行（带超时）
            try:
                result = await asyncio.wait_for(
                    worker.execute(subtask),
                    timeout=subtask.timeout
                )

                # 保存结果
                await self.task_database.save_subtask_result(
                    subtask.id, result, True
                )

            except asyncio.TimeoutError:
                logger.warning(f"子任务 {subtask.id} 超时，重试中...")
                await self._retry_subtask(subtask)

            finally:
                # 用完即销毁
                await worker.stop()
                del self.worker_agents[subtask.id]

    def _build_dag(self, subtasks: List[SubTask]) -> 'DAG':
        """构建任务DAG"""
        return DAG(subtasks)

    def _dependencies_satisfied(self, subtask: SubTask, all_subtasks: List[SubTask]) -> bool:
        """检查依赖是否满足"""
        if not subtask.depends_on:
            return True

        # 检查所有依赖是否完成
        for dep_idx in subtask.depends_on:
            dep_subtask = all_subtasks[dep_idx]
            if dep_subtask.status != TaskStatus.COMPLETED:
                return False

        return True

    async def _retry_subtask(self, subtask: SubTask):
        """重试子任务"""

        if subtask.retry_count >= subtask.max_retries:
            logger.error(f"子任务 {subtask.id} 重试次数耗尽")
            await self.task_database.save_subtask_result(
                subtask.id, None, False
            )
            return

        subtask.retry_count += 1

        # 创建新的WorkerAgent执行
        worker = WorkerAgent(
            id=f"{subtask.id}_retry_{subtask.retry_count}",
            config=self.config,
            tool_registry=self.tool_registry,
            memory_store=self.memory_store
        )

        try:
            result = await asyncio.wait_for(
                worker.execute(subtask),
                timeout=subtask.timeout
            )

            await self.task_database.save_subtask_result(
                subtask.id, result, True
            )

        finally:
            await worker.stop()

    async def _handle_task_timeout(self, task: Task, subtasks: List[SubTask]):
        """处理任务超时 - 兜底流程"""

        logger.warning(f"任务 {task.id} 超时，执行兜底流程")

        # 策略1：关闭超时的WorkerAgent
        for worker_id, worker in list(self.worker_agents.items()):
            if worker.is_busy():
                await worker.stop()
                del self.worker_agents[worker_id]

        # 策略2：创建新的TaskAgent重新执行
        # 使用更长的超时时间
        fallback_task = Task(
            id=f"{task.id}_fallback",
            type=task.type,
            description=f"{task.description}（兜底）",
            priority=max(task.priority - 1, 0),
            source="fallback",
            requires_user_interaction=False,
            timeout=task.timeout * 2,  # 双倍超时
            input_data=task.input_data
        )

        await self.task_database.add(fallback_task)

    def is_alive(self) -> bool:
        """检查Agent是否存活"""
        return self.is_running
```

---

## 4. WorkerAgent（子Agent）

### 核心设计原则
- **无状态**：每次执行完就可以销毁
- **轻量级**：最小化依赖和初始化
- **独立超时**：每个Worker有独立的超时控制
- **幂等性支持**：外部系统调用需要幂等

### 完整实现

```python
class WorkerAgent:
    """Worker Agent - 无状态执行单元"""

    def __init__(
        self,
        id: str,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        memory_store: MemoryStore
    ):
        self.id = id
        self.config = config
        self.tool_registry = tool_registry
        self.memory_store = memory_store
        self.is_busy = False

    async def execute(self, subtask: SubTask) -> WorkerResult:
        """执行子任务"""
        self.is_busy = True

        try:
            logger.info(f"WorkerAgent {self.id} 执行子任务: {subtask.description}")

            # 1. 从记忆加载上下文
            context = await self._load_context(subtask.memory_required)

            # 2. 合并输入数据
            full_input = {**context, **subtask.input_data}

            # 3. 执行工具（支持幂等）
            result = await self._execute_tool_idempotent(
                subtask.tool_name,
                full_input
            )

            return WorkerResult(
                worker_id=self.id,
                success=result.success,
                data=result.data,
                error=result.error
            )

        finally:
            self.is_busy = False

    async def _load_context(self, memory_keys: List[str]) -> Dict:
        """从记忆加载上下文"""

        context = {}
        for key in memory_keys:
            try:
                # 从记忆中检索
                memories = await self.memory_store.recall(key, top_k=5)
                context[key] = memories
            except Exception as e:
                logger.warning(f"加载记忆 {key} 失败: {e}")
                context[key] = []

        return context

    async def _execute_tool_idempotent(
        self,
        tool_name: str,
        params: dict
    ) -> ToolResult:
        """执行工具（支持幂等）"""

        tool = self.tool_registry.get(tool_name)
        if not tool:
            raise ValueError(f"工具不存在: {tool_name}")

        # 幂等性检查
        if await self._is_idempotent(tool):
            params = await self._ensure_idempotency(tool, params)

        # 执行工具
        result = await tool.execute(params)

        return result

    async def _is_idempotent(self, tool: Tool) -> bool:
        """判断工具是否需要幂等"""
        # 检查工具元数据
        return tool.metadata.get("idempotent", False)

    async def _ensure_idempotency(
        self,
        tool: Tool,
        params: dict
    ) -> dict:
        """确保幂等性"""

        # 策略1：添加idempotency_key
        if "idempotency_key" not in params:
            params["idempotency_key"] = str(uuid.uuid4())

        # 策略2：检查是否已执行
        executed = await self._check_executed(tool.name, params)
        if executed:
            logger.info(f"工具 {tool.name} 已执行，返回缓存结果")
            return executed

        # 记录执行状态
        await self._mark_executed(tool.name, params)

        return params

    async def _check_executed(self, tool_name: str, params: dict) -> Optional[Any]:
        """检查是否已执行（从缓存）"""
        # 简化实现：可以从内存缓存或Redis检查
        return None

    async def _mark_executed(self, tool_name: str, params: dict):
        """标记已执行"""
        # 记录到缓存，设置TTL
        pass

    async def stop(self):
        """停止WorkerAgent"""
        logger.info(f"WorkerAgent {self.id} 停止")
        # 无状态，直接返回
```

---

## 5. 系统监控（简单实现）

```python
class SystemMonitor:
    """系统监控"""

    def __init__(self):
        self.is_running = False

    async def start(self):
        """启动监控"""
        self.is_running = True
        asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        """监控循环"""
        while self.is_running:
            # 每秒采集一次
            await asyncio.sleep(1)

    async def get_metrics(self) -> SystemMetrics:
        """获取系统指标"""
        import psutil

        return SystemMetrics(
            cpu_usage=psutil.cpu_percent(),
            memory_usage=psutil.virtual_memory().used / (1024 * 1024),  # MB
            timestamp=time.time()
        )


@dataclass
class SystemMetrics:
    cpu_usage: float      # CPU使用率（%）
    memory_usage: float   # 内存使用（MB）
    timestamp: float
```

---

## 6. 配置文件

```yaml
# config/agent.yaml
agent:
  # 主Agent配置
  master:
    num_task_agents: 3    # TaskAgent固定数量

  # TaskAgent配置
  task_agent:
    scan_interval: 1      # 扫描任务间隔（秒）
    max_concurrent_tasks: 5 # 并发处理任务数

  # WorkerAgent配置
  worker_agent:
    max_retries: 3        # 最大重试次数
    default_timeout: 60   # 默认超时（秒）

  # LLM配置
  llm:
    provider: "openai"
    model: "gpt-4"
    api_key: "${OPENAI_API_KEY}"
    timeout: 30

  # 记忆配置
  memory:
    short_term: "memory"
    long_term: "chromadb"

  # 感知器配置
  perception:
    microphone:
      enabled: false
    email:
      enabled: true
      imap_server: "imap.gmail.com"
      username: "${EMAIL_ADDRESS}"
      password: "${EMAIL_PASSWORD}"
    file_monitor:
      enabled: true
      watch_paths:
        - "/path/to/watch"

  # 任务数据库配置
  database:
    db_path: "./data/tasks.db"
    max_retries: 3
```

---

## 7. 目录结构

```
magi/backend/src/magi/core/
├── __init__.py
├── agent.py              # Agent基类
├── master.py            # Master Agent
├── task_agent.py        # Task Agent
├── worker_agent.py      # Worker Agent
├── state.py             # Agent状态定义
├── tasks/
│   ├── database.py       # 任务数据库
│   ├── task.py          # 任务模型
│   └── dag.py           # 任务DAG
└── monitoring/
    ├── monitor.py        # 系统监控
    └── metrics.py        # 监控指标
```

---

## ✅ 核心特性总结

### MasterAgent（第一层）
- ✅ 任务识别（用户/事件/内在）
- ✅ 系统监控（CPU/内存）
- ✅ Agent健康检查和自愈
- ✅ 固定数量TaskAgent（配置化）
- ✅ 任务数据库管理

### TaskAgent（第二层）
- ✅ 扫描任务数据库
- ✅ 任务拆解（LLM决策）
- ✅ 工具和记忆匹配
- ✅ 子任务DAG编排
- ✅ 总超时控制（根据类型/优先级/交互）
- ✅ WorkerAgent生命周期管理
- ✅ 超时兜底机制

### WorkerAgent（第三层）
- ✅ 无状态、轻量级
- ✅ 用完即销毁
- ✅ 独立超时控制
- ✅ 幂等性支持

### 任务数据库
- ✅ 持久化任务队列
- ✅ 子任务管理
- ✅ 状态跟踪
- ✅ SQLite存储

### 系统监控
- ✅ CPU/内存监控
- ✅ 简单实现（psutil）

---

## 📊 完整执行流程

```
用户输入 → MasterAgent感知 → 识别为用户任务
    ↓
写入任务数据库
    ↓
TaskAgent扫描数据库 → 获取任务
    ↓
任务拆解（LLM）→ 生成子任务
    ↓
创建WorkerAgent执行子任务
    ↓
WorkerAgent执行工具 → 返回结果
    ↓
结果写入数据库
    ↓
MasterAgent监控系统健康
```

---

这个设计符合你的想法吗？有需要调整的地方吗？
