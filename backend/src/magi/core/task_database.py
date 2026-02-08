"""
任务数据库 - SQLite持久化存储
"""
import asyncio
import aiosqlite
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import time


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"          # 待处理
    ASSIGNED = "assigned"        # 已分配
    RUNNING = "running"          # 执行中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class Task:
    """任务数据结构"""
    id: str
    type: str                     # 任务类型
    data: Dict[str, Any]          # 任务数据
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_agent: Optional[str] = None  # 分配的Agent ID
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典"""
        d = asdict(self)
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> 'Task':
        """从字典创建"""
        data["status"] = TaskStatus(data["status"])
        data["priority"] = TaskPriority(data["priority"])
        return cls(**data)


class TaskDatabase:
    """
    任务数据库

    使用SQLite持久化存储任务
    """

    def __init__(self, db_path: str = ":memory:"):
        """
        初始化任务数据库

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def start(self):
        """启动数据库（创建表）"""
        self._conn = await aiosqlite.connect(self.db_path)

        # 创建任务表
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                assigned_agent TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                error TEXT,
                metadata TEXT
            )
        """)

        # 创建索引
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status
            ON tasks(status)
        """)

        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_priority
            ON tasks(priority DESC)
        """)

        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_assigned_agent
            ON tasks(assigned_agent)
        """)

        await self._conn.commit()

    async def stop(self):
        """停止数据库"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def create_task(self, task: Task) -> bool:
        """
        创建任务

        Args:
            task: 任务对象

        Returns:
            是否成功
        """
        try:
            await self._conn.execute("""
                INSERT INTO tasks (
                    id, type, data, status, priority, assigned_agent,
                    created_at, updated_at, started_at, completed_at,
                    retry_count, max_retries, error, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id,
                task.type,
                json.dumps(task.data),
                task.status.value,
                task.priority.value,
                task.assigned_agent,
                task.created_at,
                task.updated_at,
                task.started_at,
                task.completed_at,
                task.retry_count,
                task.max_retries,
                task.error,
                json.dumps(task.metadata),
            ))

            await self._conn.commit()
            return True

        except Exception as e:
            print(f"Error creating task: {e}")
            return False

    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        获取任务

        Args:
            task_id: 任务ID

        Returns:
            任务对象或None
        """
        cursor = await self._conn.execute("""
            SELECT * FROM tasks WHERE id = ?
        """, (task_id,))

        row = await cursor.fetchone()

        if row:
            return self._row_to_task(row)

        return None

    async def update_task(self, task: Task) -> bool:
        """
        更新任务

        Args:
            task: 任务对象

        Returns:
            是否成功
        """
        task.updated_at = time.time()

        try:
            await self._conn.execute("""
                UPDATE tasks SET
                    type = ?, data = ?, status = ?, priority = ?,
                    assigned_agent = ?, updated_at = ?, started_at = ?,
                    completed_at = ?, retry_count = ?, max_retries = ?,
                    error = ?, metadata = ?
                WHERE id = ?
            """, (
                task.type,
                json.dumps(task.data),
                task.status.value,
                task.priority.value,
                task.assigned_agent,
                task.updated_at,
                task.started_at,
                task.completed_at,
                task.retry_count,
                task.max_retries,
                task.error,
                json.dumps(task.metadata),
                task.id,
            ))

            await self._conn.commit()
            return True

        except Exception as e:
            print(f"Error updating task: {e}")
            return False

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        try:
            await self._conn.execute("""
                DELETE FROM tasks WHERE id = ?
            """, (task_id,))

            await self._conn.commit()
            return True

        except Exception as e:
            print(f"Error deleting task: {e}")
            return False

    async def get_tasks_by_status(
        self,
        status: TaskStatus,
        limit: int = 100
    ) -> List[Task]:
        """
        按状态获取任务

        Args:
            status: 任务状态
            limit: 最大数量

        Returns:
            任务列表
        """
        cursor = await self._conn.execute("""
            SELECT * FROM tasks
            WHERE status = ?
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
        """, (status.value, limit))

        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def get_tasks_by_agent(
        self,
        agent_id: str,
        limit: int = 100
    ) -> List[Task]:
        """
        获取Agent的任务

        Args:
            agent_id: Agent ID
            limit: 最大数量

        Returns:
            任务列表
        """
        cursor = await self._conn.execute("""
            SELECT * FROM tasks
            WHERE assigned_agent = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (agent_id, limit))

        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def get_pending_count(self) -> int:
        """
        获取待处理任务数量

        Returns:
            数量
        """
        cursor = await self._conn.execute("""
            SELECT COUNT(*) FROM tasks WHERE status = ?
        """, (TaskStatus.PENDING.value,))

        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_agent_pending_count(self, agent_id: str) -> int:
        """
        获取Agent的待处理任务数量

        Args:
            agent_id: Agent ID

        Returns:
            数量
        """
        cursor = await self._conn.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE assigned_agent = ? AND status = ?
        """, (agent_id, TaskStatus.RUNNING.value))

        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_all_tasks(self, limit: int = 100) -> List[Task]:
        """
        获取所有任务

        Args:
            limit: 最大数量

        Returns:
            任务列表
        """
        cursor = await self._conn.execute("""
            SELECT * FROM tasks
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    def _row_to_task(self, row: tuple) -> Task:
        """将数据库行转换为Task对象"""
        return Task(
            id=row[0],
            type=row[1],
            data=json.loads(row[2]),
            status=TaskStatus(row[3]),
            priority=TaskPriority(row[4]),
            assigned_agent=row[5],
            created_at=row[6],
            updated_at=row[7],
            started_at=row[8],
            completed_at=row[9],
            retry_count=row[10],
            max_retries=row[11],
            error=row[12],
            metadata=json.loads(row[13]) if row[13] else {},
        )
