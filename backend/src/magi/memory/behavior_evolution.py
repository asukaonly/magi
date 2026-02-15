"""
行为偏好层演化 (L3) - Behavior Evolution Layer

行为偏好层记录AI在处理不同类型任务时的行为模式演化。
这些偏好通过与用户交互逐渐形成，并根据用户反馈动态调整。

演化规则：
1. 任务类别学习 - 统计不同任务类型的用户反馈
2. 模糊容忍度调整 - 根据用户确认频率调整
3. 信息密度调整 - 根据用户追问频率调整
"""
import aiosqlite
import json
import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum

from .models import TaskBehaviorProfile, AmbiguityTolerance

logger = logging.getLogger(__name__)


# ===== 数据模型 =====

class SatisfactionLevel(Enum):
    """用户满意度等级"""
    VERY_LOW = "very_low"
    LOW = "low"
    NEUTRAL = "neutral"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class TaskInteractionRecord:
    """任务交互记录"""
    task_id: str
    task_category: str
    timestamp: float
    # 用户行为指标
    clarification_count: int  # 用户追问次数
    confirmation_count: int   # 用户确认次数
    correction_count: int     # 用户纠正次数
    # 满意度反馈
    satisfaction: SatisfactionLevel
    # 任务特征
    task_complexity: float    # 0-1
    task_duration: float      # 秒
    # 是否被接受
    accepted: bool


@dataclass
class CategoryStatistics:
    """类别统计信息"""
    category: str
    total_tasks: int = 0
    accepted_tasks: int = 0
    avg_clarifications: float = 0.0
    avg_confirmations: float = 0.0
    avg_corrections: float = 0.0
    avg_satisfaction: float = 0.0
    avg_complexity: float = 0.0

    # 偏好指标
    cautious_score: float = 0.5    # 谨慎度（0-1）
    impatient_score: float = 0.5   # 急进度（0-1）
    dense_score: float = 0.5       # 信息密度偏好（0-1）


# ===== 演化引擎 =====

