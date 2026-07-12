"""Persona registry backed by SQLite.

Provides stable UUID-based persona identity, CRUD operations,
and active-persona tracking.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from ..core.logger import get_logger
from ..core.sqlite import sqlite_connection_async
from ..utils.runtime import get_runtime_paths
from .loader import PersonalityConfig

logger = get_logger(__name__)

_CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS personas (
    persona_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    locale        TEXT NOT NULL DEFAULT 'en',
    config_json   TEXT NOT NULL,
    avatar_path   TEXT,
    group_name    TEXT NOT NULL DEFAULT 'general',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_builtin    INTEGER NOT NULL DEFAULT 0,
    seed_slug     TEXT,
    description   TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    deleted_at    REAL
);

CREATE TABLE IF NOT EXISTS persona_active (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    persona_id    TEXT NOT NULL REFERENCES personas(persona_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_personas_active_builtin_seed
ON personas(seed_slug)
WHERE is_builtin = 1 AND seed_slug IS NOT NULL AND deleted_at IS NULL;
"""


def _slugify(name: str) -> str:
    """Derive a URL-friendly slug from a display name."""
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", name).strip("_").lower()
    return slug[:60] or "unnamed"


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class PersonaRecord:
    """Full persona row."""

    persona_id: str
    name: str
    slug: str
    locale: str
    config: PersonalityConfig
    avatar_path: str
    group_name: str
    sort_order: int
    is_builtin: bool
    seed_slug: Optional[str]
    created_at: float
    updated_at: float
    deleted_at: float | None = None


@dataclass(frozen=True, slots=True)
class PersonaSummary:
    """Lightweight listing view."""

    persona_id: str
    name: str
    slug: str
    locale: str
    avatar_path: str
    group_name: str
    sort_order: int
    is_builtin: bool
    seed_slug: Optional[str] = None
    description: str = ""
    deleted_at: float | None = None


