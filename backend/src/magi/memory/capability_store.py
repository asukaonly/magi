"""
记忆存储 - L5能力记忆（Capability Store）
自处理层的经验沉淀
"""
import aiosqlite
import json
import uuid
from typing import Optional, List
from pathlib import Path
import time


class CapabilityMemory:
    """能力记忆"""

    def __init__(
        self,
        trigger_pattern: dict,
        action: dict,
        success_rate: float = 1.0,
        usage_count: int = 1,
        created_at: float = None,
        last_used_at: float = None,
        source: str = "experience",
    ):
        self.trigger_pattern = trigger_pattern  # 触发模式
        self.action = action  # 处理动作
        self.success_rate = success_rate  # 成功率
        self.usage_count = usage_count  # 使用次数
        self.created_at = created_at or time.time()  # 首次学习时间
        self.last_used_at = last_used_at  # 最后使用时间
        self.source = source  # 来源（human/llm/experience）


class CapabilityStore:
    """
    L5能力记忆 - 自处理层经验沉淀

    特点：
    - SQLite存储结构化数据
    - ChromaDB存储向量（语义检索）
    - 支持能力查找和复用
    - 持续学习（动态更新成功率）
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/memories/capabilities.db",
        chromadb_path: str = "~/.magi/data/chromadb",
    ):
        """
        初始化能力存储

        Args:
            db_path: SQLite数据库路径
            chromadb_path: ChromaDB路径
        """
        self.db_path = db_path
        self.chromadb_path = chromadb_path

    @property
    def _expanded_db_path(self) -> str:
        """获取展开后的数据库路径（处理 ~）"""
        return str(Path(self.db_path).expanduser())

    @property
    def _expanded_chromadb_path(self) -> str:
        """获取展开后的ChromaDB路径（处理 ~）"""
        return str(Path(self.chromadb_path).expanduser())

    async def init(self):
        """初始化数据库"""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self._expanded_chromadb_path).mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 创建能力表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    id TEXT PRIMARY KEY,
                    trigger_pattern TEXT NOT NULL,
                    action TEXT NOT NULL,
                    success_rate REAL NOT NULL,
                    usage_count INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_used_at REAL,
                    source TEXT
                )
            """)
            await db.commit()

    async def save(self, capability: CapabilityMemory):
        """
        沉淀能力

        Args:
            capability: 能力记忆
        """
        capability_id = str(uuid.uuid4())

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("""
                INSERT INTO capabilities (
                    id, trigger_pattern, action, success_rate,
                    usage_count, created_at, last_used_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                capability_id,
                json.dumps(capability.trigger_pattern),
                json.dumps(capability.action),
                capability.success_rate,
                capability.usage_count,
                capability.created_at,
                capability.last_used_at,
                capability.source,
            ))
            await db.commit()

    async def find(self, perception_pattern: dict) -> Optional[CapabilityMemory]:
        """
        查找已有能力（语义匹配）

        Args:
            perception_pattern: 感知模式

        Returns:
            匹配的能力或None
        """
        # 简化版本：直接查询最高成功率的能力
        # 实际实现应该使用ChromaDB进行向量检索
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM capabilities
                WHERE success_rate >= 0.7
                ORDER BY success_rate DESC, usage_count DESC
                LIMIT 1
            """)
            row = await cursor.fetchone()

            if not row:
                return None

            return CapabilityMemory(
                trigger_pattern=json.loads(row[1]),
                action=json.loads(row[2]),
                success_rate=row[3],
                usage_count=row[4],
                created_at=row[5],
                last_used_at=row[6],
                source=row[7],
            )

    async def update_success_rate(
        self,
        capability_id: str,
        success: bool,
    ):
        """
        更新成功率（持续学习）

        Args:
            capability_id: 能力ID
            success: 是否成功
        """
        # 获取当前能力
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT success_rate, usage_count FROM capabilities WHERE id = ?",
                (capability_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return

            current_rate = row[0]
            usage_count = row[1] + 1

            # 指数移动平均
            alpha = 0.3
            new_rate = (1 - alpha) * current_rate + alpha * (1.0 if success else 0.0)

            # 更新
            await db.execute("""
                UPDATE capabilities
                SET success_rate = ?, usage_count = ?, last_used_at = ?
                WHERE id = ?
            """, (new_rate, usage_count, time.time(), capability_id))
            await db.commit()

    async def get_all_capabilities(self) -> List[CapabilityMemory]:
        """
        获取所有能力

        Returns:
            能力列表
        """
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT * FROM capabilities")
            rows = await cursor.fetchall()

            return [
                CapabilityMemory(
                    trigger_pattern=json.loads(row[1]),
                    action=json.loads(row[2]),
                    success_rate=row[3],
                    usage_count=row[4],
                    created_at=row[5],
                    last_used_at=row[6],
                    source=row[7],
                )
                for row in rows
            ]
