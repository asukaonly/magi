"""Persistent timeline cover preferences."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Literal

from ..core.sqlite import sqlite_connection_async

TimelineCoverPreferenceMode = Literal["asset", "hidden"]
TimelineCoverAssetSource = Literal["current_period", "custom_upload"]
TIMELINE_COVER_ASSET_SOURCES = frozenset({"current_period", "custom_upload"})


class TimelineCoverPreferenceStore:
    """Stores user-selected cover preferences for a timeline period."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS timeline_cover_preferences (
                    scope_key TEXT PRIMARY KEY,
                    scale TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    mode TEXT NOT NULL,
                    asset_ref TEXT,
                    source TEXT NOT NULL DEFAULT 'current_period',
                    updated_at REAL NOT NULL
                )
                """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_timeline_cover_preferences_period
                ON timeline_cover_preferences(scale, period_start, period_end)
                """)
            await db.commit()
        self._initialized = True

    async def get_preference(
        self, *, scale: str, period_start: float, period_end: float
    ) -> dict[str, Any] | None:
        await self.initialize()
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
        return dict(row)

    async def set_preference(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        mode: TimelineCoverPreferenceMode,
        asset_ref: str | None = None,
        source: TimelineCoverAssetSource = "current_period",
    ) -> dict[str, Any]:
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

        await self.initialize()
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
        await self.initialize()
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

    @staticmethod
    def _scope_key(*, scale: str, period_start: float, period_end: float) -> str:
        return f"{scale}:{int(float(period_start))}:{int(float(period_end))}"
