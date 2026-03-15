"""
Internal note.

Internal note.
Internal note.

evolution rules:
Internal note.
Internal note.
Internal note.
Internal note.
"""
import aiosqlite
import json
import time
import logging
from typing import Optional, List
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

from .models import EmotionalState

logger = logging.getLogger(__name__)


# Internal note.

class MoodType(Enum):
    """Emotion type"""
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
    """Interaction result type"""
    SUCCESS = "success"              # Successfully completed task
    PARTIAL_SUCCESS = "partial"      # partsuccess
    FAILURE = "failure"              # failure
    REJECTED = "rejected"            # Rejected
    ERROR = "error"                  # Error occurred
    TIMEOUT = "timeout"              # timeout


class EngagementLevel(Enum):
    """User engagement level"""
    NONE = "none"                    # No engagement
    LOW = "low"                      # Low
    MEDIUM = "medium"                # Medium
    HIGH = "high"                    # High
    VERY_HIGH = "very_high"          # Very high


# ===== evolutionParameter =====

@dataclass
class EmotionalConfig:
    """emotionevolutionConfigurationParameter"""
    # Internal note.
    energy_decay_rate: float = 0.01
    # Internal note.
    stress_growth_rate: float = 0.1
    # Internal note.
    stress_recovery_rate: float = 0.05
    # Internal note.
    mood_fluctuation: float = 0.1
    # Internal note.
    social_decay_rate: float = 0.02
    # Internal note.
    recovery_threshold: float = 0.8
    # restorespeed
    recovery_speed: float = 0.2


# ===== emotionhistory =====

@dataclass
class Emotionalevent:
    """emotioneventrecord"""
    timestamp: float
    event_type: str                 # interaction/task/time elapsed
    previous_mood: str
    new_mood: str
    mood_delta: float               # Mood delta
    energy_delta: float             # Energy delta
    stress_delta: float             # Stress delta
    cause: str                      # reasonDescription


# Internal note.

