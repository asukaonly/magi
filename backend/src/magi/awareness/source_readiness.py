"""Connection-specific read model over governed L1 events and existing L2 jobs."""

from __future__ import annotations

import json
from typing import Any

from ..core.sqlite import sqlite_connection_async
from ..memory.l2.projection.governance import active_projection_event_predicate
from .source_store import SourceStore


async def visible_source_event_ids(
    store: SourceStore, memory: Any, *, connection_id: str, source_type: str
) -> list[str]:
    """Never count a source receipt as proof that forgotten L1 memory is visible."""
    ids = await store.accepted_memory_event_ids(connection_id=connection_id, source_type=source_type)
    result = []
    for event_id in ids:
        event = await memory.l1.get_user_visible_event(event_id)
        if event is not None:
            result.append(event_id)
    return result


async def source_projection_backlog(memory: Any, event_ids: list[str]) -> dict[str, int]:
    """Inspect existing jobs for the selected connection's visible evidence only."""
    result = {"pending": 0, "queued": 0, "running": 0, "claimed": 0, "completed": 0, "failed": 0}
    if memory.l2 is None or not event_ids:
        return result
    async with sqlite_connection_async(memory.memory_db_path) as db:
        rows = await db.execute_fetchall(
            "SELECT jobs.status, COUNT(*) FROM l2_projection_jobs AS jobs "
            "WHERE jobs.event_id IN (SELECT value FROM json_each(?)) "
            "AND (jobs.status IN ('completed', 'failed') OR "
            + active_projection_event_predicate("jobs.event_id") + ") GROUP BY jobs.status",
            (json.dumps(event_ids),),
        )
    result.update({row[0]: int(row[1]) for row in rows})
    result["claimed"] = result["queued"] + result["running"]
    return result
