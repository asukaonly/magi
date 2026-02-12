"""
成长记忆层 (L5) - Growth Memory Layer

成长记忆层记录AI的长期演化轨迹和重要时刻。
这是AI的"成长日记"，记录能力发展、关系变化和人格演化。

演化规则：
1. 里程碑记录 - 重要事件（首次使用能力、连续工作X小时）
2. 关系深度 - 根据交互频率和深度计算
3. 人格演化 - 重大价值观变化（罕见，需高置信度）
"""
import aiosqlite
import json
import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ===== 枚举定义 =====

class MilestoneType(Enum):
    """里程碑类型"""
    FIRST_USE = "first_use"              # 首次使用某能力
    STREAK = "streak"                    # 连续工作/交互
    MASTERY = "mastery"                  # 掌握某技能
    RELATIONSHIP = "relationship"        # 关系里程碑
    ACHIEVEMENT = "achievement"          # 成就
    PERSONALITY_CHANGE = "personality"   # 人格变化
    SPECIAL = "special"                  # 特殊事件


class InteractionType(Enum):
    """交互类型"""
    CHAT = "chat"                        # 聊天
    TASK = "task"                        # 任务
    CODE = "code"                        # 代码
    ANALYSIS = "analysis"                # 分析
    CREATIVE = "creative"                # 创意
    LEARNING = "learning"                # 学习


# ===== 数据模型 =====

@dataclass
class Milestone:
    """成长里程碑"""
    id: str
    type: MilestoneType
    title: str
    description: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipProfile:
    """关系档案"""
    user_id: str
    depth: float                         # 关系深度 0-1
    first_interaction: float             # 首次交互时间
    last_interaction: float              # 最近交互时间
    total_interactions: int              # 交互次数
    interaction_types: Dict[str, int]    # 各类型交互次数
    sentiment_score: float               # 情感分数 -1到1
    trust_level: float                   # 信任度 0-1
    notes: List[str] = field(default_factory=list)  # 备注


@dataclass
class PersonalityEvolution:
    """人格演化记录"""
    timestamp: float
    aspect: str                          # 变化的方面
    previous_value: Any
    new_value: Any
    confidence: float                    # 置信度 0-1
    reason: str                          # 变化原因


# ===== 成长记忆引擎 =====

