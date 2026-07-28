"""Version, dependency, and materialized-reference rewrites for relationships."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ..corrections.fingerprints import relationship_claim_fingerprint
from .relationship_rekey_identity import relationship_slot_key_on_connection


async def rewrite_materialized_relationship_references(
    db: aiosqlite.Connection,
    reference_map: Mapping[str, str],
) -> None:
    """Rewrite derived relationship references once for a completed rekey batch."""
    await _rewrite_materialized_json_references(db, reference_map)


async def _rewrite_versions(
    db: aiosqlite.Connection,
    *,
    affected_ids: set[str],
    target_triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> None:
    placeholders = ", ".join("?" for _ in affected_ids)
    async with db.execute(
        f"SELECT * FROM knowledge_graph_versions WHERE triple_id IN ({placeholders})",
        tuple(sorted(affected_ids)),
    ) as cursor:
        versions = await cursor.fetchall()
    for version in versions:
        scope_key = str(version["scope_key"] or "global")
        slot_key = await relationship_slot_key_on_connection(
            db,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
        )
        fingerprint = relationship_claim_fingerprint(
            slot_key_value=slot_key,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            scope_key_value=scope_key,
        )
        await db.execute(
            """
            UPDATE knowledge_graph_versions
            SET triple_id = ?, subject_id = ?, predicate = ?, object_id = ?,
                slot_key = ?, claim_fingerprint = ?
            WHERE version_id = ?
            """,
            (
                target_triple_id,
                subject_id,
                predicate,
                object_id,
                slot_key,
                fingerprint,
                version["version_id"],
            ),
        )
    await _rebuild_version_chain(db, target_triple_id)


async def _rebuild_version_chain(
    db: aiosqlite.Connection,
    triple_id: str,
) -> None:
    async with db.execute(
        """
        SELECT version_id FROM knowledge_graph_versions
        WHERE triple_id = ?
        ORDER BY created_at, version_id
        """,
        (triple_id,),
    ) as cursor:
        versions = await cursor.fetchall()
    previous: str | None = None
    for version in versions:
        await db.execute(
            "UPDATE knowledge_graph_versions SET previous_version_id = ? WHERE version_id = ?",
            (previous, version["version_id"]),
        )
        previous = str(version["version_id"])


async def _rewrite_current_edge_references(
    db: aiosqlite.Connection,
    id_map: Mapping[str, str],
) -> None:
    for old_id, new_id in id_map.items():
        await db.execute(
            "UPDATE knowledge_graph SET deprecated_by = ? WHERE deprecated_by = ?",
            (new_id, old_id),
        )
        await db.execute(
            "UPDATE knowledge_graph_versions SET authority_ref = ? WHERE authority_ref = ?",
            (new_id, old_id),
        )


async def _rewrite_conflict_effect_references(
    db: aiosqlite.Connection,
    id_map: Mapping[str, str],
) -> None:
    """Keep durable correction side effects aligned with graph identity merges."""
    for old_id, new_id in sorted(id_map.items()):
        await db.execute(
            """
            UPDATE memory_relationship_conflict_effects
            SET replacement_triple_id = ?
            WHERE replacement_triple_id = ?
            """,
            (new_id, old_id),
        )
        await db.execute(
            """
            UPDATE memory_relationship_conflict_effects
            SET pre_deprecated_by = ?
            WHERE pre_deprecated_by = ?
            """,
            (new_id, old_id),
        )
        async with db.execute(
            """
            SELECT * FROM memory_relationship_conflict_effects
            WHERE victim_triple_id = ?
            ORDER BY created_at, effect_id
            """,
            (old_id,),
        ) as cursor:
            source_effects = await cursor.fetchall()
        for source in source_effects:
            async with db.execute(
                """
                SELECT * FROM memory_relationship_conflict_effects
                WHERE correction_id = ? AND victim_triple_id = ?
                  AND effect_id != ?
                ORDER BY created_at, effect_id
                LIMIT 1
                """,
                (source["correction_id"], new_id, source["effect_id"]),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                await db.execute(
                    """
                    UPDATE memory_relationship_conflict_effects
                    SET victim_triple_id = ?
                    WHERE effect_id = ?
                    """,
                    (new_id, source["effect_id"]),
                )
                continue

            preimage = min(
                (source, existing),
                key=lambda row: (float(row["created_at"]), str(row["effect_id"])),
            )
            restored_values = [
                float(row["restored_at"])
                for row in (source, existing)
                if row["restored_at"] is not None
            ]
            restored_at = max(restored_values) if len(restored_values) == 2 else None
            await db.execute(
                """
                UPDATE memory_relationship_conflict_effects
                SET replacement_triple_id = ?, pre_status = ?,
                    pre_status_reason = ?, pre_deprecated_by = ?,
                    pre_deprecated_at = ?, pre_valid_to = ?, effective_at = ?,
                    created_at = ?, restored_at = ?
                WHERE effect_id = ?
                """,
                (
                    preimage["replacement_triple_id"],
                    preimage["pre_status"],
                    preimage["pre_status_reason"],
                    preimage["pre_deprecated_by"],
                    preimage["pre_deprecated_at"],
                    preimage["pre_valid_to"],
                    min(float(source["effective_at"]), float(existing["effective_at"])),
                    min(float(source["created_at"]), float(existing["created_at"])),
                    restored_at,
                    existing["effect_id"],
                ),
            )
            await db.execute(
                "DELETE FROM memory_relationship_conflict_effects WHERE effect_id = ?",
                (source["effect_id"],),
            )


async def _rewrite_dependencies(
    db: aiosqlite.Connection,
    id_map: Mapping[str, str],
) -> None:
    for old_id, new_id in id_map.items():
        async with db.execute(
            """
            SELECT * FROM memory_derivation_dependencies
            WHERE source_kind = 'edge' AND source_id = ?
            """,
            (old_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            await db.execute(
                """
                INSERT INTO memory_derivation_dependencies(
                    artifact_kind, artifact_id, source_kind, source_id,
                    subject_key, source_revision, created_at
                ) VALUES (?, ?, 'edge', ?, ?, ?, ?)
                ON CONFLICT(artifact_kind, artifact_id, source_kind, source_id)
                DO UPDATE SET
                    subject_key = excluded.subject_key,
                    source_revision = MAX(
                        memory_derivation_dependencies.source_revision,
                        excluded.source_revision
                    ),
                    created_at = MIN(
                        memory_derivation_dependencies.created_at,
                        excluded.created_at
                    )
                """,
                (
                    row["artifact_kind"],
                    row["artifact_id"],
                    new_id,
                    row["subject_key"],
                    row["source_revision"],
                    row["created_at"],
                ),
            )
        await db.execute(
            """
            DELETE FROM memory_derivation_dependencies
            WHERE source_kind = 'edge' AND source_id = ?
            """,
            (old_id,),
        )


_JSON_REFERENCE_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tom_snapshots": (
        "snapshot_id",
        (
            "preferences",
            "relationship_topology",
            "preferences_history",
            "relationship_history",
            "active_record_ids",
            "superseded_record_ids",
        ),
    ),
    "user_portrait_projection": (
        "user_id",
        (
            "world_json",
            "review_json",
            "recent_json",
            "prompt_summary_json",
            "evidence_refs_json",
            "source_counts_json",
        ),
    ),
    "user_profile_projection": (
        "user_id",
        (
            "communication_json",
            "identity_json",
            "preferences_json",
            "state_json",
            "field_sources_json",
            "field_conflicts_json",
        ),
    ),
}


async def _rewrite_materialized_json_references(
    db: aiosqlite.Connection,
    reference_map: Mapping[str, str],
) -> None:
    if not reference_map:
        return
    for table, (identity_column, columns) in _JSON_REFERENCE_COLUMNS.items():
        selected = ", ".join((identity_column, *columns))
        async with db.execute(f"SELECT {selected} FROM {table}") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            assignments: list[str] = []
            values: list[Any] = []
            for column in columns:
                raw = row[column]
                if raw is None:
                    continue
                try:
                    decoded = json.loads(str(raw))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                rewritten = _rewrite_reference_value(decoded, reference_map)
                if rewritten == decoded:
                    continue
                assignments.append(f"{column} = ?")
                values.append(
                    json.dumps(
                        rewritten,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            if assignments:
                await db.execute(
                    f"UPDATE {table} SET {', '.join(assignments)} WHERE {identity_column} = ?",
                    (*values, row[identity_column]),
                )


def _rewrite_reference_value(value: Any, id_map: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        replacement = id_map.get(value)
        if replacement is not None:
            return replacement
        for prefix in ("edge:", "relationship:"):
            if value.startswith(prefix):
                replacement = id_map.get(value[len(prefix) :])
                if replacement is not None:
                    return f"{prefix}{replacement}"
        return value
    if isinstance(value, list):
        return [_rewrite_reference_value(item, id_map) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _rewrite_reference_value(item, id_map) for key, item in value.items()}
    return value
