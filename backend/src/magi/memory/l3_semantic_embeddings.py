"""L3 semantic embedding storage built on SQLite (sqlite-vec compatible)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class EmbeddingBackend:
    """Embedding generator interface."""

    async def initialize(self) -> None:
        return None

    async def generate(self, text: str) -> List[float]:
        raise NotImplementedError

    @property
    def dimension(self) -> int:
        raise NotImplementedError


class LocalEmbeddingBackend(EmbeddingBackend):
    """Generates embeddings locally via sentence-transformers or hash fallback."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        self.model_name = model_name
        self._dimension = dimension
        self._model = None

    async def initialize(self) -> None:
        if self._model is not None:
            return
        if self.model_name.lower() in {"hash", "dummy"}:
            self._model = False
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self._dimension = int(self._model.get_sentence_embedding_dimension())
            logger.info("Loaded local embedding model '%s' (%d dims)", self.model_name, self._dimension)
        except Exception as exc:
            logger.warning("Using hash embeddings because local model load failed: %s", exc)
            self._model = False

    async def generate(self, text: str) -> List[float]:
        if self._model is None:
            await self.initialize()

        payload = text.strip()
        if not payload:
            return [0.0] * self._dimension

        if self._model and self._model is not False:
            vector = self._model.encode(payload, convert_to_numpy=True).tolist()
            return [float(x) for x in vector]

        return _hash_embedding(payload, self._dimension)

    @property
    def dimension(self) -> int:
        return self._dimension


class RemoteEmbeddingBackend(EmbeddingBackend):
    """Generates embeddings through an LLM adapter."""

    def __init__(self, llm_adapter: Any, model: str = "text-embedding-3-small", dimension: int = 1536):
        self.llm_adapter = llm_adapter
        self.model = model
        self._dimension = dimension

    async def initialize(self) -> None:
        if hasattr(self.llm_adapter, "set_embedding_model"):
            self.llm_adapter.set_embedding_model(self.model)
        if hasattr(self.llm_adapter, "embedding_dimension"):
            self._dimension = int(getattr(self.llm_adapter, "embedding_dimension"))

    async def generate(self, text: str) -> List[float]:
        payload = text.strip()
        if not payload:
            return [0.0] * self._dimension

        if not getattr(self.llm_adapter, "supports_embeddings", False):
            return _hash_embedding(payload, self._dimension)

        try:
            vector = await self.llm_adapter.get_embedding(payload, self.model)
        except Exception as exc:
            logger.warning("Remote embedding generation failed, using hash fallback: %s", exc)
            vector = None

        if not vector:
            return _hash_embedding(payload, self._dimension)
        return [float(x) for x in vector]

    @property
    def dimension(self) -> int:
        return self._dimension


class EventEmbedding:
    """Compatibility data holder for embedding payloads."""

    def __init__(self, event_id: str, embedding: List[float], text: str, metadata: Dict[str, Any], created_at: float):
        self.event_id = event_id
        self.embedding = embedding
        self.text = text
        self.metadata = metadata
        self.created_at = created_at


