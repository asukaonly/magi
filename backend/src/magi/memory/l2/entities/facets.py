"""Entity facet persistence helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import (
    normalize_source_event_ids,
    promote_source_event_entity_projection_candidates,
    source_event_entity_projection_block_ids,
    source_event_time_range_block_ids,
    source_event_time_range_block_predicate,
    source_event_tombstone_ids,
)
from ..storage.utils import (
    accumulate_confidence,
    max_evidence_event_ids,
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
        (
            facet_id,
            normalized_entity_id,
            normalized_entity_type,
            normalized_facet_name,
            normalized_facet_value,
        ) = self._facet_identity(
            entity_id=entity_id,
            entity_type=entity_type,
            facet_name=facet_name,
            facet_value=facet_value,
        )
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                active_event_ids = await _active_facet_source_event_ids(
                    db,
                    evidence_event_ids,
                    entity_id=normalized_entity_id,
                )
                if evidence_event_ids and not active_event_ids:
                    await db.commit()
                    return facet_id
                async with db.execute(
                    "SELECT confidence, evidence_event_ids, first_observed_at "
                    "FROM entity_facets WHERE facet_id = ?",
                    (facet_id,),
                ) as cursor:
                    existing = await cursor.fetchone()

                if existing:
                    stored_event_ids, provenance_valid = _decode_facet_source_event_ids(
                        existing["evidence_event_ids"]
                    )
                    retained_existing = await _active_facet_source_event_ids(
                        db,
                        stored_event_ids,
                        entity_id=normalized_entity_id,
                    )
                    await self._update_entity_facet(
                        db,
                        facet_id=facet_id,
                        existing_event_ids=list(retained_existing),
                        evidence_event_ids=list(active_event_ids),
                        existing_confidence=_retained_facet_confidence(
                            float(existing["confidence"]),
                            retained_count=len(retained_existing),
                            original_count=len(stored_event_ids),
                            provenance_valid=provenance_valid,
                        ),
                        confidence=confidence,
                        observed_at=observed_at,
                        source_type=source_type,
                        extraction_method=extraction_method,
                        now=now,
                    )
                else:
                    await self._insert_entity_facet(
                        db,
                        facet_id=facet_id,
                        normalized_entity_id=normalized_entity_id,
                        normalized_entity_type=normalized_entity_type,
                        normalized_facet_name=normalized_facet_name,
                        normalized_facet_value=normalized_facet_value,
                        evidence_event_ids=list(active_event_ids),
                        confidence=confidence,
                        observed_at=observed_at,
                        source_type=source_type,
                        extraction_method=extraction_method,
                        now=now,
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return facet_id

    @staticmethod
    def _facet_identity(
        *,
        entity_id: str,
        entity_type: str,
        facet_name: str,
        facet_value: str,
    ) -> tuple[str, str, str, str, str]:
        normalized_entity_type = normalize_store_entity_type(entity_type) or entity_type
        normalized_entity_id = (
            normalize_store_entity_ref(entity_id, normalized_entity_type) or entity_id
        )
        normalized_facet_name = str(facet_name or "").strip().casefold()
        normalized_facet_value = str(facet_value or "").strip().casefold()
        facet_uuid = uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"{normalized_entity_id}:{normalized_facet_name}:{normalized_facet_value}",
        )
        return (
            f"facet_{facet_uuid}",
            normalized_entity_id,
            normalized_entity_type,
            normalized_facet_name,
            normalized_facet_value,
        )

    @staticmethod
    def _merged_facet_evidence(
        existing_event_ids: List[str],
        evidence_event_ids: List[str],
    ) -> list[str]:
        merged_evidence = sorted(set(existing_event_ids).union(evidence_event_ids))
        evidence_cap = max_evidence_event_ids()
        if len(merged_evidence) > evidence_cap:
            return merged_evidence[-evidence_cap:]
        return merged_evidence

    async def _update_entity_facet(
        self,
        db: aiosqlite.Connection,
        *,
        facet_id: str,
        existing_event_ids: List[str],
        evidence_event_ids: List[str],
        existing_confidence: float,
        confidence: float,
        observed_at: float,
        source_type: str,
        extraction_method: str,
        now: float,
    ) -> None:
        merged_evidence = self._merged_facet_evidence(
            existing_event_ids,
            evidence_event_ids,
        )
        accumulated_confidence = accumulate_confidence(existing_confidence, float(confidence))
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

    async def _insert_entity_facet(
        self,
        db: aiosqlite.Connection,
        *,
        facet_id: str,
        normalized_entity_id: str,
        normalized_entity_type: str,
        normalized_facet_name: str,
        normalized_facet_value: str,
        evidence_event_ids: List[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        extraction_method: str,
        now: float,
    ) -> None:
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
        sql = f"""
            SELECT * FROM entity_facets AS facets
            WHERE facets.status = 'active'
              AND {_active_facet_predicate("facets")}
        """
        args: list[Any] = []
        if entity_id:
            sql += " AND entity_id = ?"
            args.append(entity_id)
        if facet_name:
            sql += " AND facet_name = ?"
            args.append(str(facet_name).strip().casefold())
        normalized_values = [
            str(item).strip().casefold() for item in (facet_values or []) if str(item).strip()
        ]
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
        normalized_values = [
            str(item).strip().casefold() for item in facet_values if str(item).strip()
        ]
        normalized_facet_name = str(facet_name or "").strip().casefold()
        if not normalized_entity_ids or not normalized_facet_name or not normalized_values:
            return []

        placeholders_entity = ", ".join("?" for _ in normalized_entity_ids)
        placeholders_value = ", ".join("?" for _ in normalized_values)
        sql = f"""
            SELECT facets.entity_id
            FROM entity_facets AS facets
            WHERE facets.entity_id IN ({placeholders_entity})
              AND facets.status = 'active'
              AND facets.facet_name = ?
              AND facets.facet_value IN ({placeholders_value})
              AND {_active_facet_predicate("facets")}
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


