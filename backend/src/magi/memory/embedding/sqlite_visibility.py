"""Source-side SQLite entity visibility for derived index reconciliation."""

import json
from typing import Any

from ...core.sqlite import sqlite_connection_async
from .ports import EntityVisibility


def sqlite_entity_visibility(
    db_path: str,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> EntityVisibility:
    """Build a bounded lookup over an owner-supplied internal entity query."""

    async def visible(entity_ids: list[str]) -> set[str]:
        if not entity_ids:
            return set()
        async with sqlite_connection_async(db_path, profile="readonly") as db:
            async with db.execute(
                f"SELECT entity_id FROM ({query}) AS source "
                "WHERE entity_id IN (SELECT value FROM json_each(?))",
                (*parameters, json.dumps(entity_ids)),
            ) as cursor:
                return {str(row[0]) for row in await cursor.fetchall()}

    return visible
