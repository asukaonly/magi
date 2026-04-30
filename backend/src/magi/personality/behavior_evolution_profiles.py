"""Behavior profile inference and persistence."""

from __future__ import annotations

import json
import time
from dataclasses import asdict

from ..core.sqlite import sqlite_connection_async
from .behavior_evolution_models import CategoryStatistics
from .models import AmbiguityTolerance, TaskBehaviorProfile


class BehaviorEvolutionProfileMixin:
    """Resolve behavior profiles from persisted profiles or inferred statistics."""

    _expanded_db_path: str
    persona_id: str
    _cache: dict[str, TaskBehaviorProfile]

    async def get_behavior_profile(self, task_category: str) -> TaskBehaviorProfile:
        """Return the behavior profile for a task category."""
        if task_category in self._cache:
            return self._cache[task_category]

        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT profile_json FROM behavior_profiles WHERE task_category = ? AND persona_id = ?",
                (task_category, self.persona_id)
            )
            row = await cursor.fetchone()

            if row:
                data = json.loads(row[0])
                if "ambiguity_tolerance" in data:
                    data["ambiguity_tolerance"] = AmbiguityTolerance(data["ambiguity_tolerance"])
                profile = TaskBehaviorProfile(**data)
                self._cache[task_category] = profile
                return profile

        stats = await self.get_category_statistics(task_category)
        profile = self._infer_profile_from_stats(stats)

        await self._save_behavior_profile(task_category, profile)

        self._cache[task_category] = profile
        return profile

    def _infer_profile_from_stats(self, stats: CategoryStatistics) -> TaskBehaviorProfile:
        """Infer behavior profile values from category statistics."""
        if stats.cautious_score > 0.7:
            ambiguity_tolerance = AmbiguityTolerance.CAUTIOUS
        elif stats.impatient_score > 0.7:
            ambiguity_tolerance = AmbiguityTolerance.IMPATIENT
        else:
            ambiguity_tolerance = AmbiguityTolerance.ADAPTIVE

        if stats.dense_score > 0.7:
            information_density = "dense"
        elif stats.dense_score < 0.3:
            information_density = "sparse"
        else:
            information_density = "medium"

        if stats.avg_corrections > 1:
            proactivity = "proactive"
        elif stats.avg_confirmations > 2:
            proactivity = "passive"
        else:
            proactivity = "reactive"

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
        """Persist behavior profile."""
        data = asdict(profile)
        if "ambiguity_tolerance" in data:
            data["ambiguity_tolerance"] = data["ambiguity_tolerance"].value

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE intO behavior_profiles
                   (task_category, profile_json, updated_at, persona_id)
                   valueS (?, ?, ?, ?)""",
                (task_category, json.dumps(data), time.time(), self.persona_id)
            )
            await db.commit()


__all__ = ["BehaviorEvolutionProfileMixin"]
