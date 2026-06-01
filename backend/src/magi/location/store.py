"""SQLite-backed storage for location samples + reverse-geocode cache."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .models import LocationSample


class LocationSampleStore:
    """CRUD + window queries over the ``location_samples`` table."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())

    async def insert(self, sample: LocationSample) -> str:
        """Persist a sample. Assigns a UUID if ``sample_id`` is empty."""
        sample_id = sample.sample_id or f"loc-{uuid.uuid4().hex[:12]}"
        created_at = sample.created_at or time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO location_samples
                    (sample_id, source, sampled_at, lat, lng, accuracy_m,
                     city, region, country, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample_id,
                    sample.source,
                    float(sample.sampled_at),
                    sample.lat,
                    sample.lng,
                    sample.accuracy_m,
                    sample.city,
                    sample.region,
                    sample.country,
                    json.dumps(sample.metadata or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            await db.commit()
        return sample_id

    async def query_window(
        self,
        *,
        time_start: float,
        time_end: float,
        source: Optional[str] = None,
        limit: int = 500,
    ) -> list[LocationSample]:
        """Return samples whose ``sampled_at`` falls in [time_start, time_end].

        Optionally filter to a single source. Results are ordered by
        ``sampled_at`` ascending so callers iterating for weighted
        aggregation read events chronologically.
        """
        sql = (
            "SELECT sample_id, source, sampled_at, lat, lng, accuracy_m, "
            "city, region, country, metadata_json, created_at "
            "FROM location_samples WHERE sampled_at >= ? AND sampled_at <= ?"
        )
        args: list = [float(time_start), float(time_end)]
        if source:
            sql += " AND source = ?"
            args.append(source)
        sql += " ORDER BY sampled_at ASC LIMIT ?"
        args.append(int(limit))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_sample(row) for row in rows]

    async def latest(
        self, *, source: Optional[str] = None, before: Optional[float] = None,
    ) -> Optional[LocationSample]:
        """Return the most recent sample (optionally filtered by source / cutoff)."""
        sql = (
            "SELECT sample_id, source, sampled_at, lat, lng, accuracy_m, "
            "city, region, country, metadata_json, created_at "
            "FROM location_samples WHERE 1=1"
        )
        args: list = []
        if source:
            sql += " AND source = ?"
            args.append(source)
        if before is not None:
            sql += " AND sampled_at <= ?"
            args.append(float(before))
        sql += " ORDER BY sampled_at DESC LIMIT 1"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return self._row_to_sample(row) if row else None

    @staticmethod
    def _row_to_sample(row) -> LocationSample:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (ValueError, TypeError):
            metadata = {}
        return LocationSample(
            sample_id=str(row["sample_id"]),
            source=str(row["source"]),
            sampled_at=float(row["sampled_at"]),
            lat=row["lat"],
            lng=row["lng"],
            accuracy_m=row["accuracy_m"],
            city=row["city"],
            region=row["region"],
            country=row["country"],
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=float(row["created_at"] or 0.0),
        )


class PlaceGeocodeCache:
    """Reverse-geocode cache keyed by a 4-decimal-degree (~10m) grid.

    Nominatim allows 1 req/sec — without this cache the resolver would
    chew through rate limits on repeated lookups of the same coordinate
    cluster. Grid quantization also helps with photo EXIF jitter where
    consecutive photos at the same location report slightly different lat/lng.
    """

    GRID_DECIMALS = 4

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())

    @classmethod
    def grid_key(cls, lat: float, lng: float) -> str:
        return f"{round(lat, cls.GRID_DECIMALS)},{round(lng, cls.GRID_DECIMALS)}"

    async def lookup(
        self, lat: float, lng: float,
    ) -> Optional[dict]:
        key = self.grid_key(lat, lng)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT city, region, country, poi_name, cached_at "
                "FROM place_geocode_cache WHERE grid_key = ?",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return {
            "city": row["city"],
            "region": row["region"],
            "country": row["country"],
            "poi_name": row["poi_name"],
            "cached_at": float(row["cached_at"] or 0.0),
        }

    async def put(
        self,
        lat: float,
        lng: float,
        *,
        city: Optional[str] = None,
        region: Optional[str] = None,
        country: Optional[str] = None,
        poi_name: Optional[str] = None,
    ) -> None:
        key = self.grid_key(lat, lng)
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO place_geocode_cache(grid_key, city, region, country, poi_name, cached_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(grid_key) DO UPDATE SET
                    city = excluded.city,
                    region = excluded.region,
                    country = excluded.country,
                    poi_name = excluded.poi_name,
                    cached_at = excluded.cached_at
                """,
                (key, city, region, country, poi_name, time.time()),
            )
            await db.commit()
