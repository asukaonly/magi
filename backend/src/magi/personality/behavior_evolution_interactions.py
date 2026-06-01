"""Task interaction recording for behavior evolution."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict

from ..core.sqlite import sqlite_connection_async
from .behavior_evolution_models import SatisfactionLevel, TaskInteractionRecord
from .models import TaskBehaviorProfile

logger = logging.getLogger(__name__)


class BehaviorEvolutionInteractionMixin:
    """Record user/task outcomes and invalidate derived behavior caches."""

    _expanded_db_path: str
    persona_id: str
    _cache: dict[str, TaskBehaviorProfile]
    _stats_cache: dict[str, object]

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
        """Record a task outcome and refresh category statistics."""
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
        record_data["satisfaction"] = record.satisfaction.value

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO task_interactions
                   (task_id, task_category, timestamp, clarification_count,
                    confirmation_count, correction_count, satisfaction,
                    task_complexity, task_duration, accepted, data_json, persona_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    self.persona_id,
                )
            )
            # The persisted behavior_profiles row is a memoised inference from
            # task_interactions + category_statistics. A new outcome makes that
            # cache stale; drop it so the next get_behavior_profile re-runs
            # _infer_profile_from_stats. Without this delete the feedback loop
            # silently closes on the first turn and freezes the inferred
            # profile forever — exactly the dead-loop the P2 review flagged.
            await db.execute(
                "DELETE FROM behavior_profiles WHERE task_category = ? AND persona_id = ?",
                (task_category, self.persona_id),
            )
            await db.commit()

        self._cache.pop(task_category, None)
        self._stats_cache.pop(task_category, None)

        await self._update_category_statistics(task_category)

        logger.debug(
            f"Recorded task outcome: {task_id} in {task_category}, "
            f"satisfaction={user_satisfaction.value}, accepted={accepted}"
        )


__all__ = ["BehaviorEvolutionInteractionMixin"]
