"""Persistence for product-facing user portrait projections."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from ..memory.clear_generation import ensure_memory_clear_state
from ..memory.derivation_revision import DerivationRevision
from .models import UserPortraitProjection


class UserPortraitProjectionRepository:
    """Read and write the materialized self-portrait projection."""

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
                CREATE TABLE IF NOT EXISTS memory_clear_state (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    generation INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_portrait_projection (
                    user_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'user',
                    world_json TEXT NOT NULL DEFAULT '{}',
                    review_json TEXT NOT NULL DEFAULT '{}',
                    recent_json TEXT NOT NULL DEFAULT '{}',
                    prompt_summary_json TEXT NOT NULL DEFAULT '[]',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    source_counts_json TEXT NOT NULL DEFAULT '{}',
                    generated_by TEXT NOT NULL DEFAULT 'rule',
                    input_assertion_highwater REAL NOT NULL DEFAULT 0,
                    input_claim_highwater REAL NOT NULL DEFAULT 0,
                    input_review_highwater REAL NOT NULL DEFAULT 0,
                    input_profile_highwater REAL NOT NULL DEFAULT 0,
                    source_revision INTEGER NOT NULL DEFAULT 0,
                    source_generation INTEGER NOT NULL DEFAULT 0,
                    generated_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_user_portrait_projection_entity
                    ON user_portrait_projection(entity_id, entity_type);
                CREATE INDEX IF NOT EXISTS idx_user_portrait_projection_updated
                    ON user_portrait_projection(updated_at DESC);
                """
            )
            await ensure_memory_clear_state(db)
            await db.commit()

    async def get(self, user_id: str) -> UserPortraitProjection | None:
        await self.initialize()
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT projection.*
                FROM user_portrait_projection AS projection
                LEFT JOIN memory_subject_revisions AS revision
                  ON revision.subject_key = projection.entity_id
                JOIN memory_clear_state AS clear_state
                  ON clear_state.singleton_id = 1
                WHERE projection.user_id = ?
                  AND projection.source_revision = COALESCE(revision.revision, 0)
                  AND projection.source_generation = clear_state.generation
                """,
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_projection(row)

    async def upsert(self, projection: UserPortraitProjection) -> UserPortraitProjection:
        await self.initialize()
        revision = DerivationRevision(
            subject_key=projection.entity_id,
            source_revision=projection.source_revision,
            clear_generation=projection.source_generation,
        )
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await revision.ensure_current_on_connection(db)
                async with db.execute(
                    "SELECT created_at FROM user_portrait_projection WHERE user_id = ?",
                    (projection.user_id,),
                ) as cursor:
                    existing = await cursor.fetchone()
                now = time.time()
                created_at = float(existing[0]) if existing is not None else now
                generated_at = projection.generated_at or now
                updated = projection.model_copy(
                    update={
                        "created_at": created_at,
                        "updated_at": now,
                        "generated_at": generated_at,
                    }
                )
                payload = updated.model_dump()
                await db.execute(
                    """
                INSERT INTO user_portrait_projection(
                    user_id, entity_id, entity_type,
                    world_json, review_json, recent_json, prompt_summary_json,
                    evidence_refs_json, source_counts_json, generated_by,
                    input_assertion_highwater, input_claim_highwater,
                    input_review_highwater, input_profile_highwater,
                    source_revision, source_generation, generated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    entity_type = excluded.entity_type,
                    world_json = excluded.world_json,
                    review_json = excluded.review_json,
                    recent_json = excluded.recent_json,
                    prompt_summary_json = excluded.prompt_summary_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    source_counts_json = excluded.source_counts_json,
                    generated_by = excluded.generated_by,
                    input_assertion_highwater = excluded.input_assertion_highwater,
                    input_claim_highwater = excluded.input_claim_highwater,
                    input_review_highwater = excluded.input_review_highwater,
                    input_profile_highwater = excluded.input_profile_highwater,
                    source_revision = excluded.source_revision,
                    source_generation = excluded.source_generation,
                    generated_at = excluded.generated_at,
                    updated_at = excluded.updated_at
                """,
                    (
                        payload["user_id"],
                        payload["entity_id"],
                        payload["entity_type"],
                        _dumps(payload["world"]),
                        _dumps(payload["review"]),
                        _dumps(payload["recent"]),
                        _dumps(payload["prompt_summary"]),
                        _dumps(payload["evidence_refs"]),
                        _dumps(payload["source_counts"]),
                        payload["generated_by"],
                        payload["input_assertion_highwater"],
                        payload["input_claim_highwater"],
                        payload["input_review_highwater"],
                        payload["input_profile_highwater"],
                        payload["source_revision"],
                        payload["source_generation"],
                        payload["generated_at"],
                        payload["created_at"],
                        payload["updated_at"],
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return updated

    @classmethod
    def _row_to_projection(cls, row: aiosqlite.Row) -> UserPortraitProjection:
        return UserPortraitProjection(
            user_id=str(row["user_id"]),
            entity_id=str(row["entity_id"]),
            entity_type=str(row["entity_type"]),
            world=cls._json_dict(row, "world_json"),
            review=cls._json_dict(row, "review_json"),
            recent=cls._json_dict(row, "recent_json"),
            prompt_summary=cls._json_list(row, "prompt_summary_json"),
            evidence_refs=cls._json_list(row, "evidence_refs_json"),
            source_counts={
                str(key): int(value)
                for key, value in cls._json_dict(row, "source_counts_json").items()
            },
            generated_by=str(row["generated_by"]),
            input_assertion_highwater=float(row["input_assertion_highwater"] or 0.0),
            input_claim_highwater=float(row["input_claim_highwater"] or 0.0),
            input_review_highwater=float(row["input_review_highwater"] or 0.0),
            input_profile_highwater=float(row["input_profile_highwater"] or 0.0),
            source_revision=int(row["source_revision"] or 0),
            source_generation=int(row["source_generation"] or 0),
            generated_at=float(row["generated_at"] or 0.0),
            created_at=float(row["created_at"] or 0.0),
            updated_at=float(row["updated_at"] or 0.0),
        )

    @staticmethod
    def _json_dict(row: aiosqlite.Row, key: str) -> dict[str, Any]:
        try:
            value = json.loads(str(row[key] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _json_list(row: aiosqlite.Row, key: str) -> list[str]:
        try:
            value = json.loads(str(row[key] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = ["UserPortraitProjectionRepository"]
