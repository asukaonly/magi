"""Persistence for user profile projections."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from ..memory.derivation_revision import DerivationRevision
from .models import UserProfileProjection


class UserProfileProjectionRepository:
    """Read and write the materialized user profile projection."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def initialize(self) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_subject_revisions (
                    subject_key TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_profile_projection (
                    user_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    preferred_form_of_address TEXT NOT NULL DEFAULT '',
                    real_name TEXT NOT NULL DEFAULT '',
                    birth_date TEXT NOT NULL DEFAULT '',
                    birth_year INTEGER,
                    age_years INTEGER,
                    age_as_of TEXT NOT NULL DEFAULT '',
                    home_location TEXT NOT NULL DEFAULT '',
                    communication_json TEXT NOT NULL DEFAULT '{}',
                    identity_json TEXT NOT NULL DEFAULT '{}',
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    state_json TEXT NOT NULL DEFAULT '{}',
                    field_sources_json TEXT NOT NULL DEFAULT '{}',
                    field_conflicts_json TEXT NOT NULL DEFAULT '{}',
                    completeness_score REAL NOT NULL DEFAULT 0,
                    source_revision INTEGER NOT NULL DEFAULT 0,
                    refreshed_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_profile_projection_entity
                    ON user_profile_projection(entity_id);
                CREATE INDEX IF NOT EXISTS idx_user_profile_projection_refreshed
                    ON user_profile_projection(refreshed_at DESC);
                """
            )
            await db.commit()

    async def get(self, user_id: str) -> UserProfileProjection | None:
        await self.initialize()
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT projection.*
                FROM user_profile_projection AS projection
                LEFT JOIN memory_subject_revisions AS revision
                  ON revision.subject_key = projection.entity_id
                WHERE projection.user_id = ?
                  AND projection.source_revision = COALESCE(revision.revision, 0)
                """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_projection(row) if row is not None else None

    async def upsert(self, projection: UserProfileProjection) -> UserProfileProjection:
        await self.initialize()
        revision = DerivationRevision(
            subject_key=projection.entity_id,
            source_revision=projection.source_revision,
        )
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await revision.ensure_current_on_connection(db)
                async with db.execute(
                    "SELECT created_at FROM user_profile_projection WHERE user_id = ?",
                    (projection.user_id,),
                ) as cursor:
                    existing = await cursor.fetchone()
                now = time.time()
                created_at = float(existing[0]) if existing is not None else now
                refreshed_at = projection.refreshed_at or now
                updated = projection.model_copy(
                    update={
                        "created_at": created_at,
                        "updated_at": now,
                        "refreshed_at": refreshed_at,
                    }
                )
                payload = updated.model_dump()
                await db.execute(
                    """
                INSERT INTO user_profile_projection(
                    user_id, entity_id, display_name, preferred_form_of_address,
                    real_name, birth_date, birth_year, age_years, age_as_of,
                    home_location, communication_json,
                    identity_json, preferences_json, state_json, field_sources_json,
                    field_conflicts_json, completeness_score, source_revision,
                    refreshed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    display_name = excluded.display_name,
                    preferred_form_of_address = excluded.preferred_form_of_address,
                    real_name = excluded.real_name,
                    birth_date = excluded.birth_date,
                    birth_year = excluded.birth_year,
                    age_years = excluded.age_years,
                    age_as_of = excluded.age_as_of,
                    home_location = excluded.home_location,
                    communication_json = excluded.communication_json,
                    identity_json = excluded.identity_json,
                    preferences_json = excluded.preferences_json,
                    state_json = excluded.state_json,
                    field_sources_json = excluded.field_sources_json,
                    field_conflicts_json = excluded.field_conflicts_json,
                    completeness_score = excluded.completeness_score,
                    source_revision = excluded.source_revision,
                    refreshed_at = excluded.refreshed_at,
                    updated_at = excluded.updated_at
                """,
                    (
                        payload["user_id"],
                        payload["entity_id"],
                        payload["display_name"],
                        payload["preferred_form_of_address"],
                        payload["real_name"],
                        payload["birth_date"],
                        payload["birth_year"],
                        payload["age_years"],
                        payload["age_as_of"],
                        payload["home_location"],
                        json.dumps(payload["communication"], ensure_ascii=False, sort_keys=True),
                        json.dumps(payload["identity"], ensure_ascii=False, sort_keys=True),
                        json.dumps(payload["preferences"], ensure_ascii=False, sort_keys=True),
                        json.dumps(payload["state"], ensure_ascii=False, sort_keys=True),
                        json.dumps(payload["field_sources"], ensure_ascii=False, sort_keys=True),
                        json.dumps(payload["field_conflicts"], ensure_ascii=False, sort_keys=True),
                        payload["completeness_score"],
                        payload["source_revision"],
                        payload["refreshed_at"],
                        payload["created_at"],
                        payload["updated_at"],
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return updated

    @staticmethod
    def _json_field(row: aiosqlite.Row, key: str) -> dict[str, Any]:
        try:
            value = json.loads(str(row[key] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _row_to_projection(cls, row: aiosqlite.Row) -> UserProfileProjection:
        return UserProfileProjection(
            user_id=str(row["user_id"] or ""),
            entity_id=str(row["entity_id"] or ""),
            display_name=str(row["display_name"] or ""),
            preferred_form_of_address=str(row["preferred_form_of_address"] or ""),
            real_name=str(row["real_name"] or ""),
            birth_date=str(row["birth_date"] or ""),
            birth_year=row["birth_year"],
            age_years=row["age_years"],
            age_as_of=str(row["age_as_of"] or ""),
            home_location=str(row["home_location"] or ""),
            communication=cls._json_field(row, "communication_json"),
            identity=cls._json_field(row, "identity_json"),
            preferences=cls._json_field(row, "preferences_json"),
            state=cls._json_field(row, "state_json"),
            field_sources=cls._json_field(row, "field_sources_json"),
            field_conflicts=cls._json_field(row, "field_conflicts_json"),
            completeness_score=float(row["completeness_score"] or 0.0),
            source_revision=int(row["source_revision"] or 0),
            refreshed_at=float(row["refreshed_at"] or 0.0),
            created_at=float(row["created_at"] or 0.0),
            updated_at=float(row["updated_at"] or 0.0),
        )
