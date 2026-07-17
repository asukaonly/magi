"""Idempotent cross-layer cleanup for persisted source references."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ...core.sqlite import sqlite_connection_async
from ..l3.daily_mood.store import DailyMoodAggregateStore
from ..source_event_governance import normalize_source_event_ids

_ARCHIVE_REFERENCE_PAGE_SIZE = 500
_PROJECTION_REFERENCE_PAGE_SIZE = 500


class ForgetLayerCleanup:
    """Invoke each layer after durable barriers have already been committed."""

    def __init__(self, host: Any) -> None:
        self._host = host

    async def cleanup_references(
        self,
        references: tuple[str, ...] | list[str],
        *,
        reason: str,
        prepared_entity_ids: tuple[str, ...] = (),
        entity_refresh_started_at: float | None = None,
    ) -> None:
        normalized = normalize_source_event_ids(references)
        if not normalized:
            return
        host = self._host
        refresh_started_at = float(entity_refresh_started_at or time.time())

        if host.l2 is not None:
            await host.l2.forget_source_events(
                normalized,
                reason=reason,
                persist_barrier=False,
            )
        await DailyMoodAggregateStore(host.memory_db_path).forget_source_events(normalized)
        if host.l2_entity_catalog is not None:
            await host.l2_entity_catalog.finish_source_event_forgetting(
                prepared_entity_ids,
                updated_after=refresh_started_at,
            )
        if host.l3 is not None:
            await host.l3.forget_source_events(list(normalized))
        if host.l0 is not None:
            forget_active_entities = getattr(host.l0, "forget_active_entities", None)
            if callable(forget_active_entities):
                await forget_active_entities(normalized)
            await host.l0.forget_temporary_tactics(normalized)
        if host.l4 is not None:
            await host.l4.forget_source_events(
                normalized,
                reason=reason,
                persist_barrier=False,
            )

    async def cleanup_operation_archives(self, operation_id: str) -> dict[str, int]:
        """Remove every archived row governed by one durable forget operation."""
        host = self._host
        return await _forget_operation_archives(
            getattr(host, "_archive_dir", None),
            memory_db_path=host.memory_db_path,
            operation_id=operation_id,
        )

    async def cleanup_entity_projection_sources(
        self,
        operation_id: str,
        *,
        reason: str,
    ) -> dict[str, int]:
        """Remove L3/L4 derivatives built from the deleted entity's old evidence."""
        removed = {"l3_summaries": 0, "l4_skills": 0}
        after_event_id = ""
        while True:
            async with sqlite_connection_async(self._host.memory_db_path) as db:
                async with db.execute(
                    """
                    SELECT DISTINCT event_id
                    FROM memory_projection_blocks
                    WHERE operation_id = ? AND block_kind = 'entity_projection'
                      AND event_id > ?
                    ORDER BY event_id
                    LIMIT ?
                    """,
                    (
                        str(operation_id),
                        after_event_id,
                        _PROJECTION_REFERENCE_PAGE_SIZE,
                    ),
                ) as cursor:
                    event_ids = tuple(str(row[0]) for row in await cursor.fetchall())
            if not event_ids:
                return removed
            if self._host.l3 is not None:
                removed["l3_summaries"] += int(
                    await self._host.l3.forget_source_events(list(event_ids))
                )
            if self._host.l4 is not None:
                removed["l4_skills"] += int(
                    await self._host.l4.forget_source_events(
                        event_ids,
                        reason=reason,
                        persist_barrier=False,
                    )
                )
            after_event_id = event_ids[-1]


