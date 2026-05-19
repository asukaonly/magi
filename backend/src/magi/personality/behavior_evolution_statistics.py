"""Category statistics for behavior evolution."""

from __future__ import annotations

import time

from ..core.sqlite import sqlite_connection_async
from .behavior_evolution_models import CategoryStatistics


class BehaviorEvolutionStatisticsMixin:
    """Load, compute, and cache category-level behavior statistics."""

    _expanded_db_path: str
    persona_id: str
    _stats_cache: dict[str, CategoryStatistics]

    async def get_category_statistics(self, task_category: str) -> CategoryStatistics:
        """Return aggregate behavior statistics for a task category."""
        if task_category in self._stats_cache:
            return self._stats_cache[task_category]

        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM category_statistics WHERE category = ? AND persona_id = ?",
                (task_category, self.persona_id)
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

        await self._update_category_statistics(task_category)
        return await self.get_category_statistics(task_category)

    async def get_all_categories(self) -> list[str]:
        """Get all task categories."""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT task_category FROM task_interactions WHERE persona_id = ? ORDER BY task_category",
                (self.persona_id,)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def _update_category_statistics(self, task_category: str) -> None:
        """Update category statistics from task interaction records."""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT
                    COUNT(*) as total,
                    sum(accepted) as accepted,
                    AVG(clarification_count) as avg_clar,
                    AVG(confirmation_count) as avg_conf,
                    AVG(correction_count) as avg_corr,
                    AVG(task_complexity) as avg_complex
                   FROM task_interactions
                   WHERE task_category = ? AND persona_id = ?""",
                (task_category, self.persona_id)
            )
            row = await cursor.fetchone()

            if not row or row[0] == 0:
                stats = CategoryStatistics(category=task_category)
            else:
                satisfaction_values = {"very_low": 0.0, "low": 0.25, "neutral": 0.5, "high": 0.75, "very_high": 1.0}

                cursor = await db.execute(
                    """SELECT satisfaction, COUNT(*) FROM task_interactions
                       WHERE task_category = ? AND persona_id = ? group BY satisfaction""",
                    (task_category, self.persona_id)
                )
                sat_rows = await cursor.fetchall()

                weighted_sum = 0.0
                total_count = 0
                for sat_val, count in sat_rows:
                    weighted_sum += satisfaction_values.get(sat_val, 0.5) * count
                    total_count += count

                avg_satisfaction = weighted_sum / total_count if total_count > 0 else 0.5
                avg_confirmations = row[3] or 0
                avg_clarifications = row[2] or 0
                avg_corrections = row[4] or 0

                cautious_score = min(1.0, 0.3 + avg_confirmations * 0.2)
                impatient_score = max(0.0, 1.0 - avg_clarifications * 0.15)
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

            await db.execute(
                """INSERT OR REPLACE INTO category_statistics
                   (category, total_tasks, accepted_tasks, avg_clarifications,
                    avg_confirmations, avg_corrections, avg_satisfaction,
                    avg_complexity, cautious_score, impatient_score, dense_score,
                    updated_at, persona_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    self.persona_id,
                )
            )
            await db.commit()

            self._stats_cache[task_category] = stats


__all__ = ["BehaviorEvolutionStatisticsMixin"]
