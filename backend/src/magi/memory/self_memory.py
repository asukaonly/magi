"""
记忆存储 - 自我记忆（Self Memory）
Agent设定和用户偏好
"""
import aiosqlite
import json
from typing import Dict, Any, Optional
from pathlib import Path


class SelfMemory:
    """
    自我记忆 - Agent设定和用户偏好

    存储：
    - Agent静态设定（名称、角色、性格）
    - 用户偏好（交互方式、响应风格）
    - 用户习惯（作息时间、常用功能）
    """

    def __init__(self, db_path: str = "./data/memories/self_memory.db"):
        """
        初始化自我记忆

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self):
        """初始化数据库"""
        # 确保目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # 创建配置表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS self_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            await db.commit()

    async def get_agent_profile(self) -> Dict[str, Any]:
        """
        获取Agent设定

        Returns:
            Agent设定字典
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM self_memory WHERE key = ?",
                ("agent_profile",)
            )
            row = await cursor.fetchone()

            if row:
                return json.loads(row[0])
            else:
                # 返回默认配置
                return {
                    "name": "Magi",
                    "role": "AI Assistant",
                    "personality": "helpful, friendly",
                }

    async def update_agent_profile(self, profile: Dict[str, Any]):
        """
        更新Agent设定

        Args:
            profile: Agent设定
        """
        await self._set("agent_profile", profile)

    async def get_user_preferences(self) -> Dict[str, Any]:
        """
        获取用户偏好

        Returns:
            用户偏好字典
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM self_memory WHERE key = ?",
                ("user_preferences",)
            )
            row = await cursor.fetchone()

            if row:
                return json.loads(row[0])
            else:
                return {
                    "interaction_style": "friendly",
                    "response_length": "medium",
                    "language": "zh-CN",
                }

    async def update_user_preferences(self, updates: Dict[str, Any]):
        """
        更新用户偏好

        Args:
            updates: 要更新的偏好
        """
        current = await self.get_user_preferences()
        merged = {**current, **updates}
        await self._set("user_preferences", merged)

    async def get_user_habits(self) -> Dict[str, Any]:
        """
        获取用户习惯

        Returns:
            用户习惯字典
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM self_memory WHERE key = ?",
                ("user_habits",)
            )
            row = await cursor.fetchone()

            if row:
                return json.loads(row[0])
            else:
                return {}

    async def update_user_habits(self, habits: Dict[str, Any]):
        """
        更新用户习惯

        Args:
            habits: 用户习惯
        """
        await self._set("user_habits", habits)

    async def _set(self, key: str, value: Any):
        """
        设置键值

        Args:
            key: 键
            value: 值（会被JSON序列化）
        """
        import time
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO self_memory (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(value), time.time())
            )
            await db.commit()
