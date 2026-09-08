"""Batch canonical-name lookup for recall projection.

Phase 5: stops raw entity hashes from leaking into rendered envelopes by
giving the projection layer a way to resolve entity_id → canonical_name.

Returns only entries with a non-empty canonical_name — entity_ids missing
from the result must be treated as 'unresolvable' by the caller (typically
dropped from the user-facing envelope rather than rendered with the id).
"""

from __future__ import annotations

import sqlite3
import json
from typing import Iterable

import aiosqlite


async def get_canonical_names(
    db_path: str,
    entity_ids: Iterable[str],
) -> dict[str, str]:
    """Batch-resolve entity_id → canonical_name.

    Args:
        db_path: Path to the SQLite database containing entity_catalog.
        entity_ids: Iterable of entity_id strings to resolve.

    Returns:
        Dict mapping entity_id → canonical_name. Entity_ids without a
        non-empty canonical_name (NULL, empty, or missing row) are omitted.

    Defensive: if the entity_catalog table doesn't exist (fresh deploy /
    corrupted state), returns an empty dict so the recall pipeline doesn't
    crash. Caller treats every entity as unresolvable in that case.
    """
    ids = [str(eid) for eid in entity_ids if eid]
    if not ids:
        return {}
    query = (
        "WITH requested AS (SELECT value AS entity_id FROM json_each(?)) "
        "SELECT requested.entity_id, catalog.canonical_name FROM requested "
        "LEFT JOIN entity_identity_redirects AS redirects ON redirects.source_entity_id = requested.entity_id "
        "JOIN entity_catalog AS catalog ON catalog.entity_id = COALESCE(redirects.target_entity_id, requested.entity_id) "
        "WHERE catalog.canonical_name IS NOT NULL AND catalog.canonical_name != ''"
    )
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(query, (json.dumps(ids),)) as cursor:
                rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}
    except sqlite3.OperationalError:
        return {}
