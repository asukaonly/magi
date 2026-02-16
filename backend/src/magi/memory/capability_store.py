"""
Memory Storage - L5capabilitymemory（Capability Store）
自process层的experience沉淀
"""
import aiosqlite
import json
import uuid
from typing import Optional, List
from pathlib import path
import time


class CapabilityMemory:
    """capabilitymemory"""

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
        self.trigger_pattern = trigger_pattern  # 触发pattern
        self.action = action  # processaction
        self.success_rate = success_rate  # success率
        self.usage_count = usage_count  # 使用count
        self.created_at = created_at or time.time()  # 首次learning时间
        self.last_used_at = last_used_at  # 最后使用时间
        self.source = source  # source（human/llm/experience）


class CapabilityStore:
    """
    L5capabilitymemory - 自process层experience沉淀

    特点：
    - SQLitestoragestructure化data
    - ChromaDBstoragevector（语义检索）
    - supportcapability查找and复用
    - 持续learning（dynamicupdatesuccess率）
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/memories/capabilities.db",
        chromadb_path: str = "~/.magi/data/chromadb",
    ):
        """
        initializecapabilitystorage

        Args:
            db_path: SQLitedatabasepath
            chromadb_path: ChromaDBpath
        """
        self.db_path = db_path
        self.chromadb_path = chromadb_path

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        return str(path(self.db_path).expanduser())

    @property
    def _expanded_chromadb_path(self) -> str:
        """get展开后的ChromaDBpath（process ~）"""
        return str(path(self.chromadb_path).expanduser())

    async def init(self):
        """initializedatabase"""
        path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)
        path(self._expanded_chromadb_path).mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # createcapabilitytable
            await db.execute("""
                create table IF NOT EXISTS capabilities (
                    id TEXT primary key,
                    trigger_pattern TEXT NOT NULL,
                    action TEXT NOT NULL,
                    success_rate real NOT NULL,
                    usage_count intEGER NOT NULL,
                    created_at real NOT NULL,
                    last_used_at real,
                    source TEXT
                )
            """)
            await db.commit()

    async def save(self, capability: CapabilityMemory):
        """
        沉淀capability

        Args:
            capability: capabilitymemory
        """
        capability_id = str(uuid.uuid4())

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("""
                INSERT intO capabilities (
                    id, trigger_pattern, action, success_rate,
                    usage_count, created_at, last_used_at, source
                ) valueS (?, ?, ?, ?, ?, ?, ?, ?)
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
        查找已有capability（语义匹配）

        Args:
            perception_pattern: Perceptionpattern

        Returns:
            匹配的capability或None
        """
        # 简化version：直接query最高success率的capability
        # 实际Implementation应该使用ChromaDB进rowvector检索
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                SELECT * FROM capabilities
                WHERE success_rate >= 0.7
                order BY success_rate DESC, usage_count DESC
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
        updatesuccess率（持续learning）

        Args:
            capability_id: capabilityid
            success: is notsuccess
        """
        # getcurrentcapability
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

            # 指数move平均
            alpha = 0.3
            new_rate = (1 - alpha) * current_rate + alpha * (1.0 if success else 0.0)

            # update
            await db.execute("""
                update capabilities
                set success_rate = ?, usage_count = ?, last_used_at = ?
                WHERE id = ?
            """, (new_rate, usage_count, time.time(), capability_id))
            await db.commit()

    async def get_all_capabilities(self) -> List[CapabilityMemory]:
        """
        getallcapability

        Returns:
            capabilitylist
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
