"""
emotionState层 (L4) - Emotional State Layer

emotionState层recordAI的currentemotionState，这些State会根据交互Result自然变化。
emotionState影响AI的responsestyleand语气。

evolutionrule：
1. emotion波动 - 根据交互Result自然变化
2. energy衰减 - 随时间缓慢下降，休息/restore后上升
3. stress累积 - 连续complex任务增加stress，complete任务后下降
4. 社交State - 根据user互动frequencyandtype调整
"""
import aiosqlite
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import path
from dataclasses import dataclass, field, asdict
from enum import Enum

from .models import EmotionalState

logger = logging.getLogger(__name__)


# ===== 枚举定义 =====

class Moodtype(Enum):
    """emotiontype"""
    NEUTRAL = "neutral"
    happy = "happy"
    EXCITED = "excited"
    SATISFIED = "satisfied"
    CuriOUS = "curious"
    TIRED = "tired"
    strESSED = "stressed"
    CONFUSED = "confused"
    FOCUSED = "focused"
    PLAYFUL = "playful"


class InteractionOutcome(Enum):
    """交互Resulttype"""
    SUCCESS = "success"              # successcomplete任务
    PARTIAL_SUCCESS = "partial"      # partsuccess
    failURE = "failure"              # failure
    rejectED = "rejected"            # 被拒绝
    error = "error"                  # 发生error
    timeout = "timeout"              # timeout


class Engagementlevel(Enum):
    """user参与度"""
    notttne = "notttne"                    # 无参与
    LOW = "low"                      # 低参与
    MEDIUM = "medium"                # 中等参与
    HIGH = "high"                    # 高参与
    VERY_HIGH = "very_high"          # 很高参与


# ===== evolutionParameter =====

@dataclass
class EmotionalConfig:
    """emotionevolutionConfigurationParameter"""
    # energy衰减率（每minutes）
    energy_decay_rate: float = 0.01
    # stress增长率（每单位complex度）
    stress_growth_rate: float = 0.1
    # stressrestore率（每minutes）
    stress_recovery_rate: float = 0.05
    # emotion波动幅度
    mood_fluctuation: float = 0.1
    # 社交State衰减率（每minutes）
    social_decay_rate: float = 0.02
    # restore阈Value（stress超过此Value进入疲劳State）
    recovery_threshold: float = 0.8
    # restorespeed
    recovery_speed: float = 0.2


# ===== emotionhistory =====

@dataclass
class Emotionalevent:
    """emotioneventrecord"""
    timestamp: float
    event_type: str                 # 交互/任务/时间流逝
    previous_mood: str
    new_mood: str
    mood_delta: float               # emotion变化量
    energy_delta: float             # energy变化量
    stress_delta: float             # stress变化量
    cause: str                      # reasonDescription


# ===== emotionevolution引擎 =====

