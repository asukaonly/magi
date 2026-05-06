"""Behavior evolution database schema helpers."""

from __future__ import annotations

from pathlib import Path

from ..core.sqlite import sqlite_connection_async


class BehaviorEvolutionSchemaMixin:
    """Initialize and migrate the behavior evolution database."""

    _expanded_db_path: str

    async def init(self):
        """Initialize behavior evolution database tables."""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("""
                create table IF NOT EXISTS task_interactions (
                    task_id TEXT primary key,
                    task_category TEXT NOT NULL,
                    timestamp real NOT NULL,
                    clarification_count intEGER NOT NULL,
                    confirmation_count intEGER NOT NULL,
                    correction_count intEGER NOT NULL,
                    satisfaction TEXT NOT NULL,
                    task_complexity real NOT NULL,
                    task_duration real NOT NULL,
                    accepted intEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT ''
                )
            """)

            await db.execute("""
                create table IF NOT EXISTS category_statistics (
                    category TEXT primary key,
                    total_tasks intEGER NOT NULL,
                    accepted_tasks intEGER NOT NULL,
                    avg_clarifications real NOT NULL,
                    avg_confirmations real NOT NULL,
                    avg_corrections real NOT NULL,
                    avg_satisfaction real NOT NULL,
                    avg_complexity real NOT NULL,
                    cautious_score real NOT NULL,
                    impatient_score real NOT NULL,
                    dense_score real NOT NULL,
                    updated_at real NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT ''
                )
            """)

            await db.execute("""
                create table IF NOT EXISTS behavior_profiles (
                    task_category TEXT primary key,
                    profile_json TEXT NOT NULL,
                    updated_at real NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT ''
                )
            """)

            await db.execute("""
                create index IF NOT EXISTS idx_task_interactions_category
                ON task_interactions(task_category)
            """)
            await db.execute("""
                create index IF NOT EXISTS idx_task_interactions_persona
                ON task_interactions(persona_id, task_category)
            """)

            await db.commit()


__all__ = ["BehaviorEvolutionSchemaMixin"]
