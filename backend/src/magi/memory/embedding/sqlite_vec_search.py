"""Search helpers for sqlite-vec backed memory indexes."""

from __future__ import annotations

from typing import Any, cast

import sqlite_vec

from .embedding_service import EmbeddingResult
from .sqlite_vec_types import VectorSearchHit, _deserialize_float32_blob


class SqliteVecSearchMixin:
    """Nearest-neighbor and raw-vector reads for sqlite-vec indexes."""

    async def search(
        self,
        *,
        embedding: EmbeddingResult,
        limit: int,
        max_distance: float | None = None,
        partition_value: str | None = None,
    ) -> list[VectorSearchHit]:
        host = cast(Any, self)
        await host.initialize()
        vec_table = host._vec_table_name(embedding.model_name, embedding.dimension)
        async with host._db_lock:
            db = host._require_db()
            await host._ensure_registry_schema(db)
            if not await host._table_exists(db, vec_table):
                return []

            search_limit = max(1, int(limit))
            clauses = ["embedding MATCH ?", "k = ?"]
            params: list[Any] = [sqlite_vec.serialize_float32(embedding.vector), search_limit]
            if max_distance is not None:
                clauses.append("distance < ?")
                params.append(float(max_distance))
            if partition_value is not None and host._partition_key_column:
                clauses.append(f"{host._partition_key_column} = ?")
                params.append(partition_value)
            where = " AND ".join(clauses)
            sql = f'SELECT rowid, distance FROM "{vec_table}" WHERE {where} ORDER BY distance'

            async with db.execute(sql, tuple(params)) as cursor:
                vector_rows = await cursor.fetchall()

            if not vector_rows:
                return []

            rowids = [int(row["rowid"]) for row in vector_rows]
            placeholders = ", ".join("?" for _ in rowids)
            async with db.execute(
                f"SELECT vec_rowid, {host._entity_column} FROM {host._registry_table} WHERE vec_rowid IN ({placeholders})",
                tuple(rowids),
            ) as cursor:
                registry_rows = await cursor.fetchall()

        entity_by_rowid = {int(row["vec_rowid"]): str(row[host._entity_column]) for row in registry_rows}
        hits: list[VectorSearchHit] = []
        for row in vector_rows:
            entity_id = entity_by_rowid.get(int(row["rowid"]))
            if entity_id is None:
                continue
            hits.append(VectorSearchHit(entity_id=entity_id, distance=float(row["distance"])))
        return hits

    async def get_vectors(
        self,
        *,
        entity_ids: list[str],
    ) -> dict[str, list[float]]:
        """Return raw embedding vectors for the given *entity_ids*."""
        if not entity_ids:
            return {}
        host = cast(Any, self)
        await host.initialize()
        async with host._db_lock:
            db = host._require_db()
            await host._ensure_registry_schema(db)
            ph = ", ".join("?" for _ in entity_ids)
            async with db.execute(
                f"SELECT {host._entity_column}, vec_rowid, vec_table FROM {host._registry_table}"
                f" WHERE {host._entity_column} IN ({ph})",
                tuple(entity_ids),
            ) as cursor:
                registry_rows = await cursor.fetchall()

            if not registry_rows:
                return {}

            results: dict[str, list[float]] = {}
            table_groups: dict[str, list[tuple[str, int]]] = {}
            for row in registry_rows:
                table_name = str(row["vec_table"])
                entity_id = str(row[host._entity_column])
                rowid = int(row["vec_rowid"])
                table_groups.setdefault(table_name, []).append((entity_id, rowid))

            for table_name, entries in table_groups.items():
                if not await host._table_exists(db, table_name):
                    continue
                rowids = [rowid for _, rowid in entries]
                rid_ph = ", ".join("?" for _ in rowids)
                async with db.execute(
                    f'SELECT rowid, embedding FROM "{table_name}" WHERE rowid IN ({rid_ph})',
                    tuple(rowids),
                ) as cursor:
                    vec_rows = {int(r["rowid"]): r["embedding"] for r in await cursor.fetchall()}

                for entity_id, rowid in entries:
                    raw = vec_rows.get(rowid)
                    if raw is not None:
                        results[entity_id] = _deserialize_float32_blob(raw)
        return results


__all__ = ["SqliteVecSearchMixin"]
