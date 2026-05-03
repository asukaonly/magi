import time
import logging
from typing import Optional, List

from .emotional_contracts import (
    EmotionalConfig,
    EmotionalEvent,
    EngagementLevel,
    InteractionOutcome,
    MoodType,
)
from .emotional_storage import EmotionalStateStorageMixin
from .models import EmotionalState

logger = logging.getLogger(__name__)


class EmotionalStateEngine(EmotionalStateStorageMixin):
    """
    Internal note.

    Internal note.
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/memory/emotional_state.db",
        config: EmotionalConfig = None,
        *,
        persona_id: str = "",
    ):
        """
        Internal note.

        Args:
            db_path: databasefilepath
            config: evolutionConfigurationParameter
            persona_id: Stable persona identity for scoping data.
        """
        self.db_path = db_path
        self.config = config or EmotionalConfig()
        self.persona_id = persona_id
        self._current_state: Optional[EmotionalState] = None
        self._event_history: List[EmotionalEvent] = []

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

    _MOOD_POSITIVE_TRANSITION: dict[str, MoodType] = {
        MoodType.STRESSED.value: MoodType.NEUTRAL,
        MoodType.TIRED.value: MoodType.NEUTRAL,
        MoodType.CONFUSED.value: MoodType.NEUTRAL,
        MoodType.NEUTRAL.value: MoodType.HAPPY,
        MoodType.HAPPY.value: MoodType.EXCITED,
        MoodType.CURIOUS.value: MoodType.EXCITED,
        MoodType.SATISFIED.value: MoodType.EXCITED,
        MoodType.FOCUSED.value: MoodType.SATISFIED,
        MoodType.PLAYFUL.value: MoodType.EXCITED,
        MoodType.EXCITED.value: MoodType.EXCITED,
    }

    _MOOD_NEGATIVE_TRANSITION: dict[str, MoodType] = {
        MoodType.EXCITED.value: MoodType.HAPPY,
        MoodType.HAPPY.value: MoodType.NEUTRAL,
        MoodType.SATISFIED.value: MoodType.NEUTRAL,
        MoodType.PLAYFUL.value: MoodType.NEUTRAL,
        MoodType.FOCUSED.value: MoodType.TIRED,
        MoodType.CURIOUS.value: MoodType.CONFUSED,
        MoodType.NEUTRAL.value: MoodType.TIRED,
        MoodType.TIRED.value: MoodType.STRESSED,
        MoodType.CONFUSED.value: MoodType.STRESSED,
        MoodType.STRESSED.value: MoodType.STRESSED,
    }

    def _apply_mood_change(self, current_mood: str, change: float) -> str:
        """Apply mood change, return new mood"""
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

        # Use explicit mood transition maps instead of enum index arithmetic
        if change > 0.15:
            target = self._MOOD_POSITIVE_TRANSITION.get(
                current_mood, MoodType.NEUTRAL
            )
        elif change < -0.1:
            target = self._MOOD_NEGATIVE_TRANSITION.get(
                current_mood, MoodType.NEUTRAL
            )
        else:
            return current_mood

        return target.value

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


__all__ = [
    "EmotionalConfig",
    "EmotionalEvent",
    "EmotionalStateEngine",
    "EngagementLevel",
    "InteractionOutcome",
    "MoodType",
]
