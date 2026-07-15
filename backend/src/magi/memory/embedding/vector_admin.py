"""Administrative helpers for memory vector identity and rebuilds."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...utils.runtime import get_runtime_paths
from ..l1.embeddings.common import EMBEDDING_TEXT_BUILDER_VERSION as L1_TEXT_BUILDER_VERSION
from ..l2.entities.catalog.embeddings import (
    EMBEDDING_TEXT_BUILDER_VERSION as L2_ENTITY_TEXT_BUILDER_VERSION,
)
from ..l3.embeddings.summaries import EMBEDDING_TEXT_BUILDER_VERSION as L3_TEXT_BUILDER_VERSION
from ..l4.storage.schema import EMBEDDING_TEXT_BUILDER_VERSION as L4_TEXT_BUILDER_VERSION
from .chunking import ChunkedText
from .embedding_pipeline import EmbeddingPipelineItem, MemoryEmbeddingPipeline
from .embedding_text_builders import (
    L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
    build_l2_edge_embedding_text,
)
from .local_embedding_identity import compute_local_embedding_model_fingerprint

VECTOR_LAYERS: tuple[str, ...] = ("l1", "l2_entities", "l2_edges", "l3", "l4")
_LAYER_TEXT_BUILDERS: dict[str, str] = {
    "l1": L1_TEXT_BUILDER_VERSION,
    "l2_entities": L2_ENTITY_TEXT_BUILDER_VERSION,
    "l2_edges": L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
    "l3": L3_TEXT_BUILDER_VERSION,
    "l4": L4_TEXT_BUILDER_VERSION,
}
_TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}


class EmbeddingRebuildPausedError(RuntimeError):
    """Raised when a destructive clear has paused new rebuild jobs."""

_ADMIN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS embedding_rebuild_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    requested_layers_json TEXT NOT NULL,
    active_layer TEXT,
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    succeeded_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_jobs_status_updated
    ON embedding_rebuild_jobs(status, updated_at);

CREATE TABLE IF NOT EXISTS embedding_rebuild_job_layers (
    job_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    status TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    succeeded_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (job_id, layer)
);
CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_job_layers_status
    ON embedding_rebuild_job_layers(status, updated_at);
"""


@dataclass(frozen=True, slots=True)
class VectorConfigIdentity:
    """Comparable vector identity for one memory layer."""

    layer: str
    mode: str
    text_builder_version: str
    hard_key: str
    label: str
    dimension: int | None
    identity_known: bool
    provenance: dict[str, str | int | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "mode": self.mode,
            "text_builder_version": self.text_builder_version,
            "hard_key": self.hard_key,
            "label": self.label,
            "dimension": self.dimension,
            "identity_known": self.identity_known,
            "provenance": dict(self.provenance),
        }


async def build_embedding_config_preflight(
    *, current_config: Any, proposed_config: Any
) -> dict[str, Any]:
    """Compare active and proposed embedding settings for rebuild risk."""

    ready_counts = await collect_vector_ready_counts()
    current_identities = build_layer_vector_identities(current_config)
    proposed_identities = build_layer_vector_identities(proposed_config)
    warnings: list[dict[str, Any]] = []
    for layer in VECTOR_LAYERS:
        warning = _compare_layer_identity(
            layer=layer,
            ready_count=int(ready_counts.get(layer, 0)),
            current_identity=current_identities.get(layer),
            proposed_identity=proposed_identities.get(layer),
        )
        if warning is not None:
            warnings.append(warning)
    severity = "none"
    if any(item["severity"] == "strong" for item in warnings):
        severity = "strong"
    elif any(item["severity"] == "soft" for item in warnings):
        severity = "soft"
    return {
        "severity": severity,
        "requires_rebuild": severity == "strong",
        "ready_counts": ready_counts,
        "ready_total": sum(int(value) for value in ready_counts.values()),
        "warnings": warnings,
        "current_identities": _identity_map_to_dict(current_identities),
        "proposed_identities": _identity_map_to_dict(proposed_identities),
    }


def build_layer_vector_identities(config: Any) -> dict[str, VectorConfigIdentity | None]:
    return {
        layer: _build_layer_vector_identity(config=config, layer=layer) for layer in VECTOR_LAYERS
    }