def _decode_facet_source_event_ids(value: Any) -> tuple[tuple[str, ...], bool]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return (), False
    if not isinstance(decoded, list):
        return (), False
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in decoded):
        return (), False
    return normalize_source_event_ids(decoded), True


def _retained_facet_confidence(
    confidence: float,
    *,
    retained_count: int,
    original_count: int,
    provenance_valid: bool,
) -> float:
    if not provenance_valid:
        return 0.0
    if original_count <= 0 or retained_count >= original_count:
        return confidence
    if retained_count <= 0:
        return 0.0
    bounded = min(max(confidence, 0.0), 1.0)
    return 1.0 - ((1.0 - bounded) ** (retained_count / original_count))


async def _active_facet_source_event_ids(
    db: aiosqlite.Connection,
    event_ids: List[str] | tuple[str, ...],
    *,
    entity_id: str,
) -> tuple[str, ...]:
    normalized = normalize_source_event_ids(event_ids)
    if not normalized:
        return ()
    blocked = await source_event_tombstone_ids(db, normalized)
    blocked.update(await source_event_time_range_block_ids(db, normalized))
    await promote_source_event_entity_projection_candidates(
        db,
        normalized,
        entity_ids=[entity_id],
    )
    blocked.update(
        await source_event_entity_projection_block_ids(
            db,
            normalized,
            entity_ids=[entity_id],
        )
    )
    return tuple(event_id for event_id in normalized if event_id not in blocked)


def _active_facet_predicate(alias: str) -> str:
    return f"""
        json_valid({alias}.evidence_event_ids)
        AND json_type({alias}.evidence_event_ids) = 'array'
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.evidence_event_ids) AS invalid_source
            WHERE invalid_source.type != 'text'
               OR TRIM(CAST(invalid_source.value AS TEXT)) = ''
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.evidence_event_ids) AS source
            JOIN memory_source_event_tombstones AS tombstones
              ON tombstones.event_id = TRIM(CAST(source.value AS TEXT))
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.evidence_event_ids) AS source
            JOIN memory_projection_blocks AS projection_blocks
              ON projection_blocks.event_id = TRIM(CAST(source.value AS TEXT))
             AND {source_event_time_range_block_predicate("projection_blocks")}
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.evidence_event_ids) AS source
            JOIN memory_projection_blocks AS entity_blocks
              ON entity_blocks.event_id = TRIM(CAST(source.value AS TEXT))
             AND entity_blocks.block_kind IN (
                    'entity_projection', 'entity_projection_candidate'
                 )
             AND entity_blocks.target_id = {alias}.entity_id
        )
    """
