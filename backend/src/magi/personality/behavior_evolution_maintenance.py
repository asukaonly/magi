"""Reset and export operations for behavior evolution."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from ..core.sqlite import sqlite_connection_async
from .behavior_evolution_models import CategoryStatistics
from .models import TaskBehaviorProfile

logger = logging.getLogger(__name__)


class BehaviorEvolutionMaintenanceMixin:
    """Maintenance operations for behavior evolution state."""

    _expanded_db_path: str
    persona_id: str
    _cache: dict[str, TaskBehaviorProfile]
    _stats_cache: dict[str, CategoryStatistics]

    async def reset_category(self, task_category: str) -> None:
        """Reset category behavior evolution."""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("delete FROM task_interactions WHERE task_category = ? AND persona_id = ?", (task_category, self.persona_id))
            await db.execute("delete FROM category_statistics WHERE category = ? AND persona_id = ?", (task_category, self.persona_id))
            await db.execute("delete FROM behavior_profiles WHERE task_category = ? AND persona_id = ?", (task_category, self.persona_id))
            await db.commit()

        self._cache.pop(task_category, None)
        self._stats_cache.pop(task_category, None)

        logger.info(f"Reset behavior evolution for category: {task_category}")

    async def export_data(self, task_category: str | None = None) -> dict[str, Any]:
        """Export behavior evolution data."""
        result = {}

        if task_category:
            categories = [task_category]
        else:
            categories = await self.get_all_categories()

        for category in categories:
            stats = await self.get_category_statistics(category)
            profile = await self.get_behavior_profile(category)

            result[category] = {
                "statistics": asdict(stats),
                "profile": asdict(profile),
            }

        return result


__all__ = ["BehaviorEvolutionMaintenanceMixin"]