class EmotionalStateEngine:
    """
    emotionStateevolution引擎

    根据交互and时间流逝，dynamicupdateAI的emotionState
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/memories/emotional_state.db",
        config: EmotionalConfig = None
    ):
        """
        initializeemotionState引擎

        Args:
            db_path: databasefilepath
            config: evolutionConfigurationParameter
        """
        self.db_path = db_path
        self.config = config or EmotionalConfig()
        self._current_state: Optional[EmotionalState] = None
        self._event_history: List[Emotionalevent] = []

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        from pathlib import path
        return str(path(self.db_path).expanduser())

    async def init(self):
        """initializedatabase"""
        path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # emotionStatetable
            await db.execute("""
                create table IF NOT EXISTS emotional_state (
                    key TEXT primary key,
                    value TEXT NOT NULL,
                    updated_at real NOT NULL
                )
            """)

            # emotioneventhistorytable
            await db.execute("""
                create table IF NOT EXISTS emotional_events (
                    id intEGER primary key AUTOINCREMENT,
                    timestamp real NOT NULL,
                    event_type TEXT NOT NULL,
                    previous_mood TEXT NOT NULL,
                    new_mood TEXT NOT NULL,
                    mood_delta real NOT NULL,
                    energy_delta real NOT NULL,
                    stress_delta real NOT NULL,
                    cause TEXT NOT NULL
                )
            """)

            # createindex
            await db.execute("""
                create index IF NOT EXISTS idx_emotional_events_timestamp
                ON emotional_events(timestamp DESC)
            """)

            await db.commit()

        # loadcurrentState
        await self._load_current_state()

    # ===== Stateget =====

    async def get_current_state(self) -> EmotionalState:
        """getcurrentemotionState"""
        if self._current_state is None:
            await self._load_current_state()
        return self._current_state

    async def _load_current_state(self) -> None:
        """从databaseloadcurrentState"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM emotional_state WHERE key = 'current'"
            )
            row = await cursor.fetchone()

            if row:
                self._current_state = EmotionalState(**json.loads(row[0]))
            else:
                # initializedefaultState
                self._current_state = EmotionalState()
                await self._save_current_state()

    async def _save_current_state(self) -> None:
        """savecurrentState"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE intO emotional_state (key, value, updated_at)
                   valueS (?, ?, ?)""",
                ("current", json.dumps(asdict(self._current_state)), time.time())
            )
            await db.commit()

    # ===== 交互update =====

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: Engagementlevel = Engagementlevel.MEDIUM,
        complexity: float = 0.5,
        description: str = ""
    ) -> EmotionalState:
        """
        交互后updateemotionState

        Args:
            outcome: 交互Result
            user_engagement: user参与度
            complexity: 任务complex度（0-1）
            description: Description（用于Log）

        Returns:
            update后的emotionState
        """
        state = await self.get_current_state()

        # recordoldState
        old_mood = state.current_mood
        old_energy = state.energy_level
        old_stress = state.stress_level

        # 根据Result调整emotion
        mood_change = self._calculate_mood_change(outcome, user_engagement, complexity)

        # 调整energy（successrestoreenergy，failure消耗more）
        energy_change = self._calculate_energy_change(outcome, complexity)

        # 调整stress（complex任务增加stress，success降低stress）
        stress_change = self._calculate_stress_change(outcome, complexity)

        # 应用变化
        state.current_mood = self._apply_mood_change(state.current_mood, mood_change)
        state.mood_intensity = max(0.0, min(1.0, state.mood_intensity + abs(mood_change) * 0.3))
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_change))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_change))
        state.updated_at = time.time()

        # updatenoteState
        state.focus_state = self._determine_focus_state(state)

        # update社交State
        state.social_state = self._determine_social_state(user_engagement, state.social_state)

        # recordevent
        await self._record_event(
            event_type="interaction",
            previous_mood=old_mood,
            new_mood=state.current_mood,
            mood_delta=mood_change,
            energy_delta=energy_change,
            stress_delta=stress_change,
            cause=f"Interaction: {outcome.value}, engagement: {user_engagement.value}"
        )

        # saveState
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
        任务complete后updateemotionState

        Args:
            success: is notsuccess
            complexity: 任务complex度（0-1）
            duration: 任务duration（seconds）

        Returns:
            update后的emotionState
        """
        state = await self.get_current_state()

        # success提升emotionandenergy，failure增加stress
        if success:
            outcome = InteractionOutcome.SUCCESS
            mood_boost = 0.2 * complexity
            energy_boost = 0.1 * complexity
            stress_reduction = -0.15 * complexity
        else:
            outcome = InteractionOutcome.failURE
            mood_boost = -0.1 * complexity
            energy_boost = -0.05 * complexity
            stress_reduction = 0.2 * complexity

        state.current_mood = self._apply_mood_change(state.current_mood, mood_boost)
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_boost))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_reduction))
        state.updated_at = time.time()

        # 长时间任务后可能感到疲劳
        if duration > 3600:  # 超过1hours
            state.energy_level = max(0.0, state.energy_level - 0.1)
            if state.current_mood == Moodtype.NEUTRAL.value:
                state.current_mood = Moodtype.TIRED.value

        await self._save_current_state()

        logger.debug(
            f"Emotional state updated after task: "
            f"success={success}, complexity={complexity}, "
            f"mood={state.current_mood}, energy={state.energy_level:.2f}"
        )

        return state

    # ===== 时间evolution =====

    async def decay_over_time(self, elapsed_minutes: float) -> EmotionalState:
        """
        时间流逝后的State衰减

        Args:
            elapsed_minutes: 经过的minutes数

        Returns:
            update后的emotionState
        """
        if elapsed_minutes <= 0:
            return await self.get_current_state()

        state = await self.get_current_state()

        # energy自然衰减
        energy_decay = elapsed_minutes * self.config.energy_decay_rate
        state.energy_level = max(0.0, state.energy_level - energy_decay)

        # stress自然restore
        stress_recovery = elapsed_minutes * self.config.stress_recovery_rate
        state.stress_level = max(0.0, state.stress_level - stress_recovery)

        # 社交State衰减
        if state.social_state == "engaged":
            decay_amount = elapsed_minutes * self.config.social_decay_rate
            if decay_amount > 0.5:
                state.social_state = "neutral"

        # emotionregression中性
        if state.current_mood != Moodtype.NEUTRAL.value:
            # emotion强度逐渐降低
            state.mood_intensity = max(0.0, state.mood_intensity - 0.1 * elapsed_minutes / 60)
            if state.mood_intensity <= 0.1:
                state.current_mood = Moodtype.NEUTRAL.value
                state.mood_intensity = 0.5

        state.updated_at = time.time()

        await self._save_current_state()

        logger.debug(
            f"Emotional state decayed over {elapsed_minutes:.1f} minutes: "
            f"energy={state.energy_level:.2f}, stress={state.stress_level:.2f}"
        )

        return state

    # ===== restore机制 =====

    async def recover(self, recovery_type: str = "rest") -> EmotionalState:
        """
        restore机制（休息/睡眠后）

        Args:
            recovery_type: restoretype（rest/sleep/deep_sleep）

        Returns:
            update后的emotionState
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

        # restore后通常emotion变好
        if state.current_mood in [Moodtype.TIRED.value, Moodtype.strESSED.value]:
            state.current_mood = Moodtype.NEUTRAL.value

        state.focus_state = "notttrmal"
        state.updated_at = time.time()

        await self._save_current_state()

        # recordevent
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

    # ===== internalcalculateMethod =====

    def _calculate_mood_change(
        self,
        outcome: InteractionOutcome,
        engagement: Engagementlevel,
        complexity: float
    ) -> float:
        """calculateemotion变化量"""
        # baseemotion变化
        base_changes = {
            InteractionOutcome.SUCCESS: 0.15,
            InteractionOutcome.PARTIAL_SUCCESS: 0.05,
            InteractionOutcome.failURE: -0.1,
            InteractionOutcome.rejectED: -0.05,
            InteractionOutcome.error: -0.15,
            InteractionOutcome.timeout: -0.1,
        }

        base_change = base_changes.get(outcome, 0)

        # 参与度调整
        engagement_multiplier = {
            Engagementlevel.notttne: 0.5,
            Engagementlevel.LOW: 0.8,
            Engagementlevel.MEDIUM: 1.0,
            Engagementlevel.HIGH: 1.2,
            Engagementlevel.VERY_HIGH: 1.5,
        }

        multiplier = engagement_multiplier.get(engagement, 1.0)

        # complex度调整
        complexity_factor = 0.5 + complexity * 0.5

        return base_change * multiplier * complexity_factor

    def _calculate_energy_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """calculateenergy变化量"""
        # failure消耗moreenergy
        if outcome in [InteractionOutcome.failURE, InteractionOutcome.error]:
            return -0.1 * complexity

        # successrestore少量energy
        if outcome == InteractionOutcome.SUCCESS:
            return 0.05 * complexity

        return -0.02 * complexity  # default少量消耗

    def _calculate_stress_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """calculatestress变化量"""
        # success降低stress
        if outcome == InteractionOutcome.SUCCESS:
            return -0.1 * complexity

        # failure增加stress
        if outcome in [InteractionOutcome.failURE, InteractionOutcome.error]:
            return 0.15 * complexity

        return 0.05 * complexity

    def _apply_mood_change(self, current_mood: str, change: float) -> str:
        """应用emotion变化，Returnnewemotion"""
        moods = list(Moodtype)

        # 如果currentemotionis中性，直接根据变化确定newemotion
        if current_mood == Moodtype.NEUTRAL.value:
            if change > 0.2:
                return Moodtype.EXCITED.value
            elif change > 0.1:
                return Moodtype.happy.value
            elif change < -0.15:
                return Moodtype.strESSED.value
            elif change < -0.05:
                return Moodtype.TIRED.value
            return Moodtype.NEUTRAL.value

        # 根据变化量andcurrentemotion决定newemotion
        try:
            current_idx = moods.index(Moodtype(current_mood))
        except Valueerror:
            current_idx = 0

        if change > 0.15:
            # 正向变化，向兴奋方向move
            new_idx = min(len(moods) - 1, current_idx + 1)
        elif change < -0.1:
            # 负向变化，向疲劳方向move
            new_idx = max(0, current_idx - 1)
        else:
            new_idx = current_idx

        return moods[new_idx].value

    def _determine_focus_state(self, state: EmotionalState) -> str:
        """根据State确定noteState"""
        if state.stress_level > 0.8:
            return "distracted"
        elif state.energy_level > 0.8 and state.stress_level < 0.3:
            return "flow"
        return "notttrmal"

    def _determine_social_state(self, engagement: Engagementlevel, current: str) -> str:
        """根据参与度确定社交State"""
        if engagement in [Engagementlevel.HIGH, Engagementlevel.VERY_HIGH]:
            return "engaged"
        elif engagement == Engagementlevel.notttne:
            return "withdrawn"
        return current if current in ["engaged", "neutral", "withdrawn"] else "neutral"

    # ===== eventrecord =====

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
        """recordemotionevent"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                """INSERT intO emotional_events
                   (timestamp, event_type, previous_mood, new_mood,
                    mood_delta, energy_delta, stress_delta, cause)
                   valueS (?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event_type, previous_mood, new_mood,
                 mood_delta, energy_delta, stress_delta, cause)
            )
            await db.commit()

    # ===== historyquery =====

    async def get_recent_events(self, limit: int = 50) -> List[Emotionalevent]:
        """get最近的emotionevent"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT timestamp, event_type, previous_mood, new_mood,
                          mood_delta, energy_delta, stress_delta, cause
                   FROM emotional_events
                   order BY timestamp DESC
                   LIMIT ?""",
                (limit,)
            )
            rows = await cursor.fetchall()

            events = []
            for row in rows:
                events.append(Emotionalevent(
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

    # ===== reset =====

    async def reset(self) -> None:
        """resetemotionState到初始Value"""
        self._current_state = EmotionalState()
        await self._save_current_state()

        # cleareventhistory
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("delete FROM emotional_events")
            await db.commit()

        logger.info("Emotional state reset to initial values")
