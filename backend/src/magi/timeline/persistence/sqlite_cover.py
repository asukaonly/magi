"""Persistent timeline cover preferences."""

from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from ..cover_preferences import (
    TimelineCoverPreference,
    TimelineCoverPreferenceMode,
    TimelineCoverAssetSource,
    TIMELINE_COVER_ASSET_SOURCES,
)

from ...core.sqlite import sqlite_connection_async


class SqliteTimelineCoverRepository:
    """Stores user-selected cover preferences for a timeline period."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())

    async def get_preference(
        self, *, scale: str, period_start: float, period_end: float
    ) -> TimelineCoverPreference | None:
        scope_key = self._scope_key(scale=scale, period_start=period_start, period_end=period_end)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT scope_key, scale, period_start, period_end, mode, asset_ref, source, updated_at
                FROM timeline_cover_preferences
                WHERE scope_key = ?
                """,
                (scope_key,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        mode, source = str(row["mode"]), str(row["source"])
        if mode not in {"asset", "hidden"} or source not in {
            "current_period",
            "custom_upload",
            "hidden",
        }:
            raise ValueError("Invalid stored timeline cover preference")
        return TimelineCoverPreference(
            scope_key=str(row["scope_key"]),
            scale=str(row["scale"]),
            period_start=float(row["period_start"]),
            period_end=float(row["period_end"]),
            mode=cast(TimelineCoverPreferenceMode, mode),
            asset_ref=row["asset_ref"],
            source=source,
            updated_at=float(row["updated_at"]),
        )

    async def set_preference(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        mode: TimelineCoverPreferenceMode,
        asset_ref: str | None = None,
        source: TimelineCoverAssetSource = "current_period",
    ) -> TimelineCoverPreference:
        if mode not in {"asset", "hidden"}:
            raise ValueError(f"Unsupported timeline cover mode: {mode}")
        if source not in TIMELINE_COVER_ASSET_SOURCES:
            raise ValueError(f"Unsupported timeline cover source: {source}")
        normalized_asset_ref = (asset_ref or "").strip()
        if mode == "asset" and not normalized_asset_ref:
            raise ValueError("Timeline cover asset mode requires asset_ref")
        persisted_source = source
        if mode == "hidden":
            normalized_asset_ref = ""
            persisted_source = "hidden"

        scope_key = self._scope_key(scale=scale, period_start=period_start, period_end=period_end)
        updated_at = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO timeline_cover_preferences (
                    scope_key, scale, period_start, period_end, mode, asset_ref, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    scale = excluded.scale,
                    period_start = excluded.period_start,
                    period_end = excluded.period_end,
                    mode = excluded.mode,
                    asset_ref = excluded.asset_ref,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    scope_key,
                    scale,
                    float(period_start),
                    float(period_end),
                    mode,
                    normalized_asset_ref or None,
                    persisted_source,
                    updated_at,
                ),
            )
            await db.commit()
        preference = await self.get_preference(
            scale=scale, period_start=period_start, period_end=period_end
        )
        if preference is None:
            raise RuntimeError("Failed to save timeline cover preference")
        return preference

    async def clear_preference(self, *, scale: str, period_start: float, period_end: float) -> bool:
        scope_key = self._scope_key(scale=scale, period_start=period_start, period_end=period_end)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM timeline_cover_preferences WHERE scope_key = ?",
                (scope_key,),
            )
            await db.commit()
            deleted = cursor.rowcount > 0
            await cursor.close()
        return deleted

    async def references_asset(self, asset_ref: str) -> bool:
        async with sqlite_connection_async(self.db_path) as db:
            rows = await db.execute_fetchall(
                """SELECT 1 FROM timeline_cover_preferences
                WHERE mode='asset' AND source IN ('current_period','custom_upload') AND asset_ref=? LIMIT 1""",
                (asset_ref,),
            )
            return bool(rows)

    @staticmethod
    def _scope_key(*, scale: str, period_start: float, period_end: float) -> str:
        return f"{scale}:{int(float(period_start))}:{int(float(period_end))}"
