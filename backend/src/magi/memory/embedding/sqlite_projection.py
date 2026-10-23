"""SQLite desired revisions and outbox for immutable remote vector records."""

from __future__ import annotations

import hashlib
import json
import math
import re
from uuid import uuid4
from typing import Any

from ...core.sqlite import sqlite_transaction_async
from .embedding_service import EmbeddingResult
from .projection import VectorProjection, VectorProjectionOperation, embedding_model_key


def _digest(*values: object) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class SqliteVectorProjectionRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def bind(self, namespace: str, backend_identity: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", namespace) or not backend_identity:
            raise ValueError("Invalid vector projection namespace or backend identity")
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "INSERT INTO vector_projection_namespaces(namespace,backend_identity,instance_id) VALUES (?,?,?) "
                "ON CONFLICT(namespace) DO NOTHING",
                (namespace, backend_identity, uuid4().hex),
            )
            cursor = await db.execute(
                "SELECT backend_identity FROM vector_projection_namespaces WHERE namespace=?",
                (namespace,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None or row[0] != backend_identity:
                raise ValueError(
                    "Vector backend identity changed; an explicit storage migration is required"
                )

    async def upsert(
        self,
        namespace: str,
        *,
        entity_id: str,
        embedding: EmbeddingResult,
        metadata: dict[str, Any] | None,
    ) -> VectorProjection:
        return (
            await self.upsert_many(
                namespace, [{"entity_id": entity_id, "embedding": embedding, "metadata": metadata}]
            )
        )[0]

    async def upsert_many(
        self, namespace: str, items: list[dict[str, Any]]
    ) -> list[VectorProjection]:
        prepared = []
        for item in items:
            entity_id, embedding = item["entity_id"], item["embedding"]
            if (
                not isinstance(entity_id, str)
                or not entity_id
                or not isinstance(embedding, EmbeddingResult)
            ):
                raise ValueError("Vector projection requires an entity and embedding")
            key = embedding_model_key(embedding)
            if (
                not key
                or embedding.dimension < 1
                or len(embedding.vector) != embedding.dimension
                or not all(math.isfinite(value) for value in embedding.vector)
            ):
                raise ValueError("Vector projection has an invalid embedding identity or vector")
            metadata = item.get("metadata")
            if metadata is None:
                metadata = {}
            if not isinstance(metadata, dict):
                raise ValueError("Vector metadata must be an object")
            partition = metadata.get("partition_value")
            if partition is not None and not isinstance(partition, str):
                raise ValueError("Vector partition must be a string")
            payload = json.dumps(
                {"entity_id": entity_id, "vector": embedding.vector, "metadata": metadata},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            prepared.append((entity_id, key, embedding.dimension, partition, payload))
        if not prepared:
            return []
        results = []
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT generation,revision,instance_id FROM vector_projection_namespaces WHERE namespace=?",
                (namespace,),
            )
            state = await cursor.fetchone()
            await cursor.close()
            if state is None:
                raise RuntimeError("Vector projection namespace has not been bound")
            generation, revision = int(state[0]), int(state[1])
            for entity_id, key, dimension, partition, payload in prepared:
                cursor = await db.execute(
                    "SELECT record_id,collection_id FROM vector_projection_entries WHERE namespace=? AND entity_id=? AND model_key=?",
                    (namespace, entity_id, key),
                )
                previous = await cursor.fetchone()
                await cursor.close()
                if previous is not None:
                    await self._enqueue_delete(db, namespace, str(previous[0]), str(previous[1]))
                revision += 1
                collection = (
                    f"magi-{namespace}-{_digest(state[2], key, dimension, generation)[:32]}"
                )
                record_id = _digest(state[2], namespace, entity_id, key, generation, revision)
                await db.execute(
                    "INSERT INTO vector_projection_collections(namespace,collection_id,generation) VALUES (?,?,?) ON CONFLICT(collection_id) DO NOTHING",
                    (namespace, collection, generation),
                )
                await db.execute(
                    "INSERT INTO vector_projection_entries(namespace,entity_id,model_key,dimension,generation,revision,record_id,collection_id,partition_value,published) "
                    "VALUES (?,?,?,?,?,?,?,?,?,0) ON CONFLICT(namespace,entity_id,model_key) DO UPDATE SET "
                    "dimension=excluded.dimension,generation=excluded.generation,revision=excluded.revision,record_id=excluded.record_id,"
                    "collection_id=excluded.collection_id,partition_value=excluded.partition_value,published=0",
                    (
                        namespace,
                        entity_id,
                        key,
                        dimension,
                        generation,
                        revision,
                        record_id,
                        collection,
                        partition,
                    ),
                )
                await db.execute(
                    "INSERT INTO vector_projection_operations(namespace,kind,collection_id,record_id,payload_json) VALUES (?,'upsert',?,?,?)",
                    (namespace, collection, record_id, payload),
                )
                results.append(
                    VectorProjection(
                        entity_id,
                        key,
                        dimension,
                        generation,
                        revision,
                        record_id,
                        collection,
                        partition,
                        False,
                    )
                )
            await db.execute(
                "UPDATE vector_projection_namespaces SET revision=? WHERE namespace=?",
                (revision, namespace),
            )
        return results

    @staticmethod
    async def _enqueue_delete(db, namespace: str, record_id: str, collection_id: str) -> None:
        await db.execute(
            "DELETE FROM vector_projection_operations WHERE namespace=? AND record_id=? AND kind='upsert'",
            (namespace, record_id),
        )
        await db.execute(
            "INSERT INTO vector_projection_operations(namespace,kind,collection_id,record_id) VALUES (?,'delete',?,?)",
            (namespace, collection_id, record_id),
        )

    async def delete(self, namespace: str, *, entity_id: str, model_key: str | None = None) -> None:
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            clauses = "namespace=? AND entity_id=?" + (
                " AND model_key=?" if model_key is not None else ""
            )
            parameters = (
                (namespace, entity_id, model_key)
                if model_key is not None
                else (namespace, entity_id)
            )
            cursor = await db.execute(
                f"SELECT record_id,collection_id FROM vector_projection_entries WHERE {clauses}",
                parameters,
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for row in rows:
                await self._enqueue_delete(db, namespace, str(row[0]), str(row[1]))
            await db.execute(f"DELETE FROM vector_projection_entries WHERE {clauses}", parameters)
            await db.execute(
                "UPDATE vector_projection_namespaces SET revision=revision+1 WHERE namespace=?",
                (namespace,),
            )

    async def clear(self, namespace: str) -> None:
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE vector_projection_namespaces SET generation=generation+1,revision=revision+1 WHERE namespace=?",
                (namespace,),
            )
            await db.execute(
                "DELETE FROM vector_projection_entries WHERE namespace=?", (namespace,)
            )
            await db.execute(
                "DELETE FROM vector_projection_operations WHERE namespace=?", (namespace,)
            )
            await db.execute(
                "INSERT INTO vector_projection_operations(namespace,kind,collection_id) "
                "SELECT namespace,'clear',collection_id FROM vector_projection_collections WHERE namespace=?",
                (namespace,),
            )

    async def current(
        self, namespace: str, *, entity_ids: list[str] | None = None
    ) -> list[VectorProjection]:
        if entity_ids == []:
            return []
        where = "namespace=?"
        parameters: tuple[Any, ...] = (namespace,)
        if entity_ids is not None:
            where += " AND entity_id IN (SELECT value FROM json_each(?))"
            parameters += (json.dumps(entity_ids),)
        async with sqlite_transaction_async(self._db_path) as db:
            cursor = await db.execute(
                f"SELECT * FROM vector_projection_entries WHERE {where} ORDER BY entity_id,model_key",
                parameters,
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [
            VectorProjection(
                entity_id=str(row["entity_id"]),
                model_key=str(row["model_key"]),
                dimension=int(row["dimension"]),
                generation=int(row["generation"]),
                revision=int(row["revision"]),
                record_id=str(row["record_id"]),
                collection_id=str(row["collection_id"]),
                partition_value=row["partition_value"],
                published=bool(row["published"]),
            )
            for row in rows
        ]

    async def pending(self, namespace: str, *, limit: int = 100) -> list[VectorProjectionOperation]:
        async with sqlite_transaction_async(self._db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM vector_projection_operations WHERE namespace=? ORDER BY operation_id LIMIT ?",
                (namespace, max(1, min(limit, 1000))),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        result = []
        for row in rows:
            payload = json.loads(row["payload_json"]) if row["payload_json"] is not None else None
            if payload is not None and not isinstance(payload, dict):
                raise ValueError("Invalid stored vector projection payload")
            result.append(
                VectorProjectionOperation(
                    int(row["operation_id"]),
                    row["kind"],
                    str(row["collection_id"]),
                    row["record_id"],
                    payload,
                )
            )
        return result

    async def acknowledge(self, namespace: str, operation: VectorProjectionOperation) -> None:
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT * FROM vector_projection_operations WHERE namespace=? AND operation_id=?",
                (namespace, operation.operation_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return
            if row["kind"] == "upsert":
                await db.execute(
                    "UPDATE vector_projection_entries SET published=1 WHERE namespace=? AND record_id=?",
                    (namespace, row["record_id"]),
                )
            await db.execute(
                "DELETE FROM vector_projection_operations WHERE namespace=? AND operation_id=?",
                (namespace, operation.operation_id),
            )

    async def collections(self, namespace: str) -> dict[str, bool]:
        """Retain content-free retired collection identities for late-write cleanup."""
        async with sqlite_transaction_async(self._db_path) as db:
            async with db.execute(
                "SELECT c.collection_id,c.generation=n.generation FROM vector_projection_collections c "
                "JOIN vector_projection_namespaces n ON n.namespace=c.namespace WHERE c.namespace=?",
                (namespace,),
            ) as cursor:
                return {str(row[0]): bool(row[1]) for row in await cursor.fetchall()}

    async def record_ids(self, namespace: str, collection_id: str) -> set[str]:
        async with sqlite_transaction_async(self._db_path) as db:
            async with db.execute(
                "SELECT record_id FROM vector_projection_entries WHERE namespace=? AND collection_id=?",
                (namespace, collection_id),
            ) as cursor:
                return {str(row[0]) for row in await cursor.fetchall()}

    async def filter_record_ids(self, namespace: str, collection_id: str, candidates: list[str]) -> set[str]:
        """Validate one provider page against the current immutable revisions."""
        if not candidates:
            return set()
        if len(candidates) > 250:
            raise ValueError("Vector reconciliation pages cannot exceed 250 records")
        async with sqlite_transaction_async(self._db_path) as db:
            async with db.execute(
                "SELECT record_id FROM vector_projection_entries WHERE namespace=? AND collection_id=? "
                f"AND record_id IN ({','.join('?' for _ in candidates)})",
                (namespace, collection_id, *candidates),
            ) as cursor:
                return {str(row[0]) for row in await cursor.fetchall()}

    async def search_collections(self, namespace: str, model_key: str, dimension: int) -> list[str]:
        async with sqlite_transaction_async(self._db_path) as db:
            async with db.execute(
                "SELECT DISTINCT collection_id FROM vector_projection_entries "
                "WHERE namespace=? AND model_key=? AND dimension=? AND published=1",
                (namespace, model_key, dimension),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def page(self, namespace: str, *, after: str, limit: int) -> list[str]:
        async with sqlite_transaction_async(self._db_path) as db:
            async with db.execute(
                "SELECT DISTINCT entity_id FROM vector_projection_entries WHERE namespace=? AND entity_id>? "
                "ORDER BY entity_id LIMIT ?",
                (namespace, after, limit),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]
