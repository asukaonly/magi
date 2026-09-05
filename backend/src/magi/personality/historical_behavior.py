"""Deletion-only governance for previously collected behavior data."""

from __future__ import annotations

from pathlib import Path

from ..core.sqlite import secure_compact_sqlite, sqlite_connection_async


async def clear_historical_behavior_data(db_path: str) -> int:
    """Erase historical behavior rows during an explicit learned-state clear."""
    path = Path(db_path).expanduser()
    if not path.exists():
        return 0

    deleted = 0
    async with sqlite_connection_async(str(path)) as db:
        for table_name in ("task_interactions", "category_statistics", "behavior_profiles"):
            cursor = await db.execute(f"DELETE FROM {table_name}")
            deleted += max(0, int(cursor.rowcount or 0))
        await db.commit()

    await secure_compact_sqlite(str(path))
    return deleted