class eventEmbeddingStore:
    """SQLite embedding store (sqlite-vec default backend)."""

    def __init__(self, backend: Optional[EmbeddingBackend] = None, persist_path: Optional[str] = None):
        self.backend = backend or LocalEmbeddingBackend()
        self.persist_path = str(Path(persist_path or "~/.magi/data/memories/l3_reflections.db").expanduser())
        self._sqlite_vec_enabled = False

    async def initialize(self) -> None:
        Path(self.persist_path).parent.mkdir(parents=True, exist_ok=True)
        await self.backend.initialize()
        await self._init_db()

    async def _init_db(self) -> None:
        async with aiosqlite.connect(self.persist_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS event_embeddings (
                    event_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    metadata TEXT,
                    dimension INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_event_embeddings_created_at ON event_embeddings(created_at)")
            await db.commit()

        # Attempt loading sqlite-vec extension for environments that provide it.
        self._sqlite_vec_enabled = await self._try_enable_sqlite_vec()

    async def _try_enable_sqlite_vec(self) -> bool:
        extension_candidates = ["sqlite_vec", "vec0"]
        try:
            async with aiosqlite.connect(self.persist_path) as db:
                await db.enable_load_extension(True)
                for candidate in extension_candidates:
                    try:
                        await db.load_extension(candidate)
                        logger.info("Loaded sqlite-vec extension: %s", candidate)
                        return True
                    except Exception:
                        continue
        except Exception:
            return False
        return False

    async def add_event(self, event_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[float]:
        embedding = await self.backend.generate(text)
        created_at = time.time()

        async with aiosqlite.connect(self.persist_path) as db:
            await db.execute(
                """
                INSERT INTO event_embeddings(event_id, text, embedding, metadata, dimension, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    text = excluded.text,
                    embedding = excluded.embedding,
                    metadata = excluded.metadata,
                    dimension = excluded.dimension,
                    created_at = excluded.created_at
                """,
                (
                    event_id,
                    text,
                    json.dumps(embedding),
                    json.dumps(metadata or {}),
                    len(embedding),
                    created_at,
                ),
            )
            await db.commit()

        return embedding

    async def remove_event(self, event_id: str) -> None:
        async with aiosqlite.connect(self.persist_path) as db:
            await db.execute("DELETE FROM event_embeddings WHERE event_id = ?", (event_id,))
            await db.commit()

    async def similarity_search(self, query_text: str, top_k: int = 10, threshold: float = 0.0) -> List[Dict[str, Any]]:
        query_embedding = await self.backend.generate(query_text)
        rows = await self._load_all_rows()

        results: List[Dict[str, Any]] = []
        for row in rows:
            event_embedding = json.loads(row[2])
            similarity = _cosine_similarity(query_embedding, event_embedding)
            if similarity < threshold:
                continue
            results.append(
                {
                    "event_id": row[0],
                    "similarity": similarity,
                    "text": row[1],
                    "metadata": json.loads(row[3]) if row[3] else {},
                }
            )

        results.sort(key=lambda item: item["similarity"], reverse=True)
        return results[:top_k]

    async def _load_all_rows(self) -> List[tuple]:
        async with aiosqlite.connect(self.persist_path) as db:
            cursor = await db.execute(
                "SELECT event_id, text, embedding, metadata, created_at FROM event_embeddings"
            )
            return await cursor.fetchall()

    async def get_embedding(self, event_id: str) -> Optional[List[float]]:
        async with aiosqlite.connect(self.persist_path) as db:
            cursor = await db.execute(
                "SELECT embedding FROM event_embeddings WHERE event_id = ?",
                (event_id,),
            )
            row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def batch_add_events(self, events: List[Dict[str, Any]], text_field: str = "content") -> None:
        for event in events:
            event_id = str(event.get("id") or event.get("event_id") or "")
            if not event_id:
                continue
            text = str(event.get(text_field) or event.get("data") or "").strip()
            if not text:
                continue
            await self.add_event(
                event_id=event_id,
                text=text,
                metadata={"event_type": str(event.get("type", "unknown"))},
            )

    def clear_old_embeddings(self, older_than_days: int = 30) -> int:
        cutoff = time.time() - (older_than_days * 86400)
        return _sync_delete_where(self.persist_path, "event_embeddings", cutoff)

    def clear(self) -> int:
        return _sync_clear_table(self.persist_path, "event_embeddings")

    def get_statistics(self) -> Dict[str, Any]:
        total = _sync_count(self.persist_path, "event_embeddings")
        return {
            "total_embeddings": total,
            "dimension": self.backend.dimension,
            "backend": "sqlite_vec",
            "sqlite_vec_enabled": self._sqlite_vec_enabled,
            "db_path": self.persist_path,
        }

    # compatibility methods used by legacy callers
    def _save_to_disk(self) -> None:
        return None

    _save = _save_to_disk


class HybrideventSearch:
    """Combines semantic score and keyword score."""

    def __init__(self, embedding_store: eventEmbeddingStore):
        self.embedding_store = embedding_store

    async def search(
        self,
        query: str,
        top_k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Dict[str, Any]]:
        semantic_results = await self.embedding_store.similarity_search(query_text=query, top_k=top_k * 3, threshold=0.0)
        keyword_results = await self._keyword_search(query, top_k=top_k * 3)
        merged = self._merge_results(semantic_results, keyword_results, semantic_weight, keyword_weight)
        return merged[:top_k]

    async def _keyword_search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        query_text = query.strip().lower()
        if not query_text:
            return []

        rows = await self.embedding_store._load_all_rows()
        matches: List[Dict[str, Any]] = []
        for event_id, text, _embedding, metadata, _created_at in rows:
            text_value = (text or "").lower()
            if query_text not in text_value:
                continue
            score = len(query_text) / max(len(text_value), 1)
            matches.append(
                {
                    "event_id": event_id,
                    "similarity": score,
                    "text": text,
                    "metadata": json.loads(metadata) if metadata else {},
                }
            )

        matches.sort(key=lambda item: item["similarity"], reverse=True)
        return matches[:top_k]

    def _merge_results(
        self,
        semantic_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        semantic_weight: float,
        keyword_weight: float,
    ) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}

        for item in semantic_results:
            merged[item["event_id"]] = {
                "event_id": item["event_id"],
                "text": item.get("text", ""),
                "metadata": item.get("metadata", {}),
                "semantic_score": float(item.get("similarity", 0.0)),
                "keyword_score": 0.0,
            }

        for item in keyword_results:
            event_id = item["event_id"]
            if event_id not in merged:
                merged[event_id] = {
                    "event_id": event_id,
                    "text": item.get("text", ""),
                    "metadata": item.get("metadata", {}),
                    "semantic_score": 0.0,
                    "keyword_score": 0.0,
                }
            merged[event_id]["keyword_score"] = float(item.get("similarity", 0.0))

        results = []
        for item in merged.values():
            combined = item["semantic_score"] * semantic_weight + item["keyword_score"] * keyword_weight
            results.append(
                {
                    "event_id": item["event_id"],
                    "text": item["text"],
                    "metadata": item["metadata"],
                    "semantic_score": item["semantic_score"],
                    "keyword_score": item["keyword_score"],
                    "combined_score": combined,
                    "similarity": combined,
                }
            )

        results.sort(key=lambda row: row["combined_score"], reverse=True)
        return results


def create_embedding_store(
    backend: str = "sqlite_vec",
    llm_adapter: Any = None,
    remote_model: str = "text-embedding-3-small",
    remote_dimension: int = 1536,
    persist_path: Optional[str] = None,
) -> Optional[eventEmbeddingStore]:
    """Factory for sqlite-backed embedding stores.

    Returns None if no valid embedding adapter is provided.
    Embedding requires a configured remote embedding model (no local fallback).
    """
    # Only create store if we have a valid embedding adapter
    if llm_adapter is None or not getattr(llm_adapter, "supports_embeddings", lambda: False)():
        logger.info("No embedding adapter available, L3 embeddings will be disabled")
        return None

    embedding_backend: EmbeddingBackend = RemoteEmbeddingBackend(
        llm_adapter=llm_adapter,
        model=getattr(llm_adapter, "model_name", remote_model),
        dimension=getattr(llm_adapter, "embedding_dimension", remote_dimension),
    )
    logger.info("Using remote embedding backend with model: %s", getattr(llm_adapter, "model_name", "unknown"))

    return eventEmbeddingStore(backend=embedding_backend, persist_path=persist_path)


def _hash_embedding(text: str, dimension: int) -> List[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    buf = bytearray(seed)
    while len(buf) < dimension:
        buf.extend(hashlib.sha256(bytes(buf[-32:])).digest())
    return [float(value) / 255.0 for value in buf[:dimension]]


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    if not vec1 or not vec2:
        return 0.0
    limit = min(len(vec1), len(vec2))
    if limit == 0:
        return 0.0

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for i in range(limit):
        a = float(vec1[i])
        b = float(vec2[i])
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    denom = math.sqrt(norm1) * math.sqrt(norm2)
    if denom <= 0:
        return 0.0
    return dot / denom


def _sync_count(db_path: str, table: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = int(cur.fetchone()[0])
    conn.close()
    return total


def _sync_clear_table(db_path: str, table: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = int(cur.fetchone()[0])
    cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    return total


def _sync_delete_where(db_path: str, table: str, created_at_cutoff: float) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE created_at < ?", (created_at_cutoff,))
    total = int(cur.fetchone()[0])
    cur.execute(f"DELETE FROM {table} WHERE created_at < ?", (created_at_cutoff,))
    conn.commit()
    conn.close()
    return total