async def build_embedding_vector_status(manager: "EmbeddingRebuildManager") -> dict[str, Any]:
    from ...config.loader import get_config

    runtime_config = get_config()
    ready_counts = await collect_vector_ready_counts()
    return {
        "ready_counts": ready_counts,
        "ready_total": sum(int(value) for value in ready_counts.values()),
        "active_identities": _identity_map_to_dict(build_layer_vector_identities(runtime_config)),
        "latest_job": await manager.get_latest_job(),
    }


async def collect_vector_ready_counts() -> dict[str, int]:
    paths = get_runtime_paths()
    l1_db_path = str(paths.l1_memory_db_path)
    memory_db_path = str(paths.memory_db_path)
    return {
        "l1": await _safe_count(
            l1_db_path,
            "SELECT COUNT(*) FROM fact_events fe "
            "JOIN l1_event_embedding_state es USING(event_id) "
            "WHERE fe.deleted_at IS NULL AND es.embedding_status = 3",
        ),
        "l2_entities": await _safe_count(
            memory_db_path, "SELECT COUNT(*) FROM entity_catalog WHERE embedding_status = 'ready'"
        ),
        "l2_edges": await _safe_count(
            memory_db_path,
            "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active' AND embedding_status = 'ready'",
        ),
        "l3": await _safe_count(
            memory_db_path, "SELECT COUNT(*) FROM summaries WHERE embedding_status = 'ready'"
        ),
        "l4": await _safe_count(
            memory_db_path,
            "SELECT COUNT(*) FROM procedural_skills WHERE deleted_at IS NULL AND embedding_status = 'ready'",
        ),
    }


async def collect_vector_rebuild_source_counts() -> dict[str, int]:
    paths = get_runtime_paths()
    l1_db_path = str(paths.l1_memory_db_path)
    memory_db_path = str(paths.memory_db_path)
    return {
        "l1": await _safe_count(
            l1_db_path,
            "SELECT COUNT(*) FROM fact_events WHERE deleted_at IS NULL",
        ),
        "l2_entities": await _safe_count(memory_db_path, "SELECT COUNT(*) FROM entity_catalog"),
        "l2_edges": await _safe_count(
            memory_db_path,
            "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'",
        ),
        "l3": await _safe_count(memory_db_path, "SELECT COUNT(*) FROM summaries"),
        "l4": await _safe_count(
            memory_db_path,
            "SELECT COUNT(*) FROM procedural_skills WHERE deleted_at IS NULL",
        ),
    }


