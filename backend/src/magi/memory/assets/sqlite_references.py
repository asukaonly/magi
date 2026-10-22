"""SQLite queries for visible memory owners of private image assets."""

from __future__ import annotations

from ...core.sqlite import sqlite_connection_async
from ..source_event_governance import source_occurrence_visible_predicate


class SqliteAssetReferenceRepository:
    def __init__(self, db_path: str) -> None:
        self._path = db_path

    async def is_visible_reference(self, asset_ref: str) -> bool:
        visibility = source_occurrence_visible_predicate(
            "entry.event_at", barrier_alias="manual_asset_forget_range"
        )
        async with sqlite_connection_async(self._path) as db:
            rows = await db.execute_fetchall(
                f"""SELECT 1 FROM manual_entries AS entry
                WHERE entry.deleted_at IS NULL AND entry.delete_requested_at IS NULL
                  AND (entry.pending_l1_event_id IS NULL OR entry.pending_l1_predecessor_event_id IS NULL)
                  AND EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(entry.attachments_json)
                    THEN entry.attachments_json ELSE '[]' END) attachment WHERE CAST(attachment.value AS TEXT)=?)
                  AND {visibility}
                UNION ALL SELECT 1 FROM experiences WHERE status!='invalidated' AND user_cover_asset_ref=?
                UNION ALL SELECT 1 FROM experience_drafts WHERE user_cover_asset_ref=? LIMIT 1""",
                (asset_ref, asset_ref, asset_ref),
            )
            return bool(rows)
