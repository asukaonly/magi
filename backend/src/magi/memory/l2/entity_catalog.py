"""Entity catalog and alias-resolution helpers for L2 cognition."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .ontology import coerce_unknown_entity_type


def _normalize_alias(text: str) -> str:
    return text.strip().casefold()


def _normalize_catalog_entity_type(entity_type: Optional[str]) -> Optional[str]:
    if entity_type is None:
        return None
    return coerce_unknown_entity_type(entity_type)


def _normalize_entity_ref(entity_id: Optional[str], entity_type: Optional[str]) -> Optional[str]:
    if entity_id is None:
        return None
    text = entity_id.strip()
    if not text or not entity_type or ":" not in text:
        return text or None
    _, _, suffix = text.partition(":")
    if not suffix:
        return text
    return f"{entity_type}:{suffix}"


class L2EntityCatalog:
    """Stores canonical entities, aliases, and mention evidence."""

    def __init__(self, *, db_path: str = "~/.magi/data/memories/memory.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS entity_catalog (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entity_catalog_type ON entity_catalog(entity_type);

                CREATE TABLE IF NOT EXISTS entity_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, normalized_alias),
                    FOREIGN KEY(entity_id) REFERENCES entity_catalog(entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup ON entity_aliases(normalized_alias, confidence DESC);

                CREATE TABLE IF NOT EXISTS entity_mentions (
                    mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mention_text TEXT NOT NULL,
                    normalized_surface TEXT NOT NULL,
                    entity_type TEXT,
                    evidence_event_ids TEXT NOT NULL,
                    evidence_text TEXT,
                    resolved_entity_id TEXT,
                    confidence REAL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(resolved_entity_id) REFERENCES entity_catalog(entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions(resolved_entity_id);
                """
            )
            await db.commit()
        self._initialized = True

    async def upsert_entity(
        self,
        *,
        canonical_name: str,
        entity_type: str,
        entity_id: str,
    ) -> str:
        await self.initialize()
        normalized_entity_type = _normalize_catalog_entity_type(entity_type)
        normalized_entity_id = _normalize_entity_ref(entity_id, normalized_entity_type) or entity_id
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO entity_catalog(entity_id, canonical_name, entity_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    entity_type = excluded.entity_type,
                    updated_at = excluded.updated_at
                """,
                (normalized_entity_id, canonical_name, normalized_entity_type, now, now),
            )
            await db.commit()
        return normalized_entity_id

    async def add_alias(self, *, entity_id: str, alias_text: str, confidence: float = 1.0) -> None:
        await self.initialize()
        now = time.time()
        normalized_alias = _normalize_alias(alias_text)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO entity_aliases(entity_id, alias_text, normalized_alias, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                    alias_text = excluded.alias_text,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (entity_id, alias_text, normalized_alias, float(confidence), now, now),
            )
            await db.commit()

    async def resolve_alias(
        self,
        alias_text: str,
        *,
        entity_type: Optional[str] = None,
        min_confidence: float = 0.8,
    ) -> dict[str, Any]:
        await self.initialize()
        normalized_alias = _normalize_alias(alias_text)

        query = """
            SELECT c.entity_id, c.entity_type, a.confidence
            FROM entity_aliases a
            JOIN entity_catalog c ON c.entity_id = a.entity_id
            WHERE a.normalized_alias = ?
        """
        args: list[Any] = [normalized_alias]
        normalized_entity_type = _normalize_catalog_entity_type(entity_type)
        if normalized_entity_type:
            query += " AND c.entity_type = ?"
            args.append(normalized_entity_type)
        query += " ORDER BY a.confidence DESC, c.entity_id ASC"

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return {
                "decision": "unresolved",
                "entity_id": None,
                "candidate_count": 0,
                "matched_confidence": None,
            }

        top = rows[0]
        if len(rows) > 1 and float(rows[1]["confidence"]) >= min_confidence:
            return {
                "decision": "unresolved",
                "entity_id": None,
                "candidate_count": len(rows),
                "matched_confidence": float(top["confidence"]),
            }

        if float(top["confidence"]) < min_confidence:
            return {
                "decision": "unresolved",
                "entity_id": None,
                "candidate_count": len(rows),
                "matched_confidence": float(top["confidence"]),
            }

        return {
            "decision": "match",
            "entity_id": str(top["entity_id"]),
            "candidate_count": len(rows),
            "matched_confidence": float(top["confidence"]),
        }

    async def record_mention(
        self,
        *,
        mention_text: str,
        normalized_surface: str,
        entity_type: Optional[str],
        evidence_event_ids: list[str],
        evidence_text: Optional[str],
        resolved_entity_id: Optional[str],
        confidence: Optional[float],
    ) -> int:
        await self.initialize()
        normalized_entity_type = _normalize_catalog_entity_type(entity_type)
        normalized_resolved_entity_id = _normalize_entity_ref(resolved_entity_id, normalized_entity_type)
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO entity_mentions(
                    mention_text,
                    normalized_surface,
                    entity_type,
                    evidence_event_ids,
                    evidence_text,
                    resolved_entity_id,
                    confidence,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mention_text,
                    normalized_surface,
                    normalized_entity_type,
                    json.dumps(evidence_event_ids, ensure_ascii=False),
                    evidence_text,
                    normalized_resolved_entity_id,
                    float(confidence) if confidence is not None else None,
                    now,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def get_mention(self, mention_id: int) -> Optional[dict[str, Any]]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT mention_id, mention_text, normalized_surface, entity_type,
                       evidence_event_ids, evidence_text, resolved_entity_id, confidence
                FROM entity_mentions
                WHERE mention_id = ?
                """,
                (mention_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "mention_id": int(row["mention_id"]),
            "mention_text": str(row["mention_text"]),
            "normalized_surface": str(row["normalized_surface"]),
            "entity_type": row["entity_type"],
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "evidence_text": row["evidence_text"],
            "resolved_entity_id": row["resolved_entity_id"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
        }

    async def list_entities(self, *, limit: int = 100) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._list_entities(limit=limit)

    async def list_mentions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT mention_id, mention_text, normalized_surface, entity_type,
                       evidence_event_ids, evidence_text, resolved_entity_id, confidence
                FROM entity_mentions
                ORDER BY mention_id DESC
                LIMIT ?
                """,
                (int(limit),),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "mention_id": int(row["mention_id"]),
                "mention_text": str(row["mention_text"]),
                "normalized_surface": str(row["normalized_surface"]),
                "entity_type": row["entity_type"],
                "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
                "evidence_text": row["evidence_text"],
                "resolved_entity_id": row["resolved_entity_id"],
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            }
            for row in rows
        ]

    async def list_entities_by_type(self, *, entity_type: str, limit: int = 100) -> list[dict[str, Any]]:
        await self.initialize()
        return await self._list_entities(limit=limit, entity_type=_normalize_catalog_entity_type(entity_type))

    async def clear(self) -> int:
        """Delete all catalog entities, aliases, and mention evidence."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM entity_catalog) +
                    (SELECT COUNT(*) FROM entity_mentions)
                """
            ) as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.executescript(
                """
                DELETE FROM entity_mentions;
                DELETE FROM entity_aliases;
                DELETE FROM entity_catalog;
                """
            )
            await db.commit()
        return count

    async def _list_entities(
        self,
        *,
        limit: int,
        entity_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT entity_id, canonical_name, entity_type
            FROM entity_catalog
        """
        args: list[Any] = []
        if entity_type:
            query += " WHERE entity_type = ?"
            args.append(entity_type)
        query += " ORDER BY entity_id ASC LIMIT ?"
        args.append(int(limit))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                query,
                tuple(args),
            ) as cursor:
                entities = await cursor.fetchall()

            async with db.execute(
                """
                SELECT entity_id, alias_text
                FROM entity_aliases
                ORDER BY normalized_alias ASC
                """
            ) as cursor:
                alias_rows = await cursor.fetchall()

        aliases_by_entity: dict[str, list[str]] = {}
        for row in alias_rows:
            aliases_by_entity.setdefault(str(row["entity_id"]), []).append(str(row["alias_text"]))

        return [
            {
                "entity_id": str(row["entity_id"]),
                "canonical_name": str(row["canonical_name"]),
                "entity_type": str(row["entity_type"]),
                "aliases": aliases_by_entity.get(str(row["entity_id"]), []),
            }
            for row in entities
        ]


__all__ = ["L2EntityCatalog"]