async def _forget_operation_archives(
    archive_dir: Path | str | None,
    *,
    memory_db_path: Path | str,
    operation_id: str,
) -> dict[str, int]:
    """Remove archived rows once per archive database for one operation."""
    removed = {"archived_l1_events": 0, "archived_l3_summaries": 0}
    if archive_dir is None:
        return removed
    root = Path(archive_dir)
    normalized_operation_id = str(operation_id or "").strip()
    if not root.is_dir() or not normalized_operation_id:
        return removed

    archive_paths = sorted(root.glob("*.db"))
    if not archive_paths:
        return removed

    async with sqlite_connection_async(memory_db_path) as source_db:
        first_l1_page = await _operation_l1_reference_page(
            source_db,
            operation_id=normalized_operation_id,
            after_reference="",
        )
        first_derivative_page = await _operation_derivative_reference_page(
            source_db,
            operation_id=normalized_operation_id,
            after_reference="",
        )
        if not first_l1_page and not first_derivative_page:
            return removed

        for archive_path in archive_paths:
            async with sqlite_connection_async(archive_path) as archive_db:
                await archive_db.execute("BEGIN IMMEDIATE")
                try:
                    async with archive_db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ) as cursor:
                        tables = {str(row[0]) for row in await cursor.fetchall()}

                    l1_references = first_l1_page
                    while l1_references:
                        references_json = json.dumps(
                            l1_references,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        if "archived_l1_events" in tables:
                            cursor = await archive_db.execute(
                                """
                                DELETE FROM archived_l1_events
                                WHERE event_id IN (
                                    SELECT CAST(value AS TEXT) FROM json_each(?)
                                )
                                """,
                                (references_json,),
                            )
                            removed["archived_l1_events"] += max(
                                int(cursor.rowcount or 0),
                                0,
                            )

                        l1_references = await _operation_l1_reference_page(
                            source_db,
                            operation_id=normalized_operation_id,
                            after_reference=l1_references[-1],
                        )

                    derivative_references = first_derivative_page
                    while derivative_references:
                        references_json = json.dumps(
                            derivative_references,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        if "archived_l3_summaries" in tables:
                            cursor = await archive_db.execute(
                                """
                                DELETE FROM archived_l3_summaries
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM json_each(
                                        CASE
                                            WHEN json_valid(payload_json)
                                                THEN payload_json
                                            ELSE '{}'
                                        END,
                                        '$.summary.source_event_ids'
                                    ) AS source
                                    WHERE CAST(source.value AS TEXT) IN (
                                        SELECT CAST(value AS TEXT) FROM json_each(?)
                                    )
                                ) OR EXISTS (
                                    SELECT 1
                                    FROM json_each(
                                        CASE
                                            WHEN json_valid(payload_json)
                                                THEN payload_json
                                            ELSE '{}'
                                        END,
                                        '$.event_links'
                                    ) AS link
                                    WHERE CAST(
                                        json_extract(
                                            CASE
                                                WHEN json_valid(link.value)
                                                    THEN link.value
                                                ELSE '{}'
                                            END,
                                            '$.event_id'
                                        ) AS TEXT
                                    )
                                        IN (
                                            SELECT CAST(value AS TEXT) FROM json_each(?)
                                        )
                                )
                                """,
                                (references_json, references_json),
                            )
                            removed["archived_l3_summaries"] += max(
                                int(cursor.rowcount or 0),
                                0,
                            )

                        derivative_references = await _operation_derivative_reference_page(
                            source_db,
                            operation_id=normalized_operation_id,
                            after_reference=derivative_references[-1],
                        )
                    await archive_db.commit()
                except BaseException:
                    await archive_db.rollback()
                    raise
    return removed


async def _operation_l1_reference_page(
    db: Any,
    *,
    operation_id: str,
    after_reference: str,
) -> tuple[str, ...]:
    """Read raw events that this operation is authorized to delete from L1."""
    async with db.execute(
        """
        SELECT source_ref
        FROM (
            SELECT event_id AS source_ref
            FROM memory_forget_operation_events
            WHERE operation_id = ?
            UNION
            SELECT source_ref
            FROM memory_forget_operation_refs
            WHERE operation_id = ? AND ref_type = 'audit_event'
        )
        WHERE source_ref > ?
        ORDER BY source_ref
        LIMIT ?
        """,
        (
            operation_id,
            operation_id,
            str(after_reference),
            _ARCHIVE_REFERENCE_PAGE_SIZE,
        ),
    ) as cursor:
        return normalize_source_event_ids(str(row[0]) for row in await cursor.fetchall())


async def _operation_derivative_reference_page(
    db: Any,
    *,
    operation_id: str,
    after_reference: str,
) -> tuple[str, ...]:
    """Read one stable page of references governing derived archive rows."""
    async with db.execute(
        """
        SELECT source_ref
        FROM (
            SELECT source_ref
            FROM memory_forget_operation_refs
            WHERE operation_id = ? AND ref_role IN ('barrier', 'cleanup')
            UNION
            SELECT event_id AS source_ref
            FROM memory_forget_operation_events
            WHERE operation_id = ?
            UNION
            SELECT event_id AS source_ref
            FROM memory_projection_blocks
            WHERE operation_id = ?
              AND block_kind != 'entity_projection_candidate'
        )
        WHERE source_ref > ?
        ORDER BY source_ref
        LIMIT ?
        """,
        (
            operation_id,
            operation_id,
            operation_id,
            str(after_reference),
            _ARCHIVE_REFERENCE_PAGE_SIZE,
        ),
    ) as cursor:
        return normalize_source_event_ids(str(row[0]) for row in await cursor.fetchall())


__all__ = ["ForgetLayerCleanup"]
