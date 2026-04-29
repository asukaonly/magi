"""SQLite schema helpers for personality growth memory."""

from __future__ import annotations

import aiosqlite


async def ensure_growth_memory_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        create table IF NOT EXISTS milestones (
            id TEXT primary key,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            timestamp real NOT NULL,
            metadata TEXT NOT NULL,
            persona_id TEXT NOT NULL DEFAULT ''
        )
    """)

    await db.execute("""
        create table IF NOT EXISTS relationships (
            user_id TEXT primary key,
            depth real NOT NULL,
            first_interaction real NOT NULL,
            last_interaction real NOT NULL,
            total_interactions intEGER NOT NULL,
            interaction_types TEXT NOT NULL,
            sentiment_score real NOT NULL,
            trust_level real NOT NULL,
            notes TEXT NOT NULL,
            updated_at real NOT NULL,
            persona_id TEXT NOT NULL DEFAULT ''
        )
    """)

    for table_name in ("milestones", "relationships"):
        try:
            await db.execute(f"ALTER TABLE {table_name} ADD COLUMN persona_id TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass

    await db.execute("""
        create table IF NOT EXISTS personality_evolution (
            id intEGER primary key AUTOINCREMENT,
            timestamp real NOT NULL,
            aspect TEXT NOT NULL,
            previous_value TEXT NOT NULL,
            new_value TEXT NOT NULL,
            confidence real NOT NULL,
            reason TEXT NOT NULL
        )
    """)

    await db.execute("""
        create table IF NOT EXISTS growth_statistics (
            key TEXT primary key,
            value TEXT NOT NULL,
            updated_at real NOT NULL
        )
    """)

    await db.execute("""
        create index IF NOT EXISTS idx_milestones_timestamp
        ON milestones(timestamp DESC)
    """)
    await db.execute("""
        create index IF NOT EXISTS idx_milestones_persona
        ON milestones(persona_id, timestamp DESC)
    """)
    await db.execute("""
        create index IF NOT EXISTS idx_relationships_updated
        ON relationships(updated_at DESC)
    """)
    await db.execute("""
        create index IF NOT EXISTS idx_relationships_persona
        ON relationships(persona_id, user_id)
    """)

    await db.commit()


__all__ = ["ensure_growth_memory_schema"]