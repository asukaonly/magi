"""Behavior evolution facade."""

from __future__ import annotations

from pathlib import Path

from .behavior_evolution_interactions import BehaviorEvolutionInteractionMixin
from .behavior_evolution_maintenance import BehaviorEvolutionMaintenanceMixin
from .behavior_evolution_models import CategoryStatistics, SatisfactionLevel, TaskInteractionRecord
from .behavior_evolution_preferences import BehaviorEvolutionPreferenceMixin
from .behavior_evolution_profiles import BehaviorEvolutionProfileMixin
from .behavior_evolution_schema import BehaviorEvolutionSchemaMixin
from .behavior_evolution_statistics import BehaviorEvolutionStatisticsMixin
from .models import TaskBehaviorProfile


class BehaviorEvolutionEngine(
    BehaviorEvolutionMaintenanceMixin,
    BehaviorEvolutionPreferenceMixin,
    BehaviorEvolutionProfileMixin,
    BehaviorEvolutionStatisticsMixin,
    BehaviorEvolutionInteractionMixin,
    BehaviorEvolutionSchemaMixin,
):
    """Coordinates behavior evolution storage, statistics, and profile inference."""

    def __init__(self, db_path: str = "~/.magi/data/memory/behavior_evolution.db", *, persona_id: str = ""):
        """Initialize behavior evolution engine."""
        self.db_path = db_path
        self.persona_id = persona_id
        self._cache: dict[str, TaskBehaviorProfile] = {}
        self._stats_cache: dict[str, CategoryStatistics] = {}

    @property
    def _expanded_db_path(self) -> str:
        """Return expanded database path."""
        return str(Path(self.db_path).expanduser())


__all__ = [
    "BehaviorEvolutionEngine",
    "CategoryStatistics",
    "SatisfactionLevel",
    "TaskInteractionRecord",
]
