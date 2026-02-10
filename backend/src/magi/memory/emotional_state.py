"""
情绪状态层 (L4) - Emotional State Layer

情绪状态层记录AI的当前情绪状态，这些状态会根据交互结果自然变化。
情绪状态影响AI的响应风格和语气。

演化规则：
1. 情绪波动 - 根据交互结果自然变化
2. 能量衰减 - 随时间缓慢下降，休息/恢复后上升
3. 压力累积 - 连续复杂任务增加压力，完成任务后下降
4. 社交状态 - 根据用户互动频率和类型调整
"""
import aiosqlite
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum

from .models import EmotionalState

logger = logging.getLogger(__name__)


# ===== 枚举定义 =====

class MoodType(Enum):
    """情绪类型"""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    EXCITED = "excited"
    SATISFIED = "satisfied"
    CURIOUS = "curious"
    TIRED = "tired"
    STRESSED = "stressed"
    CONFUSED = "confused"
    FOCUSED = "focused"
    PLAYFUL = "playful"


class InteractionOutcome(Enum):
    """交互结果类型"""
    SUCCESS = "success"              # 成功完成任务
    PARTIAL_SUCCESS = "partial"      # 部分成功
    FAILURE = "failure"              # 失败
    REJECTED = "rejected"            # 被拒绝
    ERROR = "error"                  # 发生错误
    TIMEOUT = "timeout"              # 超时


class EngagementLevel(Enum):
    """用户参与度"""
    NONE = "none"                    # 无参与
    LOW = "low"                      # 低参与
    MEDIUM = "medium"                # 中等参与
    HIGH = "high"                    # 高参与
    VERY_HIGH = "very_high"          # 很高参与


# ===== 演化参数 =====

@dataclass
class EmotionalConfig:
    """情绪演化配置参数"""
    # 能量衰减率（每分钟）
    energy_decay_rate: float = 0.01
    # 压力增长率（每单位复杂度）
    stress_growth_rate: float = 0.1
    # 压力恢复率（每分钟）
    stress_recovery_rate: float = 0.05
    # 情绪波动幅度
    mood_fluctuation: float = 0.1
    # 社交状态衰减率（每分钟）
    social_decay_rate: float = 0.02
    # 恢复阈值（压力超过此值进入疲劳状态）
    recovery_threshold: float = 0.8
    # 恢复速度
    recovery_speed: float = 0.2


# ===== 情绪历史 =====

@dataclass
class EmotionalEvent:
    """情绪事件记录"""
    timestamp: float
    event_type: str                 # 交互/任务/时间流逝
    previous_mood: str
    new_mood: str
    mood_delta: float               # 情绪变化量
    energy_delta: float             # 能量变化量
    stress_delta: float             # 压力变化量
    cause: str                      # 原因描述


# ===== 情绪演化引擎 =====