class EmotionalStateEngine:
    """
    Internal note.

    Internal note.
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/memories/emotional_state.db",
        config: EmotionalConfig = None
    ):
        """
        Internal note.

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
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self):
        """initializedatabase"""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

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
        """Load current state from database"""
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

    # Internal note.

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel = EngagementLevel.MEDIUM,
        complexity: float = 0.5,
        description: str = ""
    ) -> EmotionalState:
        """
        Internal note.

        Args:
            Internal note.
            Internal note.
            Internal note.
            Internal note.

        Returns:
            Internal note.
        """
        state = await self.get_current_state()

        # recordoldState
        old_mood = state.current_mood
        old_energy = state.energy_level
        old_stress = state.stress_level

        # Internal note.
        mood_change = self._calculate_mood_change(outcome, user_engagement, complexity)

        # Internal note.
        energy_change = self._calculate_energy_change(outcome, complexity)

        # Internal note.
        stress_change = self._calculate_stress_change(outcome, complexity)

        # Internal note.
        state.current_mood = self._apply_mood_change(state.current_mood, mood_change)
        state.mood_intensity = max(0.0, min(1.0, state.mood_intensity + abs(mood_change) * 0.3))
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_change))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_change))
        state.updated_at = time.time()

        # updatenoteState
        state.focus_state = self._determine_focus_state(state)

        # Internal note.
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
        Internal note.

        Args:
            success: is notsuccess
            Internal note.
            Internal note.

        Returns:
            Internal note.
        """
        state = await self.get_current_state()

        # Internal note.
        if success:
            mood_boost = 0.2 * complexity
            energy_boost = 0.1 * complexity
            stress_reduction = -0.15 * complexity
        else:
            mood_boost = -0.1 * complexity
            energy_boost = -0.05 * complexity
            stress_reduction = 0.2 * complexity

        state.current_mood = self._apply_mood_change(state.current_mood, mood_boost)
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_boost))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_reduction))
        state.updated_at = time.time()

        # Internal note.
        if duration > 3600:  # Over 1 hour
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

    # Internal note.

    async def decay_over_time(self, elapsed_minutes: float) -> EmotionalState:
        """
        Internal note.

        Args:
            Internal note.

        Returns:
            Internal note.
        """
        if elapsed_minutes <= 0:
            return await self.get_current_state()

        state = await self.get_current_state()

        # Internal note.
        energy_decay = elapsed_minutes * self.config.energy_decay_rate
        state.energy_level = max(0.0, state.energy_level - energy_decay)

        # Internal note.
        stress_recovery = elapsed_minutes * self.config.stress_recovery_rate
        state.stress_level = max(0.0, state.stress_level - stress_recovery)

        # Internal note.
        if state.social_state == "engaged":
            decay_amount = elapsed_minutes * self.config.social_decay_rate
            if decay_amount > 0.5:
                state.social_state = "neutral"

        # Internal note.
        if state.current_mood != MoodType.NEUTRAL.value:
            # Internal note.
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

    # Internal note.

    async def recover(self, recovery_type: str = "rest") -> EmotionalState:
        """
        Internal note.

        Args:
            recovery_type: Recovery type (rest/sleep/deep_sleep)

        Returns:
            Internal note.
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

        # Internal note.
        if state.current_mood in [MoodType.TIRED.value, MoodType.STRESSED.value]:
            state.current_mood = MoodType.NEUTRAL.value

        state.focus_state = "normal"
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
        engagement: EngagementLevel,
        complexity: float
    ) -> float:
        """Calculate mood delta"""
        # Internal note.
        base_changes = {
            InteractionOutcome.SUCCESS: 0.15,
            InteractionOutcome.PARTIAL_SUCCESS: 0.05,
            InteractionOutcome.FAILURE: -0.1,
            InteractionOutcome.REJECTED: -0.05,
            InteractionOutcome.ERROR: -0.15,
            InteractionOutcome.TIMEOUT: -0.1,
        }

        base_change = base_changes.get(outcome, 0)

        # Internal note.
        engagement_multiplier = {
            EngagementLevel.NONE: 0.5,
            EngagementLevel.LOW: 0.8,
            EngagementLevel.MEDIUM: 1.0,
            EngagementLevel.HIGH: 1.2,
            EngagementLevel.VERY_HIGH: 1.5,
        }

        multiplier = engagement_multiplier.get(engagement, 1.0)

        # Internal note.
        complexity_factor = 0.5 + complexity * 0.5

        return base_change * multiplier * complexity_factor

    def _calculate_energy_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """Calculate energy delta"""
        # Internal note.
        if outcome in [InteractionOutcome.FAILURE, InteractionOutcome.ERROR]:
            return -0.1 * complexity

        # Internal note.
        if outcome == InteractionOutcome.SUCCESS:
            return 0.05 * complexity

        return -0.02 * complexity  # Default: small consumption

    def _calculate_stress_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """Calculate stress delta"""
        # Internal note.
        if outcome == InteractionOutcome.SUCCESS:
            return -0.1 * complexity

        # Internal note.
        if outcome in [InteractionOutcome.FAILURE, InteractionOutcome.ERROR]:
            return 0.15 * complexity

        return 0.05 * complexity

    def _apply_mood_change(self, current_mood: str, change: float) -> str:
        """Apply mood change, return new mood"""
        moods = list(MoodType)

        # Internal note.
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

        # Internal note.
        try:
            current_idx = moods.index(MoodType(current_mood))
        except ValueError:
            current_idx = 0

        if change > 0.15:
            # Internal note.
            new_idx = min(len(moods) - 1, current_idx + 1)
        elif change < -0.1:
            # Internal note.
            new_idx = max(0, current_idx - 1)
        else:
            new_idx = current_idx

        return moods[new_idx].value

    def _determine_focus_state(self, state: EmotionalState) -> str:
        """Determine focus state from current state"""
        if state.stress_level > 0.8:
            return "distracted"
        elif state.energy_level > 0.8 and state.stress_level < 0.3:
            return "flow"
        return "normal"

    def _determine_social_state(self, engagement: EngagementLevel, current: str) -> str:
        """Determine social state from engagement level"""
        if engagement in [EngagementLevel.HIGH, EngagementLevel.VERY_HIGH]:
            return "engaged"
        elif engagement == EngagementLevel.NONE:
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
        """Get recent emotional events"""
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
        """Reset emotional state to initial values"""
        self._current_state = EmotionalState()
        await self._save_current_state()

        # cleareventhistory
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute("delete FROM emotional_events")
            await db.commit()

        logger.info("Emotional state reset to initial values")
