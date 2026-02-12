"""
任务数据库 - SQLite持久化存储

支持：
- 任务持久化存储
- 任务状态更新
- 任务恢复（系统重启后）
- 任务查询和统计
"""
import asyncio
import aiosqlite
import json
import time
import uuid
from typing import List, Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass, asdict


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"           # 待处理
    PROCESSING = "processing"     # 处理中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消
    TIMEOUT = "timeout"          # 超时


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    EMERGENCY = 5


class TaskType(Enum):
    """任务类型"""
    QUERY = "query"              # 查询类
    COMPUTATION = "computation"  # 计算类
    INTERACTIVE = "interactive"  # 交互类
    BATCH = "batch"              # 批处理类


@dataclass
class Task:
    """任务数据结构"""
    task_id: str
    type: str                    # TaskType.value
    status: str                  # TaskStatus.value
    priority: int                # TaskPriority.value
    data: Dict[str, Any]         # 任务数据
    assigned_to: Optional[str] = None  # 分配给的TaskAgent ID
    parent_id: Optional[str] = None    # 父任务ID（用于子任务）
    retry_count: int = 0               # 重试次数
    max_retries: int = 3               # 最大重试次数
    timeout: float = 60.0              # 超时时间（秒）
    created_at: float = 0.0            # 创建时间
    started_at: Optional[float] = None  # 开始时间
    completed_at: Optional[float] = None  # 完成时间
    error_message: Optional[str] = None  # 错误信息
    result: Optional[Dict[str, Any]] = None  # 执行结果

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        # 序列化data字段为JSON字符串
        if self.data is not None:
            data['data'] = json.dumps(self.data)
        if self.result is not None:
            data['result'] = json.dumps(self.result)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从字典创建Task"""
        # 反序列化data和result字段
        if isinstance(data.get('data'), str):
            data['data'] = json.loads(data['data'])
        if isinstance(data.get('result'), str):
            data['result'] = json.loads(data['result'])
        return cls(**data)


class TaskDatabase:
    """
    任务数据库

    使用SQLite持久化存储任务，支持任务恢复
    """

    def __init__(self, db_path: str = "~/.magi/data/tasks.db"):
        """
        初始化任务数据库

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def _expanded_db_path(self) -> str:
        """获取展开后的数据库路径（处理 ~）"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def _init_db(self):
        """初始化数据库表"""
        if self._initialized:
            return

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 创建任务表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    assigned_to TEXT,
                    parent_id TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    timeout REAL DEFAULT 60.0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    error_message TEXT,
                    result TEXT
                )
            """)

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status_priority
                ON tasks(status, priority DESC, created_at ASC)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to
                ON tasks(assigned_to, status)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_parent_id
                ON tasks(parent_id)
            """)

            await db.commit()

        self._initialized = True

    async def create_task(
        self,
        task_type: TaskType,
        priority: TaskPriority = TaskPriority.NORMAL,
        data: Dict[str, Any] = None,
        parent_id: str = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> Task:
        """创建新任务"""
        await self._init_db()

        task_id = str(uuid.uuid4())

        task = Task(
            task_id=task_id,
            type=task_type.value,
            status=TaskStatus.PENDING.value,
            priority=priority.value,
            data=data or {},
            parent_id=parent_id,
            timeout=timeout,
            max_retries=max_retries,
        )

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                await db.execute("""
                    INSERT INTO tasks (
                        task_id, type, status, priority, data, parent_id,
                        retry_count, max_retries, timeout, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task.task_id, task.type, task.status, task.priority,
                    json.dumps(task.data), task.parent_id,
                    task.retry_count, task.max_retries, task.timeout, task.created_at
                ))
                await db.commit()

        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return self._row_to_task(row)

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        assigned_to: str = None,
        error_message: str = None,
        result: Dict[str, Any] = None,
    ) -> bool:
        """更新任务状态"""
        await self._init_db()

        update_fields = ["status = ?"]
        update_values = [status.value]

        now = time.time()

        if status == TaskStatus.PROCESSING:
            update_fields.append("started_at = ?")
            update_values.append(now)
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED]:
            update_fields.append("completed_at = ?")
            update_values.append(now)

        if assigned_to is not None:
            update_fields.append("assigned_to = ?")
            update_values.append(assigned_to)

        if error_message is not None:
            update_fields.append("error_message = ?")
            update_values.append(error_message)

        if result is not None:
            update_fields.append("result = ?")
            update_values.append(json.dumps(result))

        update_values.append(task_id)

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                await db.execute(f"""
                    UPDATE tasks SET {', '.join(update_fields)}
                    WHERE task_id = ?
                """, update_values)
                await db.commit()

        return True

    async def increment_retry_count(self, task_id: str) -> int:
        """增加任务重试次数"""
        await self._init_db()

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                await db.execute("""
                    UPDATE tasks SET retry_count = retry_count + 1
                    WHERE task_id = ?
                """, (task_id,))
                await db.commit()

        task = await self.get_task(task_id)
        return task.retry_count if task else 0

    async def get_pending_tasks(
        self,
        limit: int = 100,
        assigned_to: str = None,
    ) -> List[Task]:
        """获取待处理任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            if assigned_to:
                cursor = await db.execute("""
                    SELECT * FROM tasks
                    WHERE status = ? AND assigned_to = ?
                    ORDER BY priority DESC, created_at ASC
                    LIMIT ?
                """, (TaskStatus.PENDING.value, assigned_to, limit))
            else:
                cursor = await db.execute("""
                    SELECT * FROM tasks
                    WHERE status = ?
                    ORDER BY priority DESC, created_at ASC
                    LIMIT ?
                """, (TaskStatus.PENDING.value, limit))

            rows = await cursor.fetchall()

            return [self._row_to_task(row) for row in rows]

    async def get_tasks_by_status(
        self,
        status: TaskStatus,
        limit: int = 100,
    ) -> List[Task]:
        """按状态获取任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (status.value, limit))

            rows = await cursor.fetchall()

            return [self._row_to_task(row) for row in rows]

    async def get_child_tasks(self, parent_id: str) -> List[Task]:
        """获取子任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE parent_id = ?
                ORDER BY priority DESC, created_at ASC
            """, (parent_id,))

            rows = await cursor.fetchall()

            return [self._row_to_task(row) for row in rows]

    async def get_stats(self) -> Dict[str, Any]:
        """获取任务统计信息"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 总任务数
            cursor = await db.execute("SELECT COUNT(*) FROM tasks")
            total = (await cursor.fetchone())[0]

            # 各状态任务数
            cursor = await db.execute("""
                SELECT status, COUNT(*) FROM tasks GROUP BY status
            """)
            status_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            # 各优先级任务数
            cursor = await db.execute("""
                SELECT priority, COUNT(*) FROM tasks GROUP BY priority
            """)
            priority_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            return {
                "total": total,
                "by_status": status_counts,
                "by_priority": priority_counts,
            }

    async def cleanup_old_tasks(
        self,
        days: int = 7,
        keep_status: List[TaskStatus] = None,
    ) -> int:
        """清理旧任务"""
        await self._init_db()

        keep_status = keep_status or [TaskStatus.PENDING, TaskStatus.PROCESSING]

        cutoff_time = time.time() - (days * 86400)

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                # 构建SQL
                status_list = ', '.join(f"'{s.value}'" for s in keep_status)
                cursor = await db.execute(f"""
                    DELETE FROM tasks
                    WHERE completed_at < ?
                    AND status NOT IN ({status_list})
                """, (cutoff_time,))

                deleted_count = cursor.rowcount
                await db.commit()

        return deleted_count

    def _row_to_task(self, row) -> Task:
        """将数据库行转换为Task对象"""
        columns = [
            'task_id', 'type', 'status', 'priority', 'data', 'assigned_to',
            'parent_id', 'retry_count', 'max_retries', 'timeout',
            'created_at', 'started_at', 'completed_at', 'error_message', 'result'
        ]

        data_dict = dict(zip(columns, row))

        # 反序列化JSON字段
        if data_dict.get('data'):
            data_dict['data'] = json.loads(data_dict['data'])
        else:
            data_dict['data'] = {}

        if data_dict.get('result'):
            data_dict['result'] = json.loads(data_dict['result'])

        return Task(**data_dict)

    async def close(self):
        """关闭数据库连接"""
        # SQLite不需要显式关闭连接池
        pass
