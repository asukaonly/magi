"""Chroma HTTP adapter; provider objects never cross the vector storage port."""

from __future__ import annotations

import asyncio
import json
import math
import os
from typing import Any

from ...config.memory_models import ChromaVectorSettings
from .projection import VectorProjectionOperation
from .remote_index import CurrentVectorRecords, RemoteVectorHit


class ChromaVectorClient:
    def __init__(self, settings: ChromaVectorSettings) -> None:
        self._settings = settings
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> Any:
        async with self._lock:
            if self._client is None:
                try:
                    import chromadb
                except ImportError as error:
                    raise RuntimeError(
                        "Chroma vector storage requires the storage-chroma dependency extra"
                    ) from error
                headers: dict[str, str] | None = None
                if self._settings.headers_env:
                    raw = os.environ.get(self._settings.headers_env)
                    if not raw:
                        raise ValueError("Chroma authentication environment variable is missing")
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict) or not all(
                        isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
                    ):
                        raise ValueError("Chroma authentication headers must be a string mapping")
                    headers = parsed
                self._client = await chromadb.AsyncHttpClient(
                    host=self._settings.host,
                    port=self._settings.port,
                    ssl=self._settings.ssl,
                    tenant=self._settings.tenant,
                    database=self._settings.database,
                    headers=headers,
                    settings=chromadb.Settings(anonymized_telemetry=False),
                )
            return self._client

    async def _collection(self, name: str) -> Any:
        client = await self._connect()
        from chromadb.errors import NotFoundError

        try:
            return await client.get_collection(name, embedding_function=None)
        except NotFoundError:
            return None

    async def apply(self, operation: VectorProjectionOperation) -> None:
        client = await self._connect()
        if operation.kind == "clear":
            await self.reconcile(operation.collection_id, None)
        elif operation.kind == "delete":
            collection = await self._collection(operation.collection_id)
            if collection is not None:
                await collection.delete(ids=[operation.record_id])
        elif operation.kind == "upsert":
            payload = operation.payload
            if payload is None or operation.record_id is None:
                raise ValueError("Vector upsert intent is incomplete")
            collection = await client.get_or_create_collection(
                operation.collection_id,
                embedding_function=None,
                configuration={"hnsw": {"space": "l2"}},
            )
            metadata = {"entity_id": payload["entity_id"]}
            partition = payload["metadata"].get("partition_value")
            if partition is not None:
                metadata["partition"] = partition
            await collection.upsert(
                ids=[operation.record_id], embeddings=[payload["vector"]], metadatas=[metadata]
            )
        else:
            raise ValueError("Unknown vector projection operation")

    async def search(
        self, collection: str, vector: list[float], limit: int, partition: str | None
    ) -> list[RemoteVectorHit]:
        target = await self._collection(collection)
        if target is None:
            return []
        count = await target.count()
        if not count:
            return []
        result = await target.query(
            query_embeddings=[vector],
            n_results=min(limit, count),
            where={"partition": partition} if partition is not None else None,
            include=["distances", "metadatas"],
        )
        hits = []
        for record_id, distance, metadata in zip(
            result["ids"][0], result["distances"][0], result["metadatas"][0], strict=True
        ):
            if (
                not isinstance(metadata, dict)
                or not isinstance(metadata.get("entity_id"), str)
                or not math.isfinite(distance)
                or distance < 0
            ):
                raise ValueError("Chroma returned an invalid vector search result")
            hits.append(RemoteVectorHit(record_id, metadata["entity_id"], math.sqrt(distance)))
        return hits

    async def vectors(self, collection: str, record_ids: list[str]) -> dict[str, list[float]]:
        target = await self._collection(collection)
        if target is None or not record_ids:
            return {}
        result = await target.get(ids=record_ids, include=["embeddings"])
        vectors = {}
        for record_id, vector in zip(result["ids"], result["embeddings"], strict=True):
            values = [float(value) for value in vector]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Chroma returned a non-finite vector")
            vectors[record_id] = values
        return vectors

    async def reconcile(self, collection: str, current_ids: CurrentVectorRecords | None) -> None:
        client = await self._connect()
        from chromadb.errors import NotFoundError

        if current_ids is None:
            try:
                await client.delete_collection(collection)
            except NotFoundError:
                pass
            return
        target = await self._collection(collection)
        if target is None:
            return
        offset = 0
        while True:
            result = await target.get(limit=250, offset=offset, include=[])
            ids = result["ids"]
            current = await current_ids(ids)
            stale = [record_id for record_id in ids if record_id not in current]
            if stale:
                await target.delete(ids=stale)
            offset += len(ids) - len(stale)
            if len(ids) < 250:
                return