class BehaviorEvolutionEngine:
    """
    行为演化引擎

    根据用户交互记录，动态调整AI的行为偏好
    """

    def __init__(self, db_path: str = "~/.magi/data/memories/behavior_evolution.db"):
        """
        初始化行为演化引擎

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._cache: Dict[str, TaskBehaviorProfile] = {}
        self._stats_cache: Dict[str, CategoryStatistics] = {}

    @property
    def _expanded_db_path(self) -> str:
        """获取展开后的数据库路径（处理 ~）"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self):
        """初始化数据库"""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 任务交互记录表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS task_interactions (
                    task_id TEXT PRIMARY KEY,
                    task_category TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    clarification_count INTEGER NOT NULL,
                    confirmation_count INTEGER NOT NULL,
                    correction_count INTEGER NOT NULL,
                    satisfaction TEXT NOT NULL,
                    task_complexity REAL NOT NULL,
                    task_duration REAL NOT NULL,
                    accepted INTEGER NOT NULL,
                    data_json TEXT NOT NULL
                )
            """)

            # 类别统计表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS category_statistics (
                    category TEXT PRIMARY KEY,
                    total_tasks INTEGER NOT NULL,
                    accepted_tasks INTEGER NOT NULL,
                    avg_clarifications REAL NOT NULL,
                    avg_confirmations REAL NOT NULL,
                    avg_corrections REAL NOT NULL,
                    avg_satisfaction REAL NOT NULL,
                    avg_complexity REAL NOT NULL,
                    cautious_score REAL NOT NULL,
                    impatient_score REAL NOT NULL,
                    dense_score REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 行为偏好表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS behavior_profiles (
                    task_category TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_interactions_category
                ON task_interactions(task_category)
            """)

            await db.commit()

    # ===== 记录交互 =====

    async def record_task_outcome(
        self,
        task_id: str,
        task_category: str,
        user_satisfaction: SatisfactionLevel = SatisfactionLevel.NEUTRAL,
        clarification_count: int = 0,
        confirmation_count: int = 0,
        correction_count: int = 0,
        task_complexity: float = 0.5,
        task_duration: float = 0.0,
        accepted: bool = True,
    ) -> None:
        """
        记录任务交互结果

        Args:
            task_id: 任务ID
            task_category: 任务类别
            user_satisfaction: 用户满意度
            clarification_count: 用户追问次数
            confirmation_count: 用户确认次数
            correction_count: 用户纠正次数
            task_complexity: 任务复杂度（0-1）
            task_duration: 任务持续时间（秒）
            accepted: 是否被接受
        """
        if isinstance(user_satisfaction, str):
            try:
                user_satisfaction = SatisfactionLevel(user_satisfaction)
            except ValueError:
                logger.warning(
                    f"Unknown satisfaction level '{user_satisfaction}', fallback to neutral"
                )
                user_satisfaction = SatisfactionLevel.NEUTRAL

        record = TaskInteractionRecord(
            task_id=task_id,
            task_category=task_category,
            timestamp=time.time(),
            clarification_count=clarification_count,
            confirmation_count=confirmation_count,
            correction_count=correction_count,
            satisfaction=user_satisfaction,
            task_complexity=task_complexity,
            task_duration=task_duration,
            accepted=accepted,
        )
        record_data = asdict(record)
        # JSON cannot serialize Enum directly.
        record_data["satisfaction"] = record.satisfaction.value

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO task_interactions
                   (task_id, task_category, timestamp, clarification_count,
                    confirmation_count, correction_count, satisfaction,
                    task_complexity, task_duration, accepted, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    task_category,
                    record.timestamp,
                    clarification_count,
                    confirmation_count,
                    correction_count,
                    user_satisfaction.value,
                    task_complexity,
                    task_duration,
                    1 if accepted else 0,
                    json.dumps(record_data),
                )
            )
            await db.commit()

        # 清除缓存
        if task_category in self._cache:
            del self._cache[task_category]
        if task_category in self._stats_cache:
            del self._stats_cache[task_category]

        # 更新统计和行为偏好
        await self._update_category_statistics(task_category)

        logger.debug(
            f"Recorded task outcome: {task_id} in {task_category}, "
            f"satisfaction={user_satisfaction.value}, accepted={accepted}"
        )

    # ===== 获取行为偏好 =====

    async def get_behavior_profile(self, task_category: str) -> TaskBehaviorProfile:
        """
        获取任务类别的行为偏好

        Args:
            task_category: 任务类别

        Returns:
            TaskBehaviorProfile对象
        """
        # 检查缓存
        if task_category in self._cache:
            return self._cache[task_category]

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT profile_json FROM behavior_profiles WHERE task_category = ?",
                (task_category,)
            )
            row = await cursor.fetchone()

            if row:
                data = json.loads(row[0])
                if "ambiguity_tolerance" in data:
                    data["ambiguity_tolerance"] = AmbiguityTolerance(data["ambiguity_tolerance"])
                profile = TaskBehaviorProfile(**data)
                self._cache[task_category] = profile
                return profile

        # 如果没有保存的偏好，根据统计生成
        stats = await self.get_category_statistics(task_category)
        profile = self._infer_profile_from_stats(stats)

        # 保存生成的偏好
        await self._save_behavior_profile(task_category, profile)

        self._cache[task_category] = profile
        return profile

    # ===== 统计信息 =====

    async def get_category_statistics(self, task_category: str) -> CategoryStatistics:
        """
        获取类别统计信息

        Args:
            task_category: 任务类别

        Returns:
            CategoryStatistics对象
        """
        # 检查缓存
        if task_category in self._stats_cache:
            return self._stats_cache[task_category]

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM category_statistics WHERE category = ?",
                (task_category,)
            )
            row = await cursor.fetchone()

            if row:
                stats = CategoryStatistics(
                    category=row[0],
                    total_tasks=row[1],
                    accepted_tasks=row[2],
                    avg_clarifications=row[3],
                    avg_confirmations=row[4],
                    avg_corrections=row[5],
                    avg_satisfaction=row[6],
                    avg_complexity=row[7],
                    cautious_score=row[8],
                    impatient_score=row[9],
                    dense_score=row[10],
                )
                self._stats_cache[task_category] = stats
                return stats

        # 如果没有统计，从交互记录计算
        await self._update_category_statistics(task_category)
        return await self.get_category_statistics(task_category)

    async def get_all_categories(self) -> List[str]:
        """获取所有任务类别"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT task_category FROM task_interactions ORDER BY task_category"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    # ===== 内部方法 =====

    async def _update_category_statistics(self, task_category: str) -> None:
        """更新类别统计信息"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(accepted) as accepted,
                    AVG(clarification_count) as avg_clar,
                    AVG(confirmation_count) as avg_conf,
                    AVG(correction_count) as avg_corr,
                    AVG(task_complexity) as avg_complex
                   FROM task_interactions
                   WHERE task_category = ?""",
                (task_category,)
            )
            row = await cursor.fetchone()

            if not row or row[0] == 0:
                # 没有数据，创建默认统计
                stats = CategoryStatistics(category=task_category)
            else:
                # 计算平均满意度
                satisfaction_values = {"very_low": 0.0, "low": 0.25, "neutral": 0.5, "high": 0.75, "very_high": 1.0}

                cursor = await db.execute(
                    """SELECT satisfaction, COUNT(*) FROM task_interactions
                       WHERE task_category = ? GROUP BY satisfaction""",
                    (task_category,)
                )
                sat_rows = await cursor.fetchall()

                weighted_sum = 0.0
                total_count = 0
                for sat_val, count in sat_rows:
                    weighted_sum += satisfaction_values.get(sat_val, 0.5) * count
                    total_count += count

                avg_satisfaction = weighted_sum / total_count if total_count > 0 else 0.5

                # 计算偏好指标
                avg_confirmations = row[3] or 0
                avg_clarifications = row[2] or 0
                avg_corrections = row[4] or 0

                # 谨慎度：用户确认越多，AI应该越谨慎
                cautious_score = min(1.0, 0.3 + avg_confirmations * 0.2)

                # 急进度：用户追问越少，越可以急躁
                impatient_score = max(0.0, 1.0 - avg_clarifications * 0.15)

                # 信息密度：用户纠正越多，说明信息不够详细
                dense_score = min(1.0, 0.3 + avg_corrections * 0.3)

                stats = CategoryStatistics(
                    category=task_category,
                    total_tasks=row[0],
                    accepted_tasks=row[1] or 0,
                    avg_clarifications=row[2] or 0.0,
                    avg_confirmations=row[3] or 0.0,
                    avg_corrections=row[4] or 0.0,
                    avg_satisfaction=avg_satisfaction,
                    avg_complexity=row[5] or 0.5,
                    cautious_score=cautious_score,
                    impatient_score=impatient_score,
                    dense_score=dense_score,
                )

            # 保存统计
            await db.execute(
                """INSERT OR REPLACE INTO category_statistics
                   (category, total_tasks, accepted_tasks, avg_clarifications,
                    avg_confirmations, avg_corrections, avg_satisfaction,
                    avg_complexity, cautious_score, impatient_score, dense_score,
                    updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_category,
                    stats.total_tasks,
                    stats.accepted_tasks,
                    stats.avg_clarifications,
                    stats.avg_confirmations,
                    stats.avg_corrections,
                    stats.avg_satisfaction,
                    stats.avg_complexity,
                    stats.cautious_score,
                    stats.impatient_score,
                    stats.dense_score,
                    time.time(),
                )
            )
            await db.commit()

            # 更新缓存
            self._stats_cache[task_category] = stats

    def _infer_profile_from_stats(self, stats: CategoryStatistics) -> TaskBehaviorProfile:
        """
        从统计信息推断行为偏好

        Args:
            stats: 类别统计信息

        Returns:
            TaskBehaviorProfile对象
        """
        # 根据统计推断模糊容忍度
        if stats.cautious_score > 0.7:
            ambiguity_tolerance = AmbiguityTolerance.CAUTIOUS
        elif stats.impatient_score > 0.7:
            ambiguity_tolerance = AmbiguityTolerance.IMPATIENT
        else:
            ambiguity_tolerance = AmbiguityTolerance.ADAPTIVE

        # 根据统计推断信息密度
        if stats.dense_score > 0.7:
            information_density = "dense"
        elif stats.dense_score < 0.3:
            information_density = "sparse"
        else:
            information_density = "medium"

        # 根据统计推断主动性
        if stats.avg_corrections > 1:
            proactivity = "proactive"  # 用户经常纠正，需要更主动
        elif stats.avg_confirmations > 2:
            proactivity = "passive"  # 用户经常确认，可以更保守
        else:
            proactivity = "reactive"

        # 根据统计推断容错度
        error_tolerance = 1.0 - (stats.avg_corrections / 5.0)
        error_tolerance = max(0.0, min(1.0, error_tolerance))

        return TaskBehaviorProfile(
            task_category=stats.category,
            information_density=information_density,
            ambiguity_tolerance=ambiguity_tolerance,
            response_prefers=[],
            response_avoids=[],
            error_tolerance=error_tolerance,
            proactivity=proactivity,
        )

    async def _save_behavior_profile(self, task_category: str, profile: TaskBehaviorProfile) -> None:
        """保存行为偏好"""
        # 转换枚举为字符串
        data = asdict(profile)
        if "ambiguity_tolerance" in data:
            data["ambiguity_tolerance"] = data["ambiguity_tolerance"].value

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO behavior_profiles
                   (task_category, profile_json, updated_at)
                   VALUES (?, ?, ?)""",
                (task_category, json.dumps(data), time.time())
            )
            await db.commit()

    # ===== 重置和导出 =====

    async def reset_category(self, task_category: str) -> None:
        """重置类别的行为演化"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("DELETE FROM task_interactions WHERE task_category = ?", (task_category,))
            await db.execute("DELETE FROM category_statistics WHERE category = ?", (task_category,))
            await db.execute("DELETE FROM behavior_profiles WHERE task_category = ?", (task_category,))
            await db.commit()

        # 清除缓存
        if task_category in self._cache:
            del self._cache[task_category]
        if task_category in self._stats_cache:
            del self._stats_cache[task_category]

        logger.info(f"Reset behavior evolution for category: {task_category}")

    async def export_data(self, task_category: str = None) -> Dict[str, Any]:
        """
        导出演化数据

        Args:
            task_category: 指定类别，None表示导出全部

        Returns:
            导出的数据字典
        """
        result = {}

        if task_category:
            categories = [task_category]
        else:
            categories = await self.get_all_categories()

        for cat in categories:
            stats = await self.get_category_statistics(cat)
            profile = await self.get_behavior_profile(cat)

            result[cat] = {
                "statistics": asdict(stats),
                "profile": asdict(profile),
            }

        return result