class EmbeddingRebuildManager:
    """Runs and persists memory embedding rebuild jobs."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._pause_depth = 0

    async def start_rebuild(
        self, *, unified_memory: Any, layers: Iterable[str] | None = None
    ) -> dict[str, Any]:
        requested_layers = _normalize_layers(layers)
        await self._ensure_schema()
        await self._mark_abandoned_jobs()
        async with self._lock:
            if self._pause_depth > 0:
                raise EmbeddingRebuildPausedError(
                    "Embedding rebuild is paused while memory is being cleared"
                )
            active_job = await self._get_active_job()
            if active_job is not None:
                return active_job
            source_counts = await collect_vector_rebuild_source_counts()
            now = time.time()
            job_id = f"embedding-rebuild-{uuid.uuid4().hex}"
            total_items = sum(int(source_counts.get(layer, 0)) for layer in requested_layers)
            db_path = str(get_runtime_paths().memory_db_path)
            async with sqlite_connection_async(db_path) as db:
                await db.execute(
                    """
                    INSERT INTO embedding_rebuild_jobs(
                        job_id, status, requested_layers_json, active_layer,
                        total_items, processed_items, succeeded_items, failed_items,
                        cancel_requested, error, created_at, started_at, finished_at, updated_at
                    ) VALUES (?, 'pending', ?, NULL, ?, 0, 0, 0, 0, NULL, ?, NULL, NULL, ?)
                    """,
                    (job_id, json.dumps(requested_layers), total_items, now, now),
                )
                await db.executemany(
                    """
                    INSERT INTO embedding_rebuild_job_layers(
                        job_id, layer, status, total_items, processed_items,
                        succeeded_items, failed_items, error, started_at, finished_at, updated_at
                    ) VALUES (?, ?, 'pending', ?, 0, 0, 0, NULL, NULL, NULL, ?)
                    """,
                    [
                        (job_id, layer, int(source_counts.get(layer, 0)), now)
                        for layer in requested_layers
                    ],
                )
                await db.commit()
            task = asyncio.create_task(self._run_job(job_id, unified_memory, requested_layers))
            self._tasks[job_id] = task
            task.add_done_callback(lambda _finished: self._tasks.pop(job_id, None))
            return await self.get_job(job_id) or {}

    async def get_latest_job(self) -> dict[str, Any] | None:
        await self._ensure_schema()
        await self._mark_abandoned_jobs()
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT job_id FROM embedding_rebuild_jobs ORDER BY created_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
        return await self.get_job(str(row["job_id"])) if row is not None else None

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        await self._ensure_schema()
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM embedding_rebuild_jobs WHERE job_id = ?", (job_id,)
            ) as cursor:
                job_row = await cursor.fetchone()
            if job_row is None:
                return None
            async with db.execute(
                "SELECT * FROM embedding_rebuild_job_layers WHERE job_id = ? ORDER BY rowid ASC",
                (job_id,),
            ) as cursor:
                layer_rows = await cursor.fetchall()
        return _job_row_to_dict(job_row, layer_rows)

    async def cancel_job(self, job_id: str) -> dict[str, Any] | None:
        await self._ensure_schema()
        db_path = str(get_runtime_paths().memory_db_path)
        now = time.time()
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                UPDATE embedding_rebuild_jobs
                SET cancel_requested = 1, updated_at = ?
                WHERE job_id = ? AND status IN ('pending', 'running')
                """,
                (now, job_id),
            )
            await db.commit()
        return await self.get_job(job_id)

    async def cancel_all_and_wait(self) -> int:
        """Cancel and await every in-process rebuild before destructive clear."""
        async with self._lock:
            active = self._cancel_active_tasks_locked()
        await self._await_cancelled_tasks(active)
        return len(active)

    async def pause_starts_and_cancel_all(self) -> int:
        """Atomically reject new jobs and cancel every existing rebuild."""
        async with self._lock:
            self._pause_depth += 1
            active = self._cancel_active_tasks_locked()
        await self._await_cancelled_tasks(active)
        return len(active)

    async def resume_starts(self) -> None:
        """Allow rebuild requests after destructive clear finishes."""
        async with self._lock:
            self._pause_depth = max(0, self._pause_depth - 1)

    def _cancel_active_tasks_locked(self) -> dict[str, asyncio.Task[None]]:
        active = {
            job_id: task
            for job_id, task in self._tasks.items()
            if not task.done()
        }
        for task in active.values():
            task.cancel()
        return active

    async def _await_cancelled_tasks(
        self,
        active: dict[str, asyncio.Task[None]],
    ) -> None:
        if not active:
            return
        await asyncio.gather(*active.values(), return_exceptions=True)
        for job_id in active:
            await self._finish_job(job_id=job_id, status="cancelled")

    async def _run_job(self, job_id: str, unified_memory: Any, layers: list[str]) -> None:
        async with unified_memory.memory_operation_guard():
            await self._run_job_guarded(job_id, unified_memory, layers)

    async def _run_job_guarded(
        self,
        job_id: str,
        unified_memory: Any,
        layers: list[str],
    ) -> None:
        now = time.time()
        await self._update_job(job_id=job_id, status="running", started_at=now, updated_at=now)
        processed_total = 0
        succeeded_total = 0
        failed_total = 0
        try:
            for layer in layers:
                if await self._cancel_requested(job_id):
                    await self._finish_job(
                        job_id=job_id,
                        status="cancelled",
                        processed_items=processed_total,
                        succeeded_items=succeeded_total,
                        failed_items=failed_total,
                    )
                    return
                await self._start_layer(job_id, layer)
                try:
                    completed_before_layer = processed_total

                    async def report_layer_progress(layer_processed: int) -> None:
                        await self._update_progress(
                            job_id=job_id,
                            layer=layer,
                            completed_items=completed_before_layer,
                            layer_processed_items=layer_processed,
                        )

                    processed = await _run_rebuild_layer(
                        unified_memory,
                        layer,
                        progress_callback=report_layer_progress,
                    )
                    await report_layer_progress(processed)
                except Exception as exc:
                    failed_total += 1
                    await self._finish_layer(job_id, layer, "failed", 0, 0, 1, str(exc))
                    await self._finish_job(
                        job_id=job_id,
                        status="failed",
                        processed_items=processed_total,
                        succeeded_items=succeeded_total,
                        failed_items=failed_total,
                        error=str(exc),
                    )
                    return
                processed_total += processed
                succeeded_total += processed
                await self._finish_layer(job_id, layer, "succeeded", processed, processed, 0, None)
            await self._finish_job(
                job_id=job_id,
                status="succeeded",
                processed_items=processed_total,
                succeeded_items=succeeded_total,
                failed_items=failed_total,
            )
        except Exception as exc:
            await self._finish_job(job_id=job_id, status="failed", error=str(exc))

    async def _ensure_schema(self) -> None:
        db_path = str(get_runtime_paths().memory_db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(db_path) as db:
            await db.executescript(_ADMIN_SCHEMA_SQL)
            await db.commit()

    async def _mark_abandoned_jobs(self) -> None:
        db_path = str(get_runtime_paths().memory_db_path)
        active_task_ids = {job_id for job_id, task in self._tasks.items() if not task.done()}
        now = time.time()
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT job_id FROM embedding_rebuild_jobs WHERE status IN ('pending', 'running')"
            ) as cursor:
                rows = await cursor.fetchall()
            abandoned = [
                str(row["job_id"]) for row in rows if str(row["job_id"]) not in active_task_ids
            ]
            if not abandoned:
                return
            placeholders = ", ".join("?" for _ in abandoned)
            await db.execute(
                f"""
                UPDATE embedding_rebuild_jobs
                SET status = 'failed', error = 'Embedding rebuild was interrupted.',
                    finished_at = ?, updated_at = ?
                WHERE job_id IN ({placeholders})
                """,
                (now, now, *abandoned),
            )
            await db.execute(
                f"""
                UPDATE embedding_rebuild_job_layers
                SET status = 'failed', error = COALESCE(error, 'Embedding rebuild was interrupted.'),
                    finished_at = COALESCE(finished_at, ?), updated_at = ?
                WHERE job_id IN ({placeholders}) AND status IN ('pending', 'running')
                """,
                (now, now, *abandoned),
            )
            await db.commit()

    async def _get_active_job(self) -> dict[str, Any] | None:
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT job_id FROM embedding_rebuild_jobs
                WHERE status IN ('pending', 'running')
                ORDER BY created_at DESC LIMIT 1
                """) as cursor:
                row = await cursor.fetchone()
        return await self.get_job(str(row["job_id"])) if row is not None else None

    async def _cancel_requested(self, job_id: str) -> bool:
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            async with db.execute(
                "SELECT cancel_requested FROM embedding_rebuild_jobs WHERE job_id = ?",
                (job_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return bool(row and int(row[0] or 0))

    async def _start_layer(self, job_id: str, layer: str) -> None:
        now = time.time()
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE embedding_rebuild_jobs SET active_layer = ?, updated_at = ? WHERE job_id = ?",
                (layer, now, job_id),
            )
            await db.execute(
                """
                UPDATE embedding_rebuild_job_layers
                SET status = 'running', started_at = ?, updated_at = ?
                WHERE job_id = ? AND layer = ?
                """,
                (now, now, job_id, layer),
            )
            await db.commit()

    async def _finish_layer(
        self,
        job_id: str,
        layer: str,
        status: str,
        processed_items: int,
        succeeded_items: int,
        failed_items: int,
        error: str | None,
    ) -> None:
        now = time.time()
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                UPDATE embedding_rebuild_job_layers
                SET status = ?, processed_items = ?, succeeded_items = ?, failed_items = ?,
                    error = ?, finished_at = ?, updated_at = ?
                WHERE job_id = ? AND layer = ?
                """,
                (
                    status,
                    int(processed_items),
                    int(succeeded_items),
                    int(failed_items),
                    error,
                    now,
                    now,
                    job_id,
                    layer,
                ),
            )
            await db.commit()

    async def _update_progress(
        self,
        *,
        job_id: str,
        layer: str,
        completed_items: int,
        layer_processed_items: int,
    ) -> None:
        now = time.time()
        layer_processed = max(0, int(layer_processed_items))
        total_processed = max(0, int(completed_items)) + layer_processed
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                UPDATE embedding_rebuild_jobs
                SET processed_items = ?, succeeded_items = ?, updated_at = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (total_processed, total_processed, now, job_id),
            )
            await db.execute(
                """
                UPDATE embedding_rebuild_job_layers
                SET processed_items = ?, succeeded_items = ?, updated_at = ?
                WHERE job_id = ? AND layer = ? AND status = 'running'
                """,
                (layer_processed, layer_processed, now, job_id, layer),
            )
            await db.commit()

    async def _update_job(self, job_id: str, **updates: Any) -> None:
        if not updates:
            return
        columns = ", ".join(f"{key} = ?" for key in updates)
        db_path = str(get_runtime_paths().memory_db_path)
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                f"UPDATE embedding_rebuild_jobs SET {columns} WHERE job_id = ?",
                (*updates.values(), job_id),
            )
            await db.commit()

    async def _finish_job(
        self,
        *,
        job_id: str,
        status: str,
        processed_items: int | None = None,
        succeeded_items: int | None = None,
        failed_items: int | None = None,
        error: str | None = None,
    ) -> None:
        now = time.time()
        updates: dict[str, Any] = {
            "status": status,
            "active_layer": None,
            "error": error,
            "finished_at": now,
            "updated_at": now,
        }
        if processed_items is not None:
            updates["processed_items"] = int(processed_items)
        if succeeded_items is not None:
            updates["succeeded_items"] = int(succeeded_items)
        if failed_items is not None:
            updates["failed_items"] = int(failed_items)
        await self._update_job(job_id, **updates)


