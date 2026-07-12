"""Read and query helpers for the L2 entity catalog."""

from __future__ import annotations

import json
from typing import Any, Optional, Protocol, cast

import aiosqlite

from .....core.sqlite import sqlite_connection_async
from ....sql_search import build_like_search_clause
from .embeddings import EMBEDDING_STATUS_DISABLED
from ...ontology import coerce_unknown_entity_type


def _normalize_alias(text: str) -> str:
    return text.strip().casefold()


def _normalize_catalog_entity_type(entity_type: Optional[str]) -> Optional[str]:
    if entity_type is None:
        return None
    return cast(str, coerce_unknown_entity_type(entity_type))


class _EntityCatalogQueryHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def search_entities_semantic(
        self,
        query_text: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...


class L2EntityCatalogQueryMixin:
    """Read, listing, and natural-language entity query behavior."""

    async def count_entities(self, *, query: str | None = None) -> int:
        """Count all entities in the catalog."""
        host = self._query_host()
        await host.initialize()
        sql = "SELECT COUNT(*) FROM entity_catalog AS ec WHERE 1=1"
        search_sql, search_args = self._entity_search_clause(query)
        sql += search_sql
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(sql, tuple(search_args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def count_mentions(self) -> int:
        """Count all entity mentions."""
        host = self._query_host()
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM entity_mentions") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_entities(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        entity_ids: list[str] | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        host = self._query_host()
        await host.initialize()
        if entity_ids is not None and not entity_ids:
            return []
        return await self._list_entities(
            limit=limit,
            offset=offset,
            entity_ids=entity_ids,
            query=query,
        )

    async def list_mentions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        host = self._query_host()
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT mention_id, mention_text, normalized_surface, entity_type,
                       evidence_event_ids, evidence_text, resolved_entity_id, confidence
                FROM entity_mentions
                ORDER BY mention_id DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
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

    async def list_entities_by_type(
        self, *, entity_type: str, limit: int = 100, order_by_recency: bool = False
    ) -> list[dict[str, Any]]:
        host = self._query_host()
        await host.initialize()
        return await self._list_entities(
            limit=limit,
            entity_type=_normalize_catalog_entity_type(entity_type),
            order_by_recency=order_by_recency,
        )

    async def find_resolution_candidates(
        self,
        mention_text: str,
        *,
        entity_type: str | None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return candidate entities for LLM disambiguation.

        Candidate recall is ordered by precision first: exact/text and semantic
        matches for the requested type, then a recency fallback so small or
        unembedded catalogs still have useful candidates.
        """
        host = self._query_host()
        await host.initialize()
        query_text = str(mention_text or "").strip()
        normalized_type = _normalize_catalog_entity_type(entity_type)
        normalized_limit = max(1, int(limit))
        if not query_text or not normalized_type:
            return []

        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _append(items: list[dict[str, Any]]) -> None:
            for item in items:
                entity_id = str(item.get("entity_id") or "").strip()
                if not entity_id or entity_id in seen_ids:
                    continue
                if str(item.get("entity_type") or "").strip() != normalized_type:
                    continue
                seen_ids.add(entity_id)
                candidates.append(item)
                if len(candidates) >= normalized_limit:
                    break

        text_and_semantic_matches = await self.resolve_query_entities(
            query_text,
            limit=normalized_limit,
            entity_types=[normalized_type],
        )
        _append(text_and_semantic_matches)

        if len(candidates) < normalized_limit:
            recent_fallback = await self.list_entities_by_type(
                entity_type=normalized_type,
                limit=normalized_limit,
                order_by_recency=True,
            )
            _append(recent_fallback)

        return candidates[:normalized_limit]

    async def find_by_canonical_name(
        self,
        canonical_name: str,
        *,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return catalog entries matching *canonical_name* (case-insensitive)."""
        host = self._query_host()
        await host.initialize()
        normalized_name = canonical_name.strip().casefold()
        if not normalized_name:
            return []
        query = """
            SELECT entity_id, canonical_name, entity_type
            FROM entity_catalog
            WHERE LOWER(canonical_name) = ?
        """
        args: list[Any] = [normalized_name]
        if entity_type:
            normalized_type = _normalize_catalog_entity_type(entity_type)
            query += " AND entity_type = ?"
            args.append(normalized_type)
        query += " ORDER BY updated_at DESC LIMIT 10"
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [
            {
                "entity_id": str(row["entity_id"]),
                "canonical_name": str(row["canonical_name"]),
                "entity_type": str(row["entity_type"]),
            }
            for row in rows
        ]

    async def resolve_query_entities(
        self,
        query_text: str,
        *,
        limit: int = 10,
        entity_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve natural-language query text into matching canonical entities.

        Uses text substring matching, supplemented by vector similarity when
        an embedding model is available and L2 vectors are enabled.
        """
        host = self._query_host()
        await host.initialize()
        normalized_query = _normalize_alias(query_text)
        if not normalized_query:
            return []

        type_filter = {
            normalized
            for item in (entity_types or [])
            if (normalized := _normalize_catalog_entity_type(item))
        }

        matches = await self._search_entities_by_substring(
            normalized_query,
            type_filter=type_filter or None,
        )

        semantic_hits = await host.search_entities_semantic(query_text, limit=limit)
        text_match_ids = {str(m["entity_id"]) for m in matches}
        for hit in semantic_hits:
            entity_id = str(hit["entity_id"])
            if entity_id in text_match_ids:
                continue
            entity_type = str(hit.get("entity_type") or "").strip()
            if type_filter and entity_type not in type_filter:
                continue
            matches.append(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "canonical_name": str(hit.get("canonical_name") or ""),
                    "match_source": "vector",
                    "matched_text": str(hit.get("canonical_name") or ""),
                    "confidence": 0.8,
                }
            )

        matches.sort(
            key=lambda item: (
                -len(str(item.get("matched_text") or "")),
                -float(item.get("confidence", 0.0) or 0.0),
                str(item.get("entity_id") or ""),
            )
        )
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in matches:
            entity_id = str(item["entity_id"])
            if entity_id in seen:
                continue
            seen.add(entity_id)
            deduped.append(item)
            if len(deduped) >= int(limit):
                break
        return deduped

    async def _search_entities_by_substring(
        self,
        normalized_query: str,
        *,
        type_filter: set[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find entities whose canonical name or alias is a substring of the query.

        Uses SQL INSTR() to avoid loading all entities into Python.
        """
        host = self._query_host()
        type_clause = ""
        type_args: list[Any] = []
        if type_filter:
            type_ph = ", ".join("?" for _ in type_filter)
            type_clause = f" AND ec.entity_type IN ({type_ph})"
            type_args = list(type_filter)

        query = f"""
            SELECT ec.entity_id, ec.canonical_name, ec.entity_type,
                   ec.canonical_name AS matched_text, 'canonical_name' AS match_source
            FROM entity_catalog ec
            WHERE INSTR(?, LOWER(TRIM(ec.canonical_name))) > 0{type_clause}
            UNION ALL
            SELECT ec.entity_id, ec.canonical_name, ec.entity_type,
                   ea.alias_text AS matched_text, 'alias' AS match_source
            FROM entity_aliases ea
            JOIN entity_catalog ec ON ea.entity_id = ec.entity_id
            WHERE INSTR(?, ea.normalized_alias) > 0{type_clause}
              AND ec.entity_id NOT IN (
                  SELECT entity_id FROM entity_catalog
                  WHERE INSTR(?, LOWER(TRIM(canonical_name))) > 0
              )
            LIMIT ?
        """
        args = (
            [normalized_query]
            + type_args
            + [normalized_query]
            + type_args
            + [normalized_query, limit]
        )

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        matches: list[dict[str, Any]] = []
        for row in rows:
            match_source = str(row["match_source"])
            matches.append(
                {
                    "entity_id": str(row["entity_id"]),
                    "entity_type": str(row["entity_type"]),
                    "canonical_name": str(row["canonical_name"]),
                    "match_source": match_source,
                    "matched_text": str(row["matched_text"]),
                    "confidence": 0.95 if match_source == "canonical_name" else 0.9,
                }
            )
        return matches

    async def _list_entities(
        self,
        *,
        limit: int,
        offset: int = 0,
        entity_type: Optional[str] = None,
        entity_ids: list[str] | None = None,
        order_by_recency: bool = False,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        host = self._query_host()
        sql = """
            SELECT ec.entity_id, ec.canonical_name, ec.entity_type, ec.embedding_status,
                   ec.embedding_profile_id, ec.last_embedded_at, ec.created_at, ec.updated_at
            FROM entity_catalog AS ec
            WHERE 1=1
        """
        args: list[Any] = []
        if entity_type:
            sql += " AND ec.entity_type = ?"
            args.append(entity_type)
        if entity_ids is not None:
            placeholders = ", ".join("?" for _ in entity_ids)
            sql += f" AND ec.entity_id IN ({placeholders})"
            args.extend(entity_ids)
        search_sql, search_args = self._entity_search_clause(query)
        sql += search_sql
        args.extend(search_args)
        if order_by_recency:
            sql += " ORDER BY ec.updated_at DESC LIMIT ? OFFSET ?"
        else:
            sql += " ORDER BY ec.entity_id ASC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                sql,
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
                "embedding_status": str(row["embedding_status"] or EMBEDDING_STATUS_DISABLED),
                "embedding_profile_id": row["embedding_profile_id"],
                "last_embedded_at": float(row["last_embedded_at"])
                if row["last_embedded_at"] is not None
                else None,
                "created_at": float(row["created_at"]),
                "updated_at": float(row["updated_at"]),
                "aliases": aliases_by_entity.get(str(row["entity_id"]), []),
            }
            for row in entities
        ]

    @staticmethod
    def _entity_search_clause(query: str | None) -> tuple[str, list[Any]]:
        return cast(
            tuple[str, list[Any]],
            build_like_search_clause(
                [
                    "ec.entity_id",
                    "ec.canonical_name",
                    "ec.entity_type",
                    "(SELECT GROUP_CONCAT(ea.alias_text, ' ') FROM entity_aliases ea WHERE ea.entity_id = ec.entity_id)",
                    "(SELECT GROUP_CONCAT(ea.normalized_alias, ' ') FROM entity_aliases ea WHERE ea.entity_id = ec.entity_id)",
                ],
                query,
            ),
        )

    def _query_host(self) -> _EntityCatalogQueryHostProtocol:
        return cast(_EntityCatalogQueryHostProtocol, self)


__all__ = ["L2EntityCatalogQueryMixin"]
