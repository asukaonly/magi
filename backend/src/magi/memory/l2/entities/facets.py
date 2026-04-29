"""Entity facet persistence helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..storage.utils import (
    MAX_EVIDENCE_EVENT_IDS,
    accumulate_confidence,
    normalize_store_entity_ref,
    normalize_store_entity_type,
)


class L2EntityFacetStoreMixin:
    """CRUD and filtering helpers for entity sidecar facets."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def upsert_entity_facet(
        self,
        *,
        entity_id: str,
        entity_type: str,
        facet_name: str,
        facet_value: str,
        evidence_event_ids: List[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        extraction_method: str = "structured_hint",
    ) -> str:
        """Insert or refresh a sidecar facet for one entity."""
        await self.initialize()
        normalized_entity_type = normalize_store_entity_type(entity_type) or entity_type
        normalized_entity_id = normalize_store_entity_ref(entity_id, normalized_entity_type) or entity_id
        normalized_facet_name = str(facet_name or "").strip().casefold()
        normalized_facet_value = str(facet_value or "").strip().casefold()
        now = time.time()
        facet_id = f"facet_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{normalized_entity_id}:{normalized_facet_name}:{normalized_facet_value}')}"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT confidence, evidence_event_ids, first_observed_at FROM entity_facets WHERE facet_id = ?",
                (facet_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                merged_evidence = sorted(set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids))
                if len(merged_evidence) > MAX_EVIDENCE_EVENT_IDS:
                    merged_evidence = merged_evidence[-MAX_EVIDENCE_EVENT_IDS:]
                accumulated_confidence = accumulate_confidence(float(existing["confidence"]), float(confidence))
                await db.execute(
                    """
                    UPDATE entity_facets
                    SET confidence = ?, evidence_event_ids = ?, last_observed_at = ?,
                        source_type = ?, extraction_method = ?, updated_at = ?
                    WHERE facet_id = ?
                    """,
                    (
                        accumulated_confidence,
                        json.dumps(merged_evidence, ensure_ascii=False),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        now,
                        facet_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO entity_facets(
                        facet_id, entity_id, entity_type, facet_name, facet_value,
                        confidence, evidence_event_ids, first_observed_at, last_observed_at,
                        source_type, extraction_method, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        facet_id,
                        normalized_entity_id,
                        normalized_entity_type,
                        normalized_facet_name,
                        normalized_facet_value,
                        float(confidence),
                        json.dumps(sorted(set(evidence_event_ids)), ensure_ascii=False),
                        float(observed_at),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        now,
                        now,
                    ),
                )
            await db.commit()
        return facet_id

    async def list_entity_facets(
        self,
        *,
        entity_id: str | None = None,
        facet_name: str | None = None,
        facet_values: List[str] | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List persisted entity facets."""
        await self.initialize()
        sql = "SELECT * FROM entity_facets WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            sql += " AND entity_id = ?"
            args.append(entity_id)
        if facet_name:
            sql += " AND facet_name = ?"
            args.append(str(facet_name).strip().casefold())
        normalized_values = [str(item).strip().casefold() for item in (facet_values or []) if str(item).strip()]
        if normalized_values:
            placeholders = ", ".join("?" for _ in normalized_values)
            sql += f" AND facet_value IN ({placeholders})"
            args.extend(normalized_values)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, int(limit)))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._facet_row_to_dict(row) for row in rows]

    async def filter_entity_ids_by_facet(
        self,
        *,
        entity_ids: List[str],
        facet_name: str,
        facet_values: List[str],
    ) -> List[str]:
        """Filter candidate entity IDs by matching sidecar facets."""
        await self.initialize()
        normalized_entity_ids = [str(item).strip() for item in entity_ids if str(item).strip()]
        normalized_values = [str(item).strip().casefold() for item in facet_values if str(item).strip()]
        normalized_facet_name = str(facet_name or "").strip().casefold()
        if not normalized_entity_ids or not normalized_facet_name or not normalized_values:
            return []

        placeholders_entity = ", ".join("?" for _ in normalized_entity_ids)
        placeholders_value = ", ".join("?" for _ in normalized_values)
        sql = f"""
            SELECT entity_id
            FROM entity_facets
            WHERE entity_id IN ({placeholders_entity})
              AND facet_name = ?
              AND facet_value IN ({placeholders_value})
            GROUP BY entity_id
        """
        args: list[Any] = [*normalized_entity_ids, normalized_facet_name, *normalized_values]
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        matched = {str(row["entity_id"]) for row in rows}
        return [entity_id for entity_id in normalized_entity_ids if entity_id in matched]

    def _facet_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "facet_name": str(row["facet_name"]),
            "facet_value": str(row["facet_value"]),
            "confidence": float(row["confidence"]),
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "source_type": row["source_type"],
            "extraction_method": row["extraction_method"],
        }

    async def _ensure_entity_facet_columns(self, db: aiosqlite.Connection) -> None:
        """Backfill additive columns for older entity_facets schemas."""
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(entity_facets)") as cursor:
            rows = await cursor.fetchall()
        columns = {str(row["name"]) for row in rows}
        if "status" not in columns:
            await db.execute(
                "ALTER TABLE entity_facets ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
            )
        if "privacy_scope" not in columns:
            await db.execute(
                "ALTER TABLE entity_facets ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private'"
            )
