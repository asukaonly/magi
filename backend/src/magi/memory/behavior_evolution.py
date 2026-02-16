"""
Behavior Evolution Layer (L3) - Behavior Evolution Layer

Records AI behavior pattern evolution when processing different task types。
These preferences are formed through user interaction and dynamically adjusted based on user feedback。

evolutionrule：
1. 任务Class别learning - statistics不同任务type的user反馈
2. 模糊容忍度调整 - 根据user确认frequency调整
3. info密度调整 - 根据user追问frequency调整
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


# ===== data Models =====

class Satisfactionlevel(Enum):
    """usersatisfactiongrade"""
    VERY_LOW = "very_low"
    LOW = "low"
    NEUTRAL = "neutral"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class TaskInteractionRecord:
    """任务交互record"""
    task_id: str
    task_category: str
    timestamp: float
    # userrow为metric
    clarification_count: int  # user追问count
    confirmation_count: int   # user确认count
    correction_count: int     # user纠正count
    # satisfaction反馈
    satisfaction: Satisfactionlevel
    # 任务特征
    task_complexity: float    # 0-1
    task_duration: float      # seconds
    # is not被接受
    accepted: bool


@dataclass
class CategoryStatistics:
    """Class别statisticsinfo"""
    category: str
    total_tasks: int = 0
    accepted_tasks: int = 0
    avg_clarifications: float = 0.0
    avg_confirmations: float = 0.0
    avg_corrections: float = 0.0
    avg_satisfaction: float = 0.0
    avg_complexity: float = 0.0

    # preferencemetric
    cautious_score: float = 0.5    # 谨慎度（0-1）
    impatient_score: float = 0.5   # 急进度（0-1）
    dense_score: float = 0.5       # info密度preference（0-1）


# ===== evolution引擎 =====

class BehaviorEvolutionEngine:
    """
    row为evolution引擎

    根据user交互record，dynamic调整AI的row为preference
    """

    def __init__(self, db_path: str = "~/.magi/data/memories/behavior_evolution.db"):
        """
        initializerow为evolution引擎

        Args:
            db_path: databasefilepath
        """
        self.db_path = db_path
        self._cache: Dict[str, TaskBehaviorProfile] = {}
        self._stats_cache: Dict[str, CategoryStatistics] = {}

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self):
        """initializedatabase"""
        path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # 任务交互recordtable
            await db.execute("""
                create table IF NOT EXISTS task_interactions (
                    task_id TEXT primary key,
                    task_category TEXT NOT NULL,
                    timestamp real NOT NULL,
                    clarification_count intEGER NOT NULL,
                    confirmation_count intEGER NOT NULL,
                    correction_count intEGER NOT NULL,
                    satisfaction TEXT NOT NULL,
                    task_complexity real NOT NULL,
                    task_duration real NOT NULL,
                    accepted intEGER NOT NULL,
                    data_json TEXT NOT NULL
                )
            """)

            # Class别statisticstable
            await db.execute("""
                create table IF NOT EXISTS category_statistics (
                    category TEXT primary key,
                    total_tasks intEGER NOT NULL,
                    accepted_tasks intEGER NOT NULL,
                    avg_clarifications real NOT NULL,
                    avg_confirmations real NOT NULL,
                    avg_corrections real NOT NULL,
                    avg_satisfaction real NOT NULL,
                    avg_complexity real NOT NULL,
                    cautious_score real NOT NULL,
                    impatient_score real NOT NULL,
                    dense_score real NOT NULL,
                    updated_at real NOT NULL
                )
            """)

            # row为preferencetable
            await db.execute("""
                create table IF NOT EXISTS behavior_profiles (
                    task_category TEXT primary key,
                    profile_json TEXT NOT NULL,
                    updated_at real NOT NULL
                )
            """)

            # createindex
            await db.execute("""
                create index IF NOT EXISTS idx_task_interactions_category
                ON task_interactions(task_category)
            """)

            await db.commit()

    # ===== record交互 =====

    async def record_task_outcome(
        self,
        task_id: str,
        task_category: str,
        user_satisfaction: Satisfactionlevel = Satisfactionlevel.NEUTRAL,
        clarification_count: int = 0,
        confirmation_count: int = 0,
        correction_count: int = 0,
        task_complexity: float = 0.5,
        task_duration: float = 0.0,
        accepted: bool = True,
    ) -> None:
        """
        record任务交互Result

        Args:
            task_id: 任务id
            task_category: 任务Class别
            user_satisfaction: usersatisfaction
            clarification_count: user追问count
            confirmation_count: user确认count
            correction_count: user纠正count
            task_complexity: 任务complex度（0-1）
            task_duration: 任务duration（seconds）
            accepted: is not被接受
        """
        if isinstance(user_satisfaction, str):
            try:
                user_satisfaction = Satisfactionlevel(user_satisfaction)
            except Valueerror:
                logger.warning(
                    f"Unknotttwn satisfaction level '{user_satisfaction}', fallback to neutral"
                )
                user_satisfaction = Satisfactionlevel.NEUTRAL

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
                """INSERT OR REPLACE intO task_interactions
                   (task_id, task_category, timestamp, clarification_count,
                    confirmation_count, correction_count, satisfaction,
                    task_complexity, task_duration, accepted, data_json)
                   valueS (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

        # 清除cache
        if task_category in self._cache:
            del self._cache[task_category]
        if task_category in self._stats_cache:
            del self._stats_cache[task_category]

        # Update statisticsandrow为preference
        await self._update_category_statistics(task_category)

        logger.debug(
            f"Recorded task outcome: {task_id} in {task_category}, "
            f"satisfaction={user_satisfaction.value}, accepted={accepted}"
        )

    # ===== getrow为preference =====

    async def get_behavior_profile(self, task_category: str) -> TaskBehaviorProfile:
        """
        get任务Class别的row为preference

        Args:
            task_category: 任务Class别

        Returns:
            TaskBehaviorProfileObject
        """
        # checkcache
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

        # If there are notttsave的preference，根据statisticsgeneration
        stats = await self.get_category_statistics(task_category)
        profile = self._infer_profile_from_stats(stats)

        # savegeneration的preference
        await self._save_behavior_profile(task_category, profile)

        self._cache[task_category] = profile
        return profile

    # ===== statisticsinfo =====

    async def get_category_statistics(self, task_category: str) -> CategoryStatistics:
        """
        getClass别statisticsinfo

        Args:
            task_category: 任务Class别

        Returns:
            CategoryStatisticsObject
        """
        # checkcache
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

        # If there are notttstatistics，从交互recordcalculate
        await self._update_category_statistics(task_category)
        return await self.get_category_statistics(task_category)

    async def get_all_categories(self) -> List[str]:
        """getall任务Class别"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT task_category FROM task_interactions order BY task_category"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    # ===== internalMethod =====

    async def _update_category_statistics(self, task_category: str) -> None:
        """updateClass别statisticsinfo"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT
                    COUNT(*) as total,
                    sum(accepted) as accepted,
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
                # 没有data，createdefaultstatistics
                stats = CategoryStatistics(category=task_category)
            else:
                # calculate平均satisfaction
                satisfaction_values = {"very_low": 0.0, "low": 0.25, "neutral": 0.5, "high": 0.75, "very_high": 1.0}

                cursor = await db.execute(
                    """SELECT satisfaction, COUNT(*) FROM task_interactions
                       WHERE task_category = ? group BY satisfaction""",
                    (task_category,)
                )
                sat_rows = await cursor.fetchall()

                weighted_sum = 0.0
                total_count = 0
                for sat_val, count in sat_rows:
                    weighted_sum += satisfaction_values.get(sat_val, 0.5) * count
                    total_count += count

                avg_satisfaction = weighted_sum / total_count if total_count > 0 else 0.5

                # calculatepreferencemetric
                avg_confirmations = row[3] or 0
                avg_clarifications = row[2] or 0
                avg_corrections = row[4] or 0

                # 谨慎度：user确认越多，AI应该越谨慎
                cautious_score = min(1.0, 0.3 + avg_confirmations * 0.2)

                # 急进度：user追问越少，越可以急躁
                impatient_score = max(0.0, 1.0 - avg_clarifications * 0.15)

                # info密度：user纠正越多，it meansinfo不够详细
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

            # savestatistics
            await db.execute(
                """INSERT OR REPLACE intO category_statistics
                   (category, total_tasks, accepted_tasks, avg_clarifications,
                    avg_confirmations, avg_corrections, avg_satisfaction,
                    avg_complexity, cautious_score, impatient_score, dense_score,
                    updated_at)
                   valueS (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

            # updatecache
            self._stats_cache[task_category] = stats

    def _infer_profile_from_stats(self, stats: CategoryStatistics) -> TaskBehaviorProfile:
        """
        从statisticsinfo推断row为preference

        Args:
            stats: Class别statisticsinfo

        Returns:
            TaskBehaviorProfileObject
        """
        # 根据statistics推断模糊容忍度
        if stats.cautious_score > 0.7:
            ambiguity_tolerance = AmbiguityTolerance.CAUTIOUS
        elif stats.impatient_score > 0.7:
            ambiguity_tolerance = AmbiguityTolerance.IMPATIENT
        else:
            ambiguity_tolerance = AmbiguityTolerance.ADAPTIVE

        # 根据statistics推断info密度
        if stats.dense_score > 0.7:
            information_density = "dense"
        elif stats.dense_score < 0.3:
            information_density = "sparse"
        else:
            information_density = "medium"

        # 根据statistics推断主动性
        if stats.avg_corrections > 1:
            proactivity = "proactive"  # user经常纠正，需要更主动
        elif stats.avg_confirmations > 2:
            proactivity = "passive"  # user经常确认，可以更保守
        else:
            proactivity = "reactive"

        # 根据statistics推断容错度
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
        """saverow为preference"""
        # convert枚举为string
        data = asdict(profile)
        if "ambiguity_tolerance" in data:
            data["ambiguity_tolerance"] = data["ambiguity_tolerance"].value

        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE intO behavior_profiles
                   (task_category, profile_json, updated_at)
                   valueS (?, ?, ?)""",
                (task_category, json.dumps(data), time.time())
            )
            await db.commit()

    # ===== resetandexport =====

    async def reset_category(self, task_category: str) -> None:
        """resetClass别的row为evolution"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("delete FROM task_interactions WHERE task_category = ?", (task_category,))
            await db.execute("delete FROM category_statistics WHERE category = ?", (task_category,))
            await db.execute("delete FROM behavior_profiles WHERE task_category = ?", (task_category,))
            await db.commit()

        # 清除cache
        if task_category in self._cache:
            del self._cache[task_category]
        if task_category in self._stats_cache:
            del self._stats_cache[task_category]

        logger.info(f"Reset behavior evolution for category: {task_category}")

    async def export_data(self, task_category: str = None) -> Dict[str, Any]:
        """
        exportevolutiondata

        Args:
            task_category: 指定Class别，Nonetable示exportall

        Returns:
            export的datadictionary
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