class PersonaRepository:
    """CRUD for the persona registry backed by SQLite."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(get_runtime_paths().persona_registry_db_path)

    # ---- lifecycle ----

    async def init(self) -> None:
        """Idempotent schema fallback. Alembic remains the canonical owner;
        this lets tests and fresh-disk callers work without a migration run."""
        async with sqlite_connection_async(self._db_path) as db:
            await db.executescript(_CREATE_SCHEMA)
            await db.commit()

    # ---- create ----

    async def create(
        self,
        config_json: str,
        *,
        locale: str = "en",
        slug: str | None = None,
        is_builtin: bool = False,
        seed_slug: str | None = None,
        persona_id: str | None = None,
    ) -> str:
        """Insert a new persona and return its persona_id."""
        data = json.loads(config_json)
        display_name = data.get("name", "") or "Unnamed"
        avatar = data.get("avatar", "")
        description = data.get("description", "")
        group = data.get("meta", {}).get("group", "general")
        order = data.get("meta", {}).get("order", 0)

        resolved_persona_id = persona_id or _new_id()
        final_slug = slug or _slugify(display_name)
        now = time.time()

        # Ensure slug uniqueness by appending a short suffix on conflict.
        async with sqlite_connection_async(self._db_path) as db:
            if persona_id is not None:
                await db.execute("BEGIN IMMEDIATE")
                existing = await db.execute_fetchall(
                    "SELECT deleted_at FROM personas WHERE persona_id = ?",
                    (persona_id,),
                )
                if existing:
                    if existing[0]["deleted_at"] is None:
                        await db.commit()
                        return persona_id
                    await db.rollback()
                    raise ValueError(f"Persona ID belongs to a deleted persona: {persona_id}")

            base_slug = final_slug
            attempt = 0
            while True:
                row = await db.execute_fetchall(
                    "SELECT 1 FROM personas WHERE slug = ?", (final_slug,)
                )
                if not row:
                    break
                attempt += 1
                final_slug = f"{base_slug}_{attempt}"

            await db.execute(
                """INSERT INTO personas
                   (persona_id, name, slug, locale, config_json, avatar_path,
                    group_name, sort_order, is_builtin, seed_slug, description,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resolved_persona_id, display_name, final_slug, locale, config_json,
                    avatar, group, order, int(is_builtin), seed_slug, description,
                    now, now,
                ),
            )
            await db.commit()

        logger.info(
            "Created persona %s (slug=%s, builtin=%s)",
            resolved_persona_id,
            final_slug,
            is_builtin,
        )
        return resolved_persona_id

    async def upsert_builtin(
        self,
        config_json: str,
        *,
        locale: str,
        seed_slug: str,
    ) -> tuple[str, bool]:
        """Atomically synchronize one builtin seed and report whether it was created."""
        data = json.loads(config_json)
        display_name = data.get("name", "") or "Unnamed"
        avatar = data.get("avatar", "")
        description = data.get("description", "")
        group = data.get("meta", {}).get("group", "general")
        order = data.get("meta", {}).get("order", 0)
        now = time.time()

        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            rows = await db.execute_fetchall(
                """SELECT persona_id FROM personas
                   WHERE is_builtin = 1 AND seed_slug = ? AND deleted_at IS NULL""",
                (seed_slug,),
            )
            if rows:
                persona_id = rows[0]["persona_id"]
                await db.execute(
                    """UPDATE personas
                       SET name = ?, locale = ?, config_json = ?, avatar_path = ?,
                           group_name = ?, sort_order = ?, description = ?, updated_at = ?
                       WHERE persona_id = ?""",
                    (
                        display_name,
                        locale,
                        config_json,
                        avatar,
                        group,
                        order,
                        description,
                        now,
                        persona_id,
                    ),
                )
                await db.commit()
                logger.debug("Synchronized builtin persona '%s' from seed", seed_slug)
                return persona_id, False

            final_slug = seed_slug
            attempt = 0
            while True:
                slug_rows = await db.execute_fetchall(
                    "SELECT 1 FROM personas WHERE slug = ?",
                    (final_slug,),
                )
                if not slug_rows:
                    break
                attempt += 1
                final_slug = f"{seed_slug}_{attempt}"

            persona_id = _new_id()
            await db.execute(
                """INSERT INTO personas
                   (persona_id, name, slug, locale, config_json, avatar_path,
                    group_name, sort_order, is_builtin, seed_slug, description,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                (
                    persona_id,
                    display_name,
                    final_slug,
                    locale,
                    config_json,
                    avatar,
                    group,
                    order,
                    seed_slug,
                    description,
                    now,
                    now,
                ),
            )
            await db.commit()

        logger.info(
            "Created builtin persona %s (seed_slug=%s)",
            persona_id,
            seed_slug,
        )
        return persona_id, True

    # ---- read ----

    async def get(self, persona_id: str, *, include_deleted: bool = False) -> PersonaRecord:
        """Load a persona by stable ID.  Raises KeyError if not found."""
        async with sqlite_connection_async(self._db_path) as db:
            sql = "SELECT * FROM personas WHERE persona_id = ?"
            params: tuple[object, ...] = (persona_id,)
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            row = await db.execute_fetchall(sql, params)
            if not row:
                raise KeyError(f"Persona not found: {persona_id}")
            return self._row_to_record(row[0])

    async def get_by_slug(self, slug: str, *, include_deleted: bool = False) -> PersonaRecord:
        """Load a persona by slug.  Raises KeyError if not found."""
        async with sqlite_connection_async(self._db_path) as db:
            sql = "SELECT * FROM personas WHERE slug = ?"
            params: tuple[object, ...] = (slug,)
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            row = await db.execute_fetchall(sql, params)
            if not row:
                raise KeyError(f"Persona slug not found: {slug}")
            return self._row_to_record(row[0])

    async def get_by_seed_slug(self, seed_slug: str, *, include_deleted: bool = False) -> PersonaRecord | None:
        """Load a builtin persona by its original seed filename stem."""
        async with sqlite_connection_async(self._db_path) as db:
            sql = "SELECT * FROM personas WHERE seed_slug = ? AND is_builtin = 1"
            params: tuple[object, ...] = (seed_slug,)
            if not include_deleted:
                sql += " AND deleted_at IS NULL"
            row = await db.execute_fetchall(sql, params)
            if not row:
                return None
            return self._row_to_record(row[0])

    async def list_all(self, *, include_deleted: bool = False) -> list[PersonaSummary]:
        """Return all personas in display order."""
        async with sqlite_connection_async(self._db_path) as db:
            sql = "SELECT * FROM personas"
            if not include_deleted:
                sql += " WHERE deleted_at IS NULL"
            sql += " ORDER BY sort_order, created_at"
            rows = await db.execute_fetchall(sql)
            return [self._row_to_summary(r) for r in rows]

    # ---- update ----

    async def update(
        self,
        persona_id: str,
        *,
        name: str | None = None,
        config_json: str | None = None,
        slug: str | None = None,
        avatar_path: str | None = None,
        group_name: str | None = None,
        sort_order: int | None = None,
    ) -> None:
        """Update mutable fields of an existing persona."""
        # When config_json changes, sync denormalized columns from it.
        description: str | None = None
        if config_json is not None:
            try:
                data = json.loads(config_json)
                meta = data.get("meta", {})
                if name is None:
                    name = data.get("name") or None
                if avatar_path is None:
                    avatar_path = data.get("avatar", "")
                description = data.get("description", "")
                if group_name is None and "group" in meta:
                    group_name = meta["group"]
                if sort_order is None and "order" in meta:
                    sort_order = meta["order"]
            except (json.JSONDecodeError, TypeError):
                pass

        sets: list[str] = []
        params: list[object] = []

        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if config_json is not None:
            sets.append("config_json = ?")
            params.append(config_json)
        if slug is not None:
            sets.append("slug = ?")
            params.append(slug)
        if avatar_path is not None:
            sets.append("avatar_path = ?")
            params.append(avatar_path)
        if group_name is not None:
            sets.append("group_name = ?")
            params.append(group_name)
        if sort_order is not None:
            sets.append("sort_order = ?")
            params.append(sort_order)
        if description is not None:
            sets.append("description = ?")
            params.append(description)

        if not sets:
            return

        sets.append("updated_at = ?")
        params.append(time.time())
        params.append(persona_id)

        async with sqlite_connection_async(self._db_path) as db:
            result = await db.execute(
                f"UPDATE personas SET {', '.join(sets)} WHERE persona_id = ? AND deleted_at IS NULL",
                tuple(params),
            )
            if result.rowcount == 0:
                raise KeyError(f"Persona not found: {persona_id}")
            await db.commit()

    # ---- delete ----

    async def delete(self, persona_id: str) -> None:
        """Soft-delete a persona.  Raises KeyError if not found."""
        async with sqlite_connection_async(self._db_path) as db:
            # Prevent deleting the active persona.
            active_rows = await db.execute_fetchall(
                "SELECT persona_id FROM persona_active WHERE persona_id = ?",
                (persona_id,),
            )
            if active_rows:
                raise ValueError("Cannot delete the currently active persona")
            now = time.time()
            result = await db.execute(
                "UPDATE personas SET deleted_at = ?, updated_at = ? WHERE persona_id = ? AND deleted_at IS NULL",
                (now, now, persona_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"Persona not found: {persona_id}")
            await db.commit()

        logger.info("Soft-deleted persona %s", persona_id)

    # ---- active persona ----

    async def get_active_id(self) -> str | None:
        """Return the active persona_id, or None if not set."""
        async with sqlite_connection_async(self._db_path) as db:
            rows = await db.execute_fetchall(
                "SELECT persona_id FROM persona_active WHERE id = 1"
            )
            if not rows:
                return None
            return rows[0]["persona_id"]

    async def set_active(self, persona_id: str) -> None:
        """Switch the active persona."""
        async with sqlite_connection_async(self._db_path) as db:
            # Verify persona exists.
            exists = await db.execute_fetchall(
                "SELECT 1 FROM personas WHERE persona_id = ? AND deleted_at IS NULL", (persona_id,)
            )
            if not exists:
                raise KeyError(f"Persona not found: {persona_id}")
            await db.execute(
                """INSERT INTO persona_active (id, persona_id) VALUES (1, ?)
                   ON CONFLICT(id) DO UPDATE SET persona_id = excluded.persona_id""",
                (persona_id,),
            )
            await db.commit()

        logger.info("Active persona set to %s", persona_id)

    async def clear_active(self) -> None:
        """Clear the active persona selection."""
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("DELETE FROM persona_active WHERE id = 1")
            await db.commit()

        logger.info("Cleared active persona")

    # ---- count ----

    async def count(self, *, include_deleted: bool = False) -> int:
        """Return total number of registered personas."""
        async with sqlite_connection_async(self._db_path) as db:
            sql = "SELECT COUNT(*) AS cnt FROM personas"
            if not include_deleted:
                sql += " WHERE deleted_at IS NULL"
            rows = await db.execute_fetchall(sql)
            return rows[0]["cnt"]

    # ---- helpers ----

    @staticmethod
    def _row_to_record(row) -> PersonaRecord:
        config_data = json.loads(row["config_json"])
        return PersonaRecord(
            persona_id=row["persona_id"],
            name=row["name"],
            slug=row["slug"],
            locale=row["locale"],
            config=PersonalityConfig.from_dict(config_data),
            avatar_path=row["avatar_path"] or "",
            group_name=row["group_name"],
            sort_order=row["sort_order"],
            is_builtin=bool(row["is_builtin"]),
            seed_slug=row["seed_slug"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"] if "deleted_at" in row.keys() else None,
        )

    @staticmethod
    def _row_to_summary(row) -> PersonaSummary:
        return PersonaSummary(
            persona_id=row["persona_id"],
            name=row["name"],
            slug=row["slug"],
            locale=row["locale"],
            avatar_path=row["avatar_path"] or "",
            group_name=row["group_name"],
            sort_order=row["sort_order"],
            is_builtin=bool(row["is_builtin"]),
            seed_slug=row["seed_slug"] if "seed_slug" in row.keys() else None,
            description=row["description"] if "description" in row.keys() else "",
            deleted_at=row["deleted_at"] if "deleted_at" in row.keys() else None,
        )
