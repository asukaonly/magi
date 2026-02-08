"""
记忆存储 - 他人记忆（Other Memory）
用户画像和其他人的记忆
"""
import aiosqlite
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import time


class UserProfile:
    """用户画像"""

    def __init__(
        self,
        user_id: str,
        interests: List[str] = None,
        habits: List[str] = None,
        personality: List[str] = None,
        relationships: Dict[str, str] = None,
        communication_style: str = "friendly",
        last_updated: float = None,
    ):
        self.user_id = user_id
        self.interests = interests or []
        self.habits = habits or []
        self.personality = personality or []
        self.relationships = relationships or {}
        self.communication_style = communication_style
        self.last_updated = last_updated or time.time()


class OtherMemory:
    """
    他人记忆 - 用户画像和其他人

    存储：
    - 用户画像（兴趣、习惯、性格、关系等）
    - 自适应更新（退避算法）
    """

    def __init__(self, db_path: str = "./data/memories/other_memory.db"):
        """
        初始化他人记忆

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.updater = AdaptiveProfileUpdater()

    async def init(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # 创建用户画像表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    interests TEXT,
                    habits TEXT,
                    personality TEXT,
                    relationships TEXT,
                    communication_style TEXT,
                    last_updated REAL
                )
            """)
            await db.commit()

    async def update_profile(
        self,
        user_id: str,
        new_events: List[Any] = None,
    ):
        """
        更新用户画像（自适应频率）

        Args:
            user_id: 用户ID
            new_events: 新事件列表（用于判断是否需要更新）
        """
        if new_events is not None:
            if self.updater.should_update(len(new_events)):
                await self.updater.update_profile(user_id, self.db_path)
        else:
            # 强制更新
            await self.updater.update_profile(user_id, self.db_path)

    async def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """
        获取用户画像

        Args:
            user_id: 用户ID

        Returns:
            用户画像或None
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return UserProfile(
                user_id=row[0],
                interests=json.loads(row[1]) if row[1] else [],
                habits=json.loads(row[2]) if row[2] else [],
                personality=json.loads(row[3]) if row[3] else [],
                relationships=json.loads(row[4]) if row[4] else {},
                communication_style=row[5] or "friendly",
                last_updated=row[6],
            )

    async def create_profile(
        self,
        user_id: str,
        profile_data: Dict[str, Any],
    ):
        """
        创建新用户画像

        Args:
            user_id: 用户ID
            profile_data: 画像数据
        """
        import time
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_profiles (
                    user_id, interests, habits, personality,
                    relationships, communication_style, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                json.dumps(profile_data.get("interests", [])),
                json.dumps(profile_data.get("habits", [])),
                json.dumps(profile_data.get("personality", [])),
                json.dumps(profile_data.get("relationships", {})),
                profile_data.get("communication_style", "friendly"),
                time.time(),
            ))
            await db.commit()


class AdaptiveProfileUpdater:
    """
    自适应更新器 - 类似退避算法

    更新频率：
    - 前期（事件<10）：每3个事件更新一次
    - 中期（事件<100）：每天更新
    - 后期（事件>=100）：每周更新
    """

    def __init__(self):
        self.event_count = 0
        self.last_update_at = 0

    def should_update(self, new_events: int) -> bool:
        """
        判断是否需要更新

        Args:
            new_events: 新增事件数

        Returns:
            是否需要更新
        """
        self.event_count += new_events
        current_time = time.time()

        # 前期（事件<10）：每3个事件更新一次
        if self.event_count < 10:
            return self.event_count >= 3

        # 中期（事件<100）：每天更新
        elif self.event_count < 100:
            days = (current_time - self.last_update_at) / 86400
            return days >= 1

        # 后期（事件>=100）：每周更新
        else:
            weeks = (current_time - self.last_update_at) / (7 * 86400)
            return weeks >= 1

    async def update_profile(self, user_id: str, db_path: str):
        """
        执行更新（这里应该是调用LLM分析事件并更新画像）

        Args:
            user_id: 用户ID
            db_path: 数据库路径
        """
        # TODO: 实际实现应该调用LLM分析事件并更新画像
        # 这里暂时只记录更新时间
        self.last_update_at = time.time()
