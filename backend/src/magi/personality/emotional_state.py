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


# Lazy decay applies when ``get_current_state`` observes an elapsed gap of at
# least this many seconds since the last update. Sub-minute gaps (typical
# within an active chat session) skip the decay+write path entirely.
LAZY_DECAY_THRESHOLD_SECONDS = 60.0


def apply_decay_to_state(
    state: EmotionalState,
    elapsed_minutes: float,
    config: EmotionalConfig,
) -> None:
    """Mutate ``state`` in place by applying ``elapsed_minutes`` worth of decay.

    Pure function so the storage mixin can call this on lazy reads without
    going through ``EmotionalStateEngine.decay_over_time`` (which would
    recursively re-enter ``get_current_state``). Callers are responsible for
    updating ``state.updated_at`` and persisting.

    Decay model:
    - energy drops linearly with ``energy_decay_rate`` per minute.
    - stress recovers linearly with ``stress_recovery_rate`` per minute.
    - social state "engaged" drops back to "neutral" after the equivalent
      of a half-unit social decay (configurable per persona).
    - mood intensity fades 0.1 per hour; once it crosses 0.1 the mood
      snaps back to NEUTRAL with intensity 0.5.
    """
    if elapsed_minutes <= 0:
        return

    energy_decay = elapsed_minutes * config.energy_decay_rate
    state.energy_level = max(0.0, state.energy_level - energy_decay)

    stress_recovery = elapsed_minutes * config.stress_recovery_rate
    state.stress_level = max(0.0, state.stress_level - stress_recovery)

    if state.social_state == "engaged":
        decay_amount = elapsed_minutes * config.social_decay_rate
        if decay_amount > 0.5:
            state.social_state = "neutral"

    if state.current_mood != MoodType.NEUTRAL.value:
        state.mood_intensity = max(0.0, state.mood_intensity - 0.1 * elapsed_minutes / 60)
        if state.mood_intensity <= 0.1:
            state.current_mood = MoodType.NEUTRAL.value
            state.mood_intensity = 0.5


def _interaction_cause(
    outcome: InteractionOutcome,
    user_engagement: EngagementLevel,
) -> str:
    return f"Interaction: {outcome.value}, engagement: {user_engagement.value}"


def _log_interaction_update(
    *,
    state: EmotionalState,
    old_mood: str,
    old_energy: float,
    old_stress: float,
) -> None:
    logger.debug(
        f"Emotional state updated after interaction: "
        f"mood {old_mood} -> {state.current_mood}, "
        f"energy {old_energy:.2f} -> {state.energy_level:.2f}, "
        f"stress {old_stress:.2f} -> {state.stress_level:.2f}"
    )