class GrowthMemoryEngine:
    """
    成长记忆引擎

    记录和管理AI的长期成长轨迹
    """

    def __init__(self, db_path: str = "~/.magi/data/memories/growth_memory.db"):
        """
        初始化成长记忆引擎

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._relationship_cache: Dict[str, RelationshipProfile] = {}
        self._milestone_cache: Optional[List[Milestone]] = None

    @property
    def _expanded_db_path(self) -> str:
        """获取展开后的数据库路径（处理 ~）"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self):
        """初始化数据库"""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 里程碑表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS milestones (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)

            # 关系档案表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    user_id TEXT PRIMARY KEY,
                    depth REAL NOT NULL,
                    first_interaction REAL NOT NULL,
                    last_interaction REAL NOT NULL,
                    total_interactions INTEGER NOT NULL,
                    interaction_types TEXT NOT NULL,
                    sentiment_score REAL NOT NULL,
                    trust_level REAL NOT NULL,
                    notes TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 人格演化表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS personality_evolution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    aspect TEXT NOT NULL,
                    previous_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL
                )
            """)

            # 统计表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS growth_statistics (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_milestones_timestamp
                ON milestones(timestamp DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_updated
                ON relationships(updated_at DESC)
            """)

            await db.commit()

    # ===== 里程碑管理 =====

    async def record_milestone(
        self,
        milestone_type: MilestoneType,
        title: str,
        description: str,
        metadata: Dict[str, Any] = None
    ) -> Milestone:
        """
        记录成长里程碑

        Args:
            milestone_type: 里程碑类型
            title: 标题
            description: 描述
            metadata: 额外元数据

        Returns:
            创建的里程碑对象
        """
        milestone_id = f"milestone_{int(time.time() * 1000)}_{hash(title) % 10000:04d}"

        milestone = Milestone(
            id=milestone_id,
            type=milestone_type,
            title=title,
            description=description,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT INTO milestones (id, type, title, description, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    milestone_id,
                    milestone_type.value,
                    title,
                    description,
                    milestone.timestamp,
                    json.dumps(metadata or {}),
                )
            )
            await db.commit()

        # 清除缓存
        self._milestone_cache = None

        # 更新统计
        await self._increment_stat("total_milestones")

        logger.info(f"Recorded milestone: {title} ({milestone_type.value})")

        return milestone

    async def get_milestones(
        self,
        milestone_type: MilestoneType = None,
        limit: int = 100
    ) -> List[Milestone]:
        """
        获取里程碑列表

        Args:
            milestone_type: 筛选类型，None表示全部
            limit: 最大数量

        Returns:
            里程碑列表
        """
        # 使用缓存
        if self._milestone_cache is not None and milestone_type is None:
            return self._milestone_cache[:limit]

        async with aiosqlite.connect(self._expanded_db_path) as db:
            if milestone_type:
                cursor = await db.execute(
                    """SELECT id, type, title, description, timestamp, metadata
                       FROM milestones WHERE type = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (milestone_type.value, limit)
                )
            else:
                cursor = await db.execute(
                    """SELECT id, type, title, description, timestamp, metadata
                       FROM milestones
                       ORDER BY timestamp DESC LIMIT ?""",
                    (limit,)
                )

            rows = await cursor.fetchall()

            milestones = []
            for row in rows:
                milestones.append(Milestone(
                    id=row[0],
                    type=MilestoneType(row[1]),
                    title=row[2],
                    description=row[3],
                    timestamp=row[4],
                    metadata=json.loads(row[5]) if row[5] else {},
                ))

            if milestone_type is None:
                self._milestone_cache = milestones

            return milestones

    # ===== 交互记录 =====

    async def record_interaction(
        self,
        user_id: str,
        interaction_type: InteractionType,
        outcome: str = "neutral",
        sentiment: float = 0.0,
        notes: str = ""
    ) -> RelationshipProfile:
        """
        记录与用户的交互

        Args:
            user_id: 用户ID
            interaction_type: 交互类型
            outcome: 结果（success/failure/neutral）
            sentiment: 情感分数（-1到1）
            notes: 备注

        Returns:
            更新后的关系档案
        """
        now = time.time()

        # 获取现有关系或创建新的
        profile = await self.get_relationship(user_id)

        if profile is None:
            profile = RelationshipProfile(
                user_id=user_id,
                depth=0.0,
                first_interaction=now,
                last_interaction=now,
                total_interactions=0,
                interaction_types={},
                sentiment_score=0.0,
                trust_level=0.5,
                notes=[],
            )

        # 更新统计
        profile.total_interactions += 1
        profile.last_interaction = now

        # 更新交互类型统计
        type_key = interaction_type.value
        profile.interaction_types[type_key] = profile.interaction_types.get(type_key, 0) + 1

        # 更新情感分数（指数移动平均）
        alpha = 0.2  # 平滑因子
        profile.sentiment_score = (1 - alpha) * profile.sentiment_score + alpha * sentiment

        # 更新信任度
        if outcome == "success":
            profile.trust_level = min(1.0, profile.trust_level + 0.02)
        elif outcome == "failure":
            profile.trust_level = max(0.0, profile.trust_level - 0.01)

        # 计算关系深度
        profile.depth = await self._calculate_relationship_depth(profile)

        # 添加备注
        if notes:
            profile.notes.append(f"[{datetime.fromtimestamp(now).strftime('%Y-%m-%d')}] {notes}")
            # 只保留最近20条备注
            profile.notes = profile.notes[-20:]

        # 保存
        await self._save_relationship(profile)

        # 更新全局统计
        await self._increment_stat("total_interactions")

        # 检查关系里程碑
        await self._check_relationship_milestones(profile)

        logger.debug(
            f"Recorded interaction: user={user_id}, type={interaction_type.value}, "
            f"depth={profile.depth:.2f}, trust={profile.trust_level:.2f}"
        )

        return profile

    async def get_relationship(self, user_id: str) -> Optional[RelationshipProfile]:
        """
        获取与用户的关系档案

        Args:
            user_id: 用户ID

        Returns:
            关系档案，不存在则返回None
        """
        # 检查缓存
        if user_id in self._relationship_cache:
            return self._relationship_cache[user_id]

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT user_id, depth, first_interaction, last_interaction,
                          total_interactions, interaction_types, sentiment_score,
                          trust_level, notes
                   FROM relationships WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()

            if row:
                profile = RelationshipProfile(
                    user_id=row[0],
                    depth=row[1],
                    first_interaction=row[2],
                    last_interaction=row[3],
                    total_interactions=row[4],
                    interaction_types=json.loads(row[5]),
                    sentiment_score=row[6],
                    trust_level=row[7],
                    notes=json.loads(row[8]),
                )
                self._relationship_cache[user_id] = profile
                return profile

        return None

    # ===== 关系深度计算 =====

    async def _calculate_relationship_depth(self, profile: RelationshipProfile) -> float:
        """
        计算关系深度

        考虑因素：
        - 交互次数（频率）
        - 交互时长（从首次到现在）
        - 交互多样性（类型数量）
        - 情感分数
        - 信任度

        Returns:
            关系深度 0-1
        """
        now = time.time()
        duration_days = (now - profile.first_interaction) / (24 * 3600)

        # 基础分数（交互次数）
        frequency_score = min(1.0, profile.total_interactions / 100)

        # 时长分数
        duration_score = min(1.0, duration_days / 365)

        # 多样性分数
        type_count = len([t for t, c in profile.interaction_types.items() if c > 0])
        diversity_score = min(1.0, type_count / len(InteractionType))

        # 情感分数（归一化到0-1）
        sentiment_score = (profile.sentiment_score + 1) / 2

        # 信任度
        trust_score = profile.trust_level

        # 加权平均
        depth = (
            0.3 * frequency_score +
            0.2 * duration_score +
            0.15 * diversity_score +
            0.15 * sentiment_score +
            0.2 * trust_score
        )

        return min(1.0, max(0.0, depth))

    async def update_relationship_depth(self, user_id: str, delta: float) -> None:
        """
        直接调整关系深度

        Args:
            user_id: 用户ID
            delta: 调整量（正负）
        """
        profile = await self.get_relationship(user_id)
        if profile:
            profile.depth = max(0.0, min(1.0, profile.depth + delta))
            await self._save_relationship(profile)

    # ===== 人格演化 =====

    async def check_personality_evolution(
        self,
        aspect: str,
        previous_value: Any,
        new_value: Any,
        confidence: float,
        reason: str
    ) -> bool:
        """
        检查并记录人格演化

        只有在高置信度时才记录人格变化

        Args:
            aspect: 变化的方面
            previous_value: 之前的值
            new_value: 新值
            confidence: 置信度（0-1）
            reason: 变化原因

        Returns:
            是否记录了演化
        """
        # 置信度阈值
        if confidence < 0.8:
            return False

        # 检查是否真的有变化
        if previous_value == new_value:
            return False

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT INTO personality_evolution
                   (timestamp, aspect, previous_value, new_value, confidence, reason)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (time.time(), aspect, str(previous_value), str(new_value), confidence, reason)
            )
            await db.commit()

        logger.info(
            f"Personality evolution recorded: {aspect} from {previous_value} to {new_value} "
            f"(confidence: {confidence:.2f})"
        )

        # 记录里程碑
        await self.record_milestone(
            milestone_type=MilestoneType.PERSONALITY_CHANGE,
            title=f"Personality Shift: {aspect}",
            description=f"{aspect} changed from {previous_value} to {new_value}",
            metadata={"confidence": confidence, "reason": reason}
        )

        return True

    # ===== 里程碑检测 =====

    async def _check_relationship_milestones(self, profile: RelationshipProfile) -> None:
        """检查关系里程碑"""
        user_id = profile.user_id

        # 首次交互
        if profile.total_interactions == 1:
            await self.record_milestone(
                milestone_type=MilestoneType.RELATIONSHIP,
                title=f"First Meeting: {user_id}",
                description=f"First interaction with user {user_id}",
                metadata={"user_id": user_id}
            )

        # 关系深化
        depth_milestones = {
            0.3: "Acquaintance",
            0.5: "Friend",
            0.7: "Close Friend",
            0.9: "Best Friend",
        }

        for threshold, title in depth_milestones.items():
            if profile.depth >= threshold:
                # 检查是否已经记录过
                existing = await self.get_milestones(
                    milestone_type=MilestoneType.RELATIONSHIP,
                    limit=100
                )
                milestone_title = f"{title}: {user_id}"

                if not any(m.title == milestone_title for m in existing):
                    await self.record_milestone(
                        milestone_type=MilestoneType.RELATIONSHIP,
                        title=milestone_title,
                        description=f"Relationship with {user_id} reached {title} level (depth: {profile.depth:.2f})",
                        metadata={"user_id": user_id, "depth": profile.depth}
                    )

        # 交互次数里程碑
        interaction_milestones = [10, 50, 100, 500, 1000]
        for count in interaction_milestones:
            if profile.total_interactions == count:
                await self.record_milestone(
                    milestone_type=MilestoneType.RELATIONSHIP,
                    title=f"{count} Interactions: {user_id}",
                    description=f"Reached {count} interactions with {user_id}",
                    metadata={"user_id": user_id, "count": count}
                )

    # ===== 统计信息 =====

    async def get_growth_summary(self) -> Dict[str, Any]:
        """获取成长摘要"""
        stats = await self._get_all_stats()

        milestones = await self.get_milestones(limit=1000)

        # 获取所有关系
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM relationships")
            total_relationships = (await cursor.fetchone())[0]

        return {
            "total_milestones": len(milestones),
            "total_interactions": int(stats.get("total_interactions", 0)),
            "total_relationships": total_relationships,
            "first_interaction": float(stats.get("first_interaction", time.time())),
            "active_days": int(stats.get("active_days", 0)),
            "learned_capabilities": stats.get("learned_capabilities", []),
        }

    async def _get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT key, value FROM growth_statistics")
            rows = await cursor.fetchall()

            stats = {}
            for key, value in rows:
                try:
                    stats[key] = json.loads(value)
                except:
                    stats[key] = value

            return stats

    async def _increment_stat(self, key: str, value: Any = 1) -> None:
        """增加统计值"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT value FROM growth_statistics WHERE key = ?", (key,))
            row = await cursor.fetchone()

            if row:
                try:
                    current = json.loads(row[0])
                except:
                    current = row[0]

                if isinstance(current, int):
                    current += value
                elif isinstance(current, list):
                    if isinstance(value, list):
                        current = list(set(current + value))
                    else:
                        current.append(value)
            else:
                current = value

            await db.execute(
                """INSERT OR REPLACE INTO growth_statistics (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(current), time.time())
            )
            await db.commit()

    async def _save_relationship(self, profile: RelationshipProfile) -> None:
        """保存关系档案"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO relationships
                   (user_id, depth, first_interaction, last_interaction,
                    total_interactions, interaction_types, sentiment_score,
                    trust_level, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile.user_id,
                    profile.depth,
                    profile.first_interaction,
                    profile.last_interaction,
                    profile.total_interactions,
                    json.dumps(profile.interaction_types),
                    profile.sentiment_score,
                    profile.trust_level,
                    json.dumps(profile.notes),
                    time.time(),
                )
            )
            await db.commit()

        # 更新缓存
        self._relationship_cache[profile.user_id] = profile

    # ===== 导出和重置 =====

    async def export_relationships(self) -> List[Dict[str, Any]]:
        """导出所有关系"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT user_id, depth, first_interaction, last_interaction,
                          total_interactions, interaction_types, sentiment_score,
                          trust_level, notes
                   FROM relationships
                   ORDER BY depth DESC"""
            )
            rows = await cursor.fetchall()

            relationships = []
            for row in rows:
                relationships.append({
                    "user_id": row[0],
                    "depth": row[1],
                    "first_interaction": row[2],
                    "last_interaction": row[3],
                    "total_interactions": row[4],
                    "interaction_types": json.loads(row[5]),
                    "sentiment_score": row[6],
                    "trust_level": row[7],
                    "notes": json.loads(row[8]),
                })

            return relationships

    async def reset_user(self, user_id: str) -> None:
        """重置用户关系"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("DELETE FROM relationships WHERE user_id = ?", (user_id,))
            await db.commit()

        if user_id in self._relationship_cache:
            del self._relationship_cache[user_id]

        logger.info(f"Reset relationship for user: {user_id}")
