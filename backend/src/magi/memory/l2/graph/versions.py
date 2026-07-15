"""Immutable relationship version records for correction-safe history."""

from __future__ import annotations

import time
import uuid
from typing import Any

import aiosqlite


async def append_knowledge_graph_version(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    correction_id: str | None = None,
    created_at: float | None = None,
) -> str:
    """Append the current edge state and return its immutable version id."""
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT * FROM knowledge_graph WHERE triple_id = ?",
        (triple_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Relationship does not exist: {triple_id}")
    async with db.execute(
        """
        SELECT version_id FROM knowledge_graph_versions
        WHERE triple_id = ?
        ORDER BY created_at DESC, version_id DESC
        LIMIT 1
        """,
        (triple_id,),
    ) as cursor:
        previous = await cursor.fetchone()

    version_id = f"kgv_{uuid.uuid4().hex}"
    await db.execute(
        """
        INSERT INTO knowledge_graph_versions(
            version_id, triple_id, previous_version_id, slot_key, claim_fingerprint,
            subject_id, subject_type, predicate, object_id, object_type, fact_kind,
            confidence, evidence_event_ids, evidence_text, status, valid_from, valid_to,
            scope_key, scope_json, authority_ref, correction_id, created_at,
            natural_summary, observation_count, first_observed_at, last_observed_at,
            last_confirmed_at, source_type, extraction_method, expires_at,
            evidence_class, edge_created_at, governance_complete
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1
        )
        """,
        (
            version_id,
            triple_id,
            str(previous["version_id"]) if previous is not None else None,
            str(row["slot_key"] or ""),
            str(row["claim_fingerprint"] or ""),
            str(row["subject_id"]),
            str(row["subject_type"]),
            str(row["predicate"]),
            str(row["object_id"]),
            str(row["object_type"]),
            str(row["fact_kind"]),
            float(row["confidence"]),
            str(row["evidence_event_ids"] or "[]"),
            str(row["evidence_text"] or ""),
            str(row["status"]),
            row["valid_from"],
            row["valid_to"],
            str(row["scope_key"] or "global"),
            str(row["scope_json"] or "{}"),
            row["authority_ref"],
            correction_id,
            float(created_at if created_at is not None else time.time()),
            str(row["natural_summary"] or ""),
            int(row["observation_count"] or 1),
            row["first_observed_at"],
            row["last_observed_at"],
            row["last_confirmed_at"],
            str(row["source_type"] or ""),
            str(row["extraction_method"] or ""),
            row["expires_at"],
            row["evidence_class"],
            row["created_at"],
        ),
    )
    return version_id


async def list_knowledge_graph_versions(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
) -> list[dict[str, Any]]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT * FROM knowledge_graph_versions
        WHERE triple_id = ?
        ORDER BY created_at, version_id
        """,
        (triple_id,),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


__all__ = ["append_knowledge_graph_version", "list_knowledge_graph_versions"]
