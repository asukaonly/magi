"""Legacy single-trait snapshot materialization for L2 assertions."""

from __future__ import annotations

import json
import time
import uuid
from typing import List, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .snapshot_protocols import _SnapshotHostProtocol


class L2SnapshotMaterializationMixin:
    """Persist the older stress-level snapshot materialization path."""

    async def _materialize_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        trait_name: str,
        trait_value: str,
        assertion_ids: List[str],
        last_interaction_at: float,
    ) -> None:
        host = cast(_SnapshotHostProtocol, self)
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()

            core_traits = {"stress_level": trait_value} if trait_name == "stress_level" else {}
            current_stress = 1.0 if trait_value == "high" else 0.2

            if existing:
                merged_traits = json.loads(existing["core_traits"] or "{}")
                merged_traits.update(core_traits)
                await db.execute(
                    """
                    UPDATE tom_snapshots
                    SET core_traits = ?, current_stress_level = ?, last_interaction_at = ?,
                        last_updated_at = ?, update_source_assertion_ids = ?,
                        snapshot_version = snapshot_version + 1
                    WHERE snapshot_id = ?
                    """,
                    (
                        json.dumps(merged_traits, ensure_ascii=False),
                        current_stress,
                        float(last_interaction_at),
                        now,
                        json.dumps(assertion_ids, ensure_ascii=False),
                        str(existing["snapshot_id"]),
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO tom_snapshots(
                        snapshot_id, entity_id, entity_type, core_traits, sensitive_triggers,
                        preferences, public_sentiment_profile, relationship_topology,
                        current_stress_level, current_mood, current_engagement, current_context,
                        interaction_count, last_interaction_at, last_updated_at,
                        update_source_assertion_ids, snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"snapshot_{uuid.uuid4().hex}",
                        entity_id,
                        entity_type,
                        json.dumps(core_traits, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        current_stress,
                        None,
                        0.5,
                        json.dumps({}, ensure_ascii=False),
                        1,
                        float(last_interaction_at),
                        now,
                        json.dumps(assertion_ids, ensure_ascii=False),
                        1,
                        now,
                    ),
                )
            await db.commit()


__all__ = ["L2SnapshotMaterializationMixin"]