async def rebuild_l2_edge_embeddings(
    *,
    db_path: str,
    embedding_service: Any,
    vector_index: Any,
    batch_size: int = 100,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
) -> int:
    """Rebuild active L2 knowledge-graph edge embeddings."""

    if embedding_service is None or vector_index is None:
        return 0
    normalized_batch_size = max(1, int(batch_size))
    await vector_index.clear()
    await _disable_active_l2_edge_embeddings(db_path)

    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
        text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
    )
    processed = 0
    offset = 0
    while True:
        rows = await _fetch_l2_edge_embedding_rows(
            db_path=db_path,
            batch_size=normalized_batch_size,
            offset=offset,
        )
        if not rows:
            break

        await _embed_l2_edge_rows(
            db_path=db_path,
            rows=rows,
            embedding_service=embedding_service,
            pipeline=pipeline,
        )
        processed += len(rows)
        offset += len(rows)
        if progress_callback is not None:
            await progress_callback(processed)
    return processed


async def _disable_active_l2_edge_embeddings(db_path: str) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute("""
            UPDATE knowledge_graph
            SET embedding_status = 'disabled', embedding_profile_id = NULL, last_embedded_at = NULL
            WHERE status = 'active'
            """)
        await db.commit()


async def _fetch_l2_edge_embedding_rows(
    *,
    db_path: str,
    batch_size: int,
    offset: int,
) -> list[aiosqlite.Row]:
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT kg.triple_id, kg.subject_id, kg.predicate, kg.object_id,
                kg.evidence_text, kg.natural_summary,
                sc.canonical_name AS subject_name, oc.canonical_name AS object_name
            FROM knowledge_graph kg
            LEFT JOIN entity_catalog sc ON sc.entity_id = kg.subject_id
            LEFT JOIN entity_catalog oc ON oc.entity_id = kg.object_id
            WHERE kg.status = 'active'
            ORDER BY kg.updated_at DESC, kg.triple_id ASC
            LIMIT ? OFFSET ?
            """,
            (batch_size, offset),
        ) as cursor:
            return await cursor.fetchall()


async def _embed_l2_edge_rows(
    *,
    db_path: str,
    rows: list[aiosqlite.Row],
    embedding_service: Any,
    pipeline: MemoryEmbeddingPipeline,
) -> None:
    items = [_edge_row_to_embedding_item(row) for row in rows]
    items = [item for item in items if item is not None]
    if not items:
        return
    results = await pipeline.upsert_items(items)
    updates = _l2_edge_embedding_updates(results, embedding_service)
    if updates:
        await _mark_l2_edge_embeddings_ready(db_path, updates)


def _l2_edge_embedding_updates(
    results: Iterable[Any],
    embedding_service: Any,
) -> list[tuple[str, float, str]]:
    updates: list[tuple[str, float, str]] = []
    for result in results:
        profile = embedding_service.profile_from_result(
            result.embeddings[0],
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )
        updates.append((profile.profile_id, result.embedded_at, result.parent_id))
    return updates


async def _mark_l2_edge_embeddings_ready(
    db_path: str,
    updates: list[tuple[str, float, str]],
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.executemany(
            """
            UPDATE knowledge_graph
            SET embedding_status = 'ready', embedding_profile_id = ?, last_embedded_at = ?
            WHERE triple_id = ?
            """,
            updates,
        )
        await db.commit()


async def _run_rebuild_layer(
    unified_memory: Any,
    layer: str,
    *,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
) -> int:
    if layer == "l1":
        store = getattr(unified_memory, "l1", None)
        return (
            int(await store.rebuild_embeddings(progress_callback=progress_callback))
            if store is not None
            else 0
        )
    if layer == "l2_entities":
        catalog = getattr(unified_memory, "l2_entity_catalog", None)
        return (
            int(await catalog.rebuild_embeddings(progress_callback=progress_callback))
            if catalog is not None
            else 0
        )
    if layer == "l2_edges":
        catalog = getattr(unified_memory, "l2_entity_catalog", None)
        l2_store = getattr(unified_memory, "l2", None)
        if catalog is None or l2_store is None:
            return 0
        return int(
            await rebuild_l2_edge_embeddings(
                db_path=str(l2_store.db_path),
                embedding_service=catalog.embedding_service,
                vector_index=catalog.edge_vector_index,
                progress_callback=progress_callback,
            )
        )
    if layer == "l3":
        store = getattr(unified_memory, "l3", None)
        return (
            int(await store.rebuild_embeddings(progress_callback=progress_callback))
            if store is not None
            else 0
        )
    if layer == "l4":
        store = getattr(unified_memory, "l4", None)
        return (
            int(await store.rebuild_embeddings(progress_callback=progress_callback))
            if store is not None
            else 0
        )
    raise ValueError(f"Unsupported embedding rebuild layer: {layer}")


def _edge_row_to_embedding_item(row: aiosqlite.Row) -> EmbeddingPipelineItem | None:
    text = build_l2_edge_embedding_text(
        subject_id=str(row["subject_id"]),
        predicate=str(row["predicate"]),
        object_id=str(row["object_id"]),
        evidence_text=row["evidence_text"],
        natural_summary=row["natural_summary"],
        subject_name=row["subject_name"],
        object_name=row["object_name"],
    )
    if not text.strip():
        return None
    triple_id = str(row["triple_id"])
    return EmbeddingPipelineItem(
        parent_id=triple_id,
        chunks=[
            ChunkedText(
                chunk_id=triple_id,
                text=text,
                chunk_index=0,
                char_start=0,
                char_end=len(text),
                token_estimate=max(1, len(text) // 4),
            )
        ],
        metadata={"kind": "edge"},
    )


def _build_layer_vector_identity(config: Any, layer: str) -> VectorConfigIdentity | None:
    if not _layer_vectors_enabled(config, layer):
        return None
    memory = getattr(config, "memory", None) or getattr(
        getattr(config, "agent", None), "memory", None
    )
    embedding_cfg = getattr(memory, "embedding", None)
    mode = _enum_value(getattr(embedding_cfg, "mode", "off"))
    if mode == "local":
        return _build_local_layer_identity(config, layer, _LAYER_TEXT_BUILDERS[layer])
    if mode == "remote":
        return _build_remote_layer_identity(config, layer, _LAYER_TEXT_BUILDERS[layer])
    return None


def _build_remote_layer_identity(
    config: Any, layer: str, text_builder_version: str
) -> VectorConfigIdentity | None:
    llm = getattr(config, "llm", None)
    selections = getattr(llm, "selections", {}) or {}
    providers = getattr(llm, "providers", {}) or {}
    selection = selections.get("embedding") if isinstance(selections, dict) else None
    if selection is None:
        return None
    model = str(getattr(selection, "model", "") or "").strip()
    if not model:
        return None
    dimension = _int_or_none(getattr(selection, "embedding_dimension", None))
    provider_id = str(getattr(selection, "provider_id", "") or "").strip()
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    hard_payload = {
        "mode": "remote",
        "model": model,
        "dimension": dimension,
        "text_builder_version": text_builder_version,
    }
    return VectorConfigIdentity(
        layer=layer,
        mode="remote",
        text_builder_version=text_builder_version,
        hard_key=_stable_json(hard_payload),
        label=model,
        dimension=dimension,
        identity_known=dimension is not None,
        provenance={
            "provider_id": provider_id or None,
            "provider_type": (
                _enum_value(getattr(provider, "provider_type", ""))
                if provider is not None
                else None
            ),
            "base_url": _embedding_base_url(provider),
            "api_format": str(getattr(provider, "api_format", "") or "") or None,
        },
    )


def _build_local_layer_identity(
    config: Any, layer: str, text_builder_version: str
) -> VectorConfigIdentity | None:
    memory = getattr(config, "memory", None) or getattr(
        getattr(config, "agent", None), "memory", None
    )
    local_cfg = getattr(getattr(memory, "embedding", None), "local", None)
    if local_cfg is None:
        return None
    fingerprint = compute_local_embedding_model_fingerprint(local_cfg)
    if fingerprint is None:
        model_ref = _local_model_ref(local_cfg)
        hard_payload = {
            "mode": "local",
            "model_file_hash": None,
            "model_ref": model_ref,
            "dimension": None,
            "text_builder_version": text_builder_version,
        }
        return VectorConfigIdentity(
            layer=layer,
            mode="local",
            text_builder_version=text_builder_version,
            hard_key=_stable_json(hard_payload),
            label=model_ref or "local",
            dimension=None,
            identity_known=False,
            provenance={"model_source": _enum_value(getattr(local_cfg, "model_source", "managed"))},
        )
    hard_payload = {
        "mode": "local",
        "model_file_hash": fingerprint.model_file_hash,
        "runtime_family": fingerprint.runtime_family,
        "dimension": fingerprint.dimension,
        "text_builder_version": text_builder_version,
    }
    return VectorConfigIdentity(
        layer=layer,
        mode="local",
        text_builder_version=text_builder_version,
        hard_key=_stable_json(hard_payload),
        label=fingerprint.model_name,
        dimension=fingerprint.dimension,
        identity_known=True,
        provenance={
            "model_source": _enum_value(getattr(local_cfg, "model_source", "managed")),
            "model_file_hash": fingerprint.model_file_hash[:16],
        },
    )


def _compare_layer_identity(
    *,
    layer: str,
    ready_count: int,
    current_identity: VectorConfigIdentity | None,
    proposed_identity: VectorConfigIdentity | None,
) -> dict[str, Any] | None:
    if ready_count <= 0 or (current_identity is None and proposed_identity is None):
        return None
    if current_identity is None or proposed_identity is None:
        return _warning(
            layer,
            "soft",
            "vector_availability_changed",
            ready_count,
            current_identity,
            proposed_identity,
        )
    if current_identity.hard_key != proposed_identity.hard_key:
        return _warning(
            layer,
            "strong",
            "hard_identity_changed",
            ready_count,
            current_identity,
            proposed_identity,
        )
    if (
        current_identity.mode == "remote"
        and proposed_identity.mode == "remote"
        and current_identity.provenance != proposed_identity.provenance
    ):
        return _warning(
            layer,
            "soft",
            "remote_provider_changed",
            ready_count,
            current_identity,
            proposed_identity,
        )
    return None


def _warning(
    layer: str,
    severity: str,
    reason: str,
    ready_count: int,
    current_identity: VectorConfigIdentity | None,
    proposed_identity: VectorConfigIdentity | None,
) -> dict[str, Any]:
    return {
        "layer": layer,
        "severity": severity,
        "reason": reason,
        "ready_count": ready_count,
        "current": current_identity.to_dict() if current_identity is not None else None,
        "proposed": proposed_identity.to_dict() if proposed_identity is not None else None,
    }


def _layer_vectors_enabled(config: Any, layer: str) -> bool:
    memory = getattr(config, "memory", None) or getattr(
        getattr(config, "agent", None), "memory", None
    )
    if memory is None:
        return False
    layer_key = "l2" if layer in {"l2_entities", "l2_edges"} else layer
    layer_config = getattr(memory, layer_key, None)
    if layer_config is None:
        return False
    return bool(getattr(layer_config, "enabled", True)) and bool(
        getattr(layer_config, "vectors_enabled", True)
    )


async def _safe_count(db_path: str, sql: str) -> int:
    if not Path(db_path).exists():
        return 0
    try:
        async with sqlite_connection_async(db_path) as db:
            async with db.execute(sql) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _job_row_to_dict(job_row: aiosqlite.Row, layer_rows: list[aiosqlite.Row]) -> dict[str, Any]:
    processed_items = int(job_row["processed_items"] or 0)
    succeeded_items = int(job_row["succeeded_items"] or 0)
    failed_items = int(job_row["failed_items"] or 0)
    total_items = _normalized_rebuild_total(
        total_items=job_row["total_items"],
        processed_items=processed_items,
        succeeded_items=succeeded_items,
        failed_items=failed_items,
    )
    return {
        "job_id": str(job_row["job_id"]),
        "status": str(job_row["status"]),
        "requested_layers": _json_list(str(job_row["requested_layers_json"] or "[]")),
        "active_layer": job_row["active_layer"],
        "total_items": total_items,
        "processed_items": processed_items,
        "succeeded_items": succeeded_items,
        "failed_items": failed_items,
        "cancel_requested": bool(job_row["cancel_requested"]),
        "error": job_row["error"],
        "created_at": job_row["created_at"],
        "started_at": job_row["started_at"],
        "finished_at": job_row["finished_at"],
        "updated_at": job_row["updated_at"],
        "terminal": str(job_row["status"]) in _TERMINAL_JOB_STATUSES,
        "layers": [_layer_row_to_dict(row) for row in layer_rows],
    }


def _layer_row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    processed_items = int(row["processed_items"] or 0)
    succeeded_items = int(row["succeeded_items"] or 0)
    failed_items = int(row["failed_items"] or 0)
    total_items = _normalized_rebuild_total(
        total_items=row["total_items"],
        processed_items=processed_items,
        succeeded_items=succeeded_items,
        failed_items=failed_items,
    )
    return {
        "layer": str(row["layer"]),
        "status": str(row["status"]),
        "total_items": total_items,
        "processed_items": processed_items,
        "succeeded_items": succeeded_items,
        "failed_items": failed_items,
        "error": row["error"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
    }


def _normalized_rebuild_total(
    *, total_items: Any, processed_items: int, succeeded_items: int, failed_items: int
) -> int:
    return max(int(total_items or 0), processed_items, succeeded_items + failed_items)


def _normalize_layers(layers: Iterable[str] | None) -> list[str]:
    if layers is None:
        return list(VECTOR_LAYERS)
    normalized: list[str] = []
    for layer in layers:
        value = str(layer or "").strip()
        if value in VECTOR_LAYERS and value not in normalized:
            normalized.append(value)
    return normalized or list(VECTOR_LAYERS)


def _embedding_base_url(provider: Any) -> str | None:
    if provider is None:
        return None
    services = getattr(provider, "services", None)
    embedding = getattr(services, "embedding", None)
    value = str(
        getattr(embedding, "base_url", "") or getattr(provider, "base_url", "") or ""
    ).strip()
    return value or None


def _local_model_ref(local_cfg: Any) -> str:
    if _enum_value(getattr(local_cfg, "model_source", "managed")) == "external":
        return str(getattr(local_cfg, "model_dir_path", "") or "").strip()
    return str(getattr(local_cfg, "managed_model_id", "") or "").strip()


def _identity_map_to_dict(identities: dict[str, VectorConfigIdentity | None]) -> dict[str, Any]:
    return {
        layer: identity.to_dict() if identity is not None else None
        for layer, identity in identities.items()
    }


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_list(value: str) -> list[str]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


__all__ = [
    "EmbeddingRebuildPausedError",
    "EmbeddingRebuildManager",
    "VECTOR_LAYERS",
    "build_embedding_config_preflight",
    "build_embedding_vector_status",
    "build_layer_vector_identities",
    "collect_vector_rebuild_source_counts",
    "collect_vector_ready_counts",
    "rebuild_l2_edge_embeddings",
]