class EmotionalStateEngine(EmotionalStateStorageMixin):
    """Persona-scoped emotional state engine: mood/energy/stress with decay and recovery."""

    def __init__(
        self,
        db_path: str = "~/.magi/data/memory/emotional_state.db",
        config: EmotionalConfig = None,
        *,
        persona_id: str = "",
    ):
        self.db_path = db_path
        self.config = config or EmotionalConfig()
        self.persona_id = persona_id
        self._current_state: Optional[EmotionalState] = None
        self._event_history: List[EmotionalEvent] = []

    async def get_current_state(self) -> EmotionalState:
        """Return the current emotional state, applying lazy time-based decay.

        The persona's mood/energy/stress is meant to drift toward neutral while
        the user is idle (energy fades, stress recovers, intensity decays).
        Production has no separate scheduler driving ``decay_over_time``, so
        this read path applies elapsed-time decay implicitly whenever the gap
        since the last update exceeds ``LAZY_DECAY_THRESHOLD_SECONDS``. Reads
        inside the same active turn (sub-minute) skip the decay+write path,
        so this stays cheap.
        """
        state = await super().get_current_state()
        elapsed_seconds = time.time() - float(state.updated_at or 0.0)
        if elapsed_seconds < LAZY_DECAY_THRESHOLD_SECONDS:
            return state
        apply_decay_to_state(
            state,
            elapsed_minutes=elapsed_seconds / 60.0,
            config=self.config,
        )
        state.updated_at = time.time()
        await self._save_current_state()
        logger.debug(
            "Lazy decay applied: persona=%s elapsed_minutes=%.1f energy=%.2f stress=%.2f mood=%s",
            self.persona_id or "default",
            elapsed_seconds / 60.0,
            state.energy_level,
            state.stress_level,
            state.current_mood,
        )
        return state

    async def update_after_interaction(
        self,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel = EngagementLevel.MEDIUM,
        complexity: float = 0.5,
        description: str = "",
    ) -> EmotionalState:
        """Update mood, energy, and stress after an interaction."""
        state = await self.get_current_state()
        old_mood = state.current_mood
        old_energy = state.energy_level
        old_stress = state.stress_level

        mood_change, energy_change, stress_change = self._interaction_deltas(
            outcome=outcome,
            user_engagement=user_engagement,
            complexity=complexity,
        )
        self._apply_interaction_deltas(
            state=state,
            user_engagement=user_engagement,
            mood_change=mood_change,
            energy_change=energy_change,
            stress_change=stress_change,
        )
        await self._record_interaction_event(
            state=state,
            previous_mood=old_mood,
            outcome=outcome,
            user_engagement=user_engagement,
            mood_change=mood_change,
            energy_change=energy_change,
            stress_change=stress_change,
        )
        await self._save_current_state()
        _log_interaction_update(
            state=state,
            old_mood=old_mood,
            old_energy=old_energy,
            old_stress=old_stress,
        )

        return state

    def _interaction_deltas(
        self,
        *,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel,
        complexity: float,
    ) -> tuple[float, float, float]:
        mood_change = self._calculate_mood_change(outcome, user_engagement, complexity)
        energy_change = self._calculate_energy_change(outcome, complexity)
        stress_change = self._calculate_stress_change(outcome, complexity)
        return mood_change, energy_change, stress_change

    def _apply_interaction_deltas(
        self,
        *,
        state: EmotionalState,
        user_engagement: EngagementLevel,
        mood_change: float,
        energy_change: float,
        stress_change: float,
    ) -> None:
        state.current_mood = self._apply_mood_change(state.current_mood, mood_change)
        state.mood_intensity = max(0.0, min(1.0, state.mood_intensity + abs(mood_change) * 0.3))
        state.energy_level = max(0.0, min(1.0, state.energy_level + energy_change))
        state.stress_level = max(0.0, min(1.0, state.stress_level + stress_change))
        state.updated_at = time.time()
        state.focus_state = self._determine_focus_state(state)
        state.social_state = self._determine_social_state(user_engagement, state.social_state)

    async def _record_interaction_event(
        self,
        *,
        state: EmotionalState,
        previous_mood: str,
        outcome: InteractionOutcome,
        user_engagement: EngagementLevel,
        mood_change: float,
        energy_change: float,
        stress_change: float,
    ) -> None:
        await self._record_event(
            event_type="interaction",
            previous_mood=previous_mood,
            new_mood=state.current_mood,
            mood_delta=mood_change,
            energy_delta=energy_change,
            stress_delta=stress_change,
            cause=_interaction_cause(outcome, user_engagement),
        )

    async def update_after_task_completion(
        self, success: bool, complexity: float, duration: float
    ) -> EmotionalState:
        """Update emotional state after a task ends; reduces energy on long-running tasks."""
        state = await self.get_current_state()

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

    async def decay_over_time(self, elapsed_minutes: float) -> EmotionalState:
        """Apply time-based decay: energy fades, stress recovers, mood drifts back to neutral."""
        if elapsed_minutes <= 0:
            return await self.get_current_state()

        state = await self.get_current_state()
        apply_decay_to_state(state, elapsed_minutes, self.config)
        state.updated_at = time.time()

        await self._save_current_state()

        logger.debug(
            f"Emotional state decayed over {elapsed_minutes:.1f} minutes: "
            f"energy={state.energy_level:.2f}, stress={state.stress_level:.2f}"
        )

        return state

    async def recover(self, recovery_type: str = "rest") -> EmotionalState:
        """Boost energy and clear stress; ``recovery_type`` is one of rest/sleep/deep_sleep."""
        state = await self.get_current_state()

        recovery_amounts = {
            "rest": {"energy": 0.3, "stress": -0.2},
            "sleep": {"energy": 0.7, "stress": -0.5},
            "deep_sleep": {"energy": 1.0, "stress": -0.8},
        }

        recovery = recovery_amounts.get(recovery_type, recovery_amounts["rest"])

        state.energy_level = min(1.0, state.energy_level + recovery["energy"])
        state.stress_level = max(0.0, state.stress_level + recovery["stress"])

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
            cause=f"Recovery: {recovery_type}",
        )

        logger.info(
            f"Emotional state recovered: type={recovery_type}, energy={state.energy_level:.2f}"
        )

        return state

    # ===== internalcalculateMethod =====

    def _calculate_mood_change(
        self, outcome: InteractionOutcome, engagement: EngagementLevel, complexity: float
    ) -> float:
        """Calculate mood delta"""
        base_changes = {
            InteractionOutcome.SUCCESS: 0.15,
            InteractionOutcome.PARTIAL_SUCCESS: 0.05,
            InteractionOutcome.FAILURE: -0.1,
            InteractionOutcome.REJECTED: -0.05,
            InteractionOutcome.ERROR: -0.15,
            InteractionOutcome.TIMEOUT: -0.1,
        }

        base_change = base_changes.get(outcome, 0)

        engagement_multiplier = {
            EngagementLevel.NONE: 0.5,
            EngagementLevel.LOW: 0.8,
            EngagementLevel.MEDIUM: 1.0,
            EngagementLevel.HIGH: 1.2,
            EngagementLevel.VERY_HIGH: 1.5,
        }

        multiplier = engagement_multiplier.get(engagement, 1.0)

        complexity_factor = 0.5 + complexity * 0.5

        return base_change * multiplier * complexity_factor

    def _calculate_energy_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """Calculate energy delta"""
        if outcome in [InteractionOutcome.FAILURE, InteractionOutcome.ERROR]:
            return -0.1 * complexity

        if outcome == InteractionOutcome.SUCCESS:
            return 0.05 * complexity

        return -0.02 * complexity  # Default: small consumption

    def _calculate_stress_change(self, outcome: InteractionOutcome, complexity: float) -> float:
        """Calculate stress delta"""
        if outcome == InteractionOutcome.SUCCESS:
            return -0.1 * complexity

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
            target = self._MOOD_POSITIVE_TRANSITION.get(current_mood, MoodType.NEUTRAL)
        elif change < -0.1:
            target = self._MOOD_NEGATIVE_TRANSITION.get(current_mood, MoodType.NEUTRAL)
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
    "LAZY_DECAY_THRESHOLD_SECONDS",
    "MoodType",
    "apply_decay_to_state",
]
