"""
任务database - SQLite持久化storage

support：
- 任务持久化storage
- 任务Stateupdate
- 任务restore（系统重启后）
- 任务queryandstatistics
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
    """任务State"""
    pending = "pending"           # pending
    processING = "processing"     # processing
    COMPLETED = "completed"       # completed
    failED = "failed"            # failure
    CANCELLED = "cancelled"      # cancelled
    timeout = "timeout"          # timeout


class TaskPriority(Enum):
    """任务priority"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    EMERGENCY = 5


class TaskType(Enum):
    """任务type"""
    QUERY = "query"              # queryClass
    COMPUTATION = "computation"  # calculateClass
    INTERACTIVE = "interactive"  # 交互Class
    BATCH = "batch"              # 批processClass


@dataclass
class Task:
    """任务datastructure"""
    task_id: str
    type: str                    # TaskType.value
    status: str                  # TaskStatus.value
    priority: int                # TaskPriority.value
    data: Dict[str, Any]         # 任务data
    assigned_to: Optional[str] = None  # 分配给的TaskAgent id
    parent_id: Optional[str] = None    # 父任务id（用于子任务）
    retry_count: int = 0               # 重试count
    max_retries: int = 3               # maximum重试count
    timeout: float = 60.0              # timeout时间（seconds）
    created_at: float = 0.0            # created at
    started_at: Optional[float] = None  # Start时间
    completed_at: Optional[float] = None  # complete时间
    error_message: Optional[str] = None  # errorinfo
    result: Optional[Dict[str, Any]] = None  # Execution result

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """convert为dictionary"""
        data = asdict(self)
        # serializedatafield为JSONstring
        if self.data is not None:
            data['data'] = json.dumps(self.data)
        if self.result is not None:
            data['result'] = json.dumps(self.result)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从dictionarycreateTask"""
        # deserializedataandresultfield
        if isinstance(data.get('data'), str):
            data['data'] = json.loads(data['data'])
        if isinstance(data.get('result'), str):
            data['result'] = json.loads(data['result'])
        return cls(**data)


class TaskDatabase:
    """
    任务database

    使用SQLite持久化storage任务，support任务restore
    """

    def __init__(self, db_path: str = "~/.magi/data/tasks.db"):
        """
        initialize任务database

        Args:
            db_path: databasefilepath
        """
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        from pathlib import Path
        return str(path(self.db_path).expanduser())

    async def _init_db(self):
        """initializedatabasetable"""
        if self._initialized:
            return

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # create任务table
            await db.execute("""
                create table IF NOT EXISTS tasks (
                    task_id TEXT primary key,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority intEGER NOT NULL,
                    data TEXT NOT NULL,
                    assigned_to TEXT,
                    parent_id TEXT,
                    retry_count intEGER DEFAULT 0,
                    max_retries intEGER DEFAULT 3,
                    timeout real DEFAULT 60.0,
                    created_at real NOT NULL,
                    started_at real,
                    completed_at real,
                    error_message TEXT,
                    result TEXT
                )
            """)

            # createindex
            await db.execute("""
                create index IF NOT EXISTS idx_tasks_status_priority
                ON tasks(status, priority DESC, created_at asC)
            """)

            await db.execute("""
                create index IF NOT EXISTS idx_tasks_assigned_to
                ON tasks(assigned_to, status)
            """)

            await db.execute("""
                create index IF NOT EXISTS idx_tasks_parent_id
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
        """createnew任务"""
        await self._init_db()

        task_id = str(uuid.uuid4())

        task = Task(
            task_id=task_id,
            type=task_type.value,
            status=TaskStatus.pending.value,
            priority=priority.value,
            data=data or {},
            parent_id=parent_id,
            timeout=timeout,
            max_retries=max_retries,
        )

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                await db.execute("""
                    INSERT intO tasks (
                        task_id, type, status, priority, data, parent_id,
                        retry_count, max_retries, timeout, created_at
                    ) valueS (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task.task_id, task.type, task.status, task.priority,
                    json.dumps(task.data), task.parent_id,
                    task.retry_count, task.max_retries, task.timeout, task.created_at
                ))
                await db.commit()

        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """get任务"""
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
        """update任务State"""
        await self._init_db()

        update_fields = ["status = ?"]
        update_values = [status.value]

        notttw = time.time()

        if status == TaskStatus.processING:
            update_fields.append("started_at = ?")
            update_values.append(notttw)
        elif status in [TaskStatus.COMPLETED, TaskStatus.failED, TaskStatus.timeout, TaskStatus.CANCELLED]:
            update_fields.append("completed_at = ?")
            update_values.append(notttw)

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
                    update tasks set {', '.join(update_fields)}
                    WHERE task_id = ?
                """, update_values)
                await db.commit()

        return True

    async def increment_retry_count(self, task_id: str) -> int:
        """增加任务重试count"""
        await self._init_db()

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                await db.execute("""
                    update tasks set retry_count = retry_count + 1
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
        """getpending任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            if assigned_to:
                cursor = await db.execute("""
                    SELECT * FROM tasks
                    WHERE status = ? AND assigned_to = ?
                    order BY priority DESC, created_at asC
                    LIMIT ?
                """, (TaskStatus.pending.value, assigned_to, limit))
            else:
                cursor = await db.execute("""
                    SELECT * FROM tasks
                    WHERE status = ?
                    order BY priority DESC, created_at asC
                    LIMIT ?
                """, (TaskStatus.pending.value, limit))

            rows = await cursor.fetchall()

            return [self._row_to_task(row) for row in rows]

    async def get_tasks_by_status(
        self,
        status: TaskStatus,
        limit: int = 100,
    ) -> List[Task]:
        """按Stateget任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE status = ?
                order BY created_at DESC
                LIMIT ?
            """, (status.value, limit))

            rows = await cursor.fetchall()

            return [self._row_to_task(row) for row in rows]

    async def get_child_tasks(self, parent_id: str) -> List[Task]:
        """get子任务"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE parent_id = ?
                order BY priority DESC, created_at asC
            """, (parent_id,))

            rows = await cursor.fetchall()

            return [self._row_to_task(row) for row in rows]

    async def get_stats(self) -> Dict[str, Any]:
        """get任务statisticsinfo"""
        await self._init_db()

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 总任务数
            cursor = await db.execute("SELECT COUNT(*) FROM tasks")
            total = (await cursor.fetchone())[0]

            # 各State任务数
            cursor = await db.execute("""
                SELECT status, COUNT(*) FROM tasks group BY status
            """)
            status_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            # 各priority任务数
            cursor = await db.execute("""
                SELECT priority, COUNT(*) FROM tasks group BY priority
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
        """清理old任务"""
        await self._init_db()

        keep_status = keep_status or [TaskStatus.pending, TaskStatus.processING]

        cutoff_time = time.time() - (days * 86400)

        async with self._lock:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                # buildSQL
                status_list = ', '.join(f"'{s.value}'" for s in keep_status)
                cursor = await db.execute(f"""
                    delete FROM tasks
                    WHERE completed_at < ?
                    AND status NOT IN ({status_list})
                """, (cutoff_time,))

                deleted_count = cursor.rowcount
                await db.commit()

        return deleted_count

    def _row_to_task(self, row) -> Task:
        """将databaserowconvert为TaskObject"""
        columns = [
            'task_id', 'type', 'status', 'priority', 'data', 'assigned_to',
            'parent_id', 'retry_count', 'max_retries', 'timeout',
            'created_at', 'started_at', 'completed_at', 'error_message', 'result'
        ]

        data_dict = dict(zip(columns, row))

        # deserializeJSONfield
        if data_dict.get('data'):
            data_dict['data'] = json.loads(data_dict['data'])
        else:
            data_dict['data'] = {}

        if data_dict.get('result'):
            data_dict['result'] = json.loads(data_dict['result'])

        return Task(**data_dict)

    async def close(self):
        """关闭databaseconnection"""
        # SQLite不需要显式关闭connection池
        pass