class EmotionalStateEngine:
    """
    情绪状态演化引擎

    根据交互和时间流逝，动态更新AI的情绪状态
    """

    def __init__(
        self,
        db_path: str = "./data/memories/emotional_state.db",
        config: EmotionalConfig = None
    ):
        """
        初始化情绪状态引擎

        Args:
            db_path: 数据库文件路径
            config: 演化配置参数
        """
        self.db_path = db_path
        self.config = config or EmotionalConfig()
        self._current_state: Optional[EmotionalState] = None
        self._event_history: List[EmotionalEvent] = []

    async def init(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # 情绪状态表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS emotional_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

            # 情绪事件历史表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS emotional_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    previous_mood TEXT NOT NULL,
                    new_mood TEXT NOT NULL,
                    mood_delta REAL NOT NULL,
                    energy_delta REAL NOT NULL,
                    stress_delta REAL NOT NULL,
                    cause TEXT NOT NULL
                )
            """)

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotional_events_timestamp
                ON emotional_events(timestamp DESC)
            """)

            await db.commit()

        # 加载当前状态
        await self._load_current_state()

    # ===== 状态获取 =====

    async def get_current_state(self) -> EmotionalState:
        """获取当前情绪状态"""
        if self._current_state is None:
            await self._load_current_state()
        return self._current_state

    async def _load_current_state(self) -> None:
        """从数据库加载当前状态"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM emotional_state WHERE key = 'current'"
            )
            row = await cursor.fetchone()

            if row:
                self._current_state = EmotionalState(**json.loads(row[0]))
            else:
                # 初始化默认状态
                self._current_state = EmotionalState()
                await self._save_current_state()

    async def _save_current_state(self) -> None:
        """保存当前状态"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO emotional_state (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                ("current", json.dumps(asdict(self._current_state)), time.time())
            )
            await db.commit()

    # ===== 交互更新 =====

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel = EngagementLevel.MEDIUM,
        complexity: float = 0.5,
        description: str = ""
    ) -> EmotionalState:
        """
        交互后更新情绪状态

        Args:
            outcome: 交互结果
            user_engagement: 用户参与度
            complexity: 任务复杂度（0-1）
            description: 描述（用于日志）

        Returns:
            更新后的情绪状态
        """
        state = await self.get_current_state()

        # 记录旧状态
        old_mood = state.current_mood
        old_energy = state.energy_level
        old_stress = state.stress_level

        # 根据结果调整情绪
        mood_change = self._calculate_mood_change(outcome, user_engagement, complexity)

        # 调整能量（成功恢复能量，失败消耗更多）
        energy_change = self._calculate_energy_change(outcome, complexity)

        # 调整压力（复杂任务增加压力，成功降低压力）
        stress_change = self._calculate_stress_change(outcome, complexity)

        # 应用变化
        state.current_mood = self._apply_mood_change(state.current_mood, mood_change)
        state.mood_intensity = max(0.0, min(1.0, state.mood_intensity + abs(mood_change) * 0.3))
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_change))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_change))
        state.updated_at = time.time()

        # 更新注意状态
        state.focus_state = self._determine_focus_state(state)

        # 更新社交状态
        state.social_state = self._determine_social_state(user_engagement, state.social_state)

        # 记录事件
        await self._record_event(
            event_type="interaction",
            previous_mood=old_mood,
            new_mood=state.current_mood,
            mood_delta=mood_change,
            energy_delta=energy_change,
            stress_delta=stress_change,
            cause=f"Interaction: {outcome.value}, engagement: {user_engagement.value}"
        )

        # 保存状态
        await self._save_current_state()

        logger.debug(
            f"Emotional state updated after interaction: "
            f"mood {old_mood} -> {state.current_mood}, "
            f"energy {old_energy:.2f} -> {state.energy_level:.2f}, "
            f"stress {old_stress:.2f} -> {state.stress_level:.2f}"
        )

        return state

    async def update_after_task_completion(
        self,
        success: bool,
        complexity: float,
        duration: float
    ) -> EmotionalState:
        """
        任务完成后更新情绪状态

        Args:
            success: 是否成功
            complexity: 任务复杂度（0-1）
            duration: 任务持续时间（秒）

        Returns:
            更新后的情绪状态
        """
        state = await self.get_current_state()

        # 成功提升情绪和能量，失败增加压力
        if success:
            outcome = InteractionOutcome.SUCCESS
            mood_boost = 0.2 * complexity
            energy_boost = 0.1 * complexity
            stress_reduction = -0.15 * complexity
        else:
            outcome = InteractionOutcome.FAILURE
            mood_boost = -0.1 * complexity
            energy_boost = -0.05 * complexity
            stress_reduction = 0.2 * complexity

        state.current_mood = self._apply_mood_change(state.current_mood, mood_boost)
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_boost))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_reduction))
        state.updated_at = time.time()

        # 长时间任务后可能感到疲劳
        if duration > 3600:  # 超过1小时
            state.energy_level = max(0.0, state.energy_level - 0.1)
            if state.current_mood == MoodType.NEUTRAL.value:
                state.current_mood = MoodType.TIRED.value

        await self._save_current_state()

        logger.debug(
            f"Emotional state updated after task: "
            f"success={success}, complexity={complexity}, "
            f"mood={state.current_mood}, energy={state.energy_level:.2f}"
        )

        return state

    # ===== 时间演化 =====

    async def decay_over_time(self, elapsed_minutes: float) -> EmotionalState:
        """
        时间流逝后的状态衰减

        Args:
            elapsed_minutes: 经过的分钟数

        Returns:
            更新后的情绪状态
        """
        if elapsed_minutes <= 0:
            return await self.get_current_state()

        state = await self.get_current_state()

        # 能量自然衰减
        energy_decay = elapsed_minutes * self.config.energy_decay_rate
        state.energy_level = max(0.0, state.energy_level - energy_decay)

        # 压力自然恢复
        stress_recovery = elapsed_minutes * self.config.stress_recovery_rate
        state.stress_level = max(0.0, state.stress_level - stress_recovery)

        # 社交状态衰减
        if state.social_state == "engaged":
            decay_amount = elapsed_minutes * self.config.social_decay_rate
            if decay_amount > 0.5:
                state.social_state = "neutral"

        # 情绪回归中性
        if state.current_mood != MoodType.NEUTRAL.value:
            # 情绪强度逐渐降低
            state.mood_intensity = max(0.0, state.mood_intensity - 0.1 * elapsed_minutes / 60)
            if state.mood_intensity <= 0.1:
                state.current_mood = MoodType.NEUTRAL.value
                state.mood_intensity = 0.5

        state.updated_at = time.time()

        await self._save_current_state()

        logger.debug(
            f"Emotional state decayed over {elapsed_minutes:.1f} minutes: "
            f"energy={state.energy_level:.2f}, stress={state.stress_level:.2f}"
        )

        return state

    # ===== 恢复机制 =====

    async def recover(self, recovery_type: str = "rest") -> EmotionalState:
        """
        恢复机制（休息/睡眠后）

        Args:
            recovery_type: 恢复类型（rest/sleep/deep_sleep）

        Returns:
            更新后的情绪状态
        """
        state = await self.get_current_state()

        recovery_amounts = {
            "rest": {"energy": 0.3, "stress": -0.2},
            "sleep": {"energy": 0.7, "stress": -0.5},
            "deep_sleep": {"energy": 1.0, "stress": -0.8},
        }

        recovery = recovery_amounts.get(recovery_type, recovery_amounts["rest"])

        state.energy_level = min(1.0, state.energy_level + recovery["energy"])
        state.stress_level = max(0.0, state.stress_level + recovery["stress"])

        # 恢复后通常情绪变好
        if state.current_mood in [MoodType.TIRED.value, MoodType.STRESSED.value]:
            state.current_mood = MoodType.NEUTRAL.value

        state.focus_state = "normal"
        state.updated_at = time.time()

        await self._save_current_state()

        # 记录事件
        await self._record_event(
            event_type="recovery",
            previous_mood=state.current_mood,
            new_mood=state.current_mood,
            mood_delta=0,
            energy_delta=recovery["energy"],
            stress_delta=recovery["stress"],
            cause=f"Recovery: {recovery_type}"
        )

        logger.info(f"Emotional state recovered: type={recovery_type}, energy={state.energy_level:.2f}")

        return state

    # ===== 内部计算方法 =====

    def _calculate_mood_change(
        self,
        outcome: InteractionOutcome,
        engagement: EngagementLevel,
        complexity: float
    ) -> float:
        """计算情绪变化量"""
        # 基础情绪变化
        base_changes = {
            InteractionOutcome.SUCCESS: 0.15,
            InteractionOutcome.PARTIAL_SUCCESS: 0.05,
            InteractionOutcome.FAILURE: -0.1,
            InteractionOutcome.REJECTED: -0.05,
            InteractionOutcome.ERROR: -0.15,
            InteractionOutcome.TIMEOUT: -0.1,
        }

        base_change = base_changes.get(outcome, 0)

        # 参与度调整
        engagement_multiplier = {
            EngagementLevel.NONE: 0.5,
            EngagementLevel.LOW: 0.8,
            EngagementLevel.MEDIUM: 1.0,
            EngagementLevel.HIGH: 1.2,
            EngagementLevel.VERY_HIGH: 1.5,
        }

        multiplier = engagement_multiplier.get(engagement, 1.0)

        # 复杂度调整
        complexity_factor = 0.5 + complexity * 0.5

        return base_change * multiplier * complexity_factor

    def _calculate_energy_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """计算能量变化量"""
        # 失败消耗更多能量
        if outcome in [InteractionOutcome.FAILURE, InteractionOutcome.ERROR]:
            return -0.1 * complexity

        # 成功恢复少量能量
        if outcome == InteractionOutcome.SUCCESS:
            return 0.05 * complexity

        return -0.02 * complexity  # 默认少量消耗

    def _calculate_stress_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """计算压力变化量"""
        # 成功降低压力
        if outcome == InteractionOutcome.SUCCESS:
            return -0.1 * complexity

        # 失败增加压力
        if outcome in [InteractionOutcome.FAILURE, InteractionOutcome.ERROR]:
            return 0.15 * complexity

        return 0.05 * complexity

    def _apply_mood_change(self, current_mood: str, change: float) -> str:
        """应用情绪变化，返回新情绪"""
        moods = list(MoodType)

        # 如果当前情绪是中性，直接根据变化确定新情绪
        if current_mood == MoodType.NEUTRAL.value:
            if change > 0.2:
                return MoodType.EXCITED.value
            elif change > 0.1:
                return MoodType.HAPPY.value
            elif change < -0.15:
                return MoodType.STRESSED.value
            elif change < -0.05:
                return MoodType.TIRED.value
            return MoodType.NEUTRAL.value

        # 根据变化量和当前情绪决定新情绪
        try:
            current_idx = moods.index(MoodType(current_mood))
        except ValueError:
            current_idx = 0

        if change > 0.15:
            # 正向变化，向兴奋方向移动
            new_idx = min(len(moods) - 1, current_idx + 1)
        elif change < -0.1:
            # 负向变化，向疲劳方向移动
            new_idx = max(0, current_idx - 1)
        else:
            new_idx = current_idx

        return moods[new_idx].value

    def _determine_focus_state(self, state: EmotionalState) -> str:
        """根据状态确定注意状态"""
        if state.stress_level > 0.8:
            return "distracted"
        elif state.energy_level > 0.8 and state.stress_level < 0.3:
            return "flow"
        return "normal"

    def _determine_social_state(self, engagement: EngagementLevel, current: str) -> str:
        """根据参与度确定社交状态"""
        if engagement in [EngagementLevel.HIGH, EngagementLevel.VERY_HIGH]:
            return "engaged"
        elif engagement == EngagementLevel.NONE:
            return "withdrawn"
        return current if current in ["engaged", "neutral", "withdrawn"] else "neutral"

    # ===== 事件记录 =====

    async def _record_event(
        self,
        event_type: str,
        previous_mood: str,
        new_mood: str,
        mood_delta: float,
        energy_delta: float,
        stress_delta: float,
        cause: str
    ) -> None:
        """记录情绪事件"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO emotional_events
                   (timestamp, event_type, previous_mood, new_mood,
                    mood_delta, energy_delta, stress_delta, cause)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event_type, previous_mood, new_mood,
                 mood_delta, energy_delta, stress_delta, cause)
            )
            await db.commit()

    # ===== 历史查询 =====

    async def get_recent_events(self, limit: int = 50) -> List[EmotionalEvent]:
        """获取最近的情绪事件"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT timestamp, event_type, previous_mood, new_mood,
                          mood_delta, energy_delta, stress_delta, cause
                   FROM emotional_events
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,)
            )
            rows = await cursor.fetchall()

            events = []
            for row in rows:
                events.append(EmotionalEvent(
                    timestamp=row[0],
                    event_type=row[1],
                    previous_mood=row[2],
                    new_mood=row[3],
                    mood_delta=row[4],
                    energy_delta=row[5],
                    stress_delta=row[6],
                    cause=row[7],
                ))

            return events

    # ===== 重置 =====

    async def reset(self) -> None:
        """重置情绪状态到初始值"""
        self._current_state = EmotionalState()
        await self._save_current_state()

        # 清空事件历史
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM emotional_events")
            await db.commit()

        logger.info("Emotional state reset to initial values")
