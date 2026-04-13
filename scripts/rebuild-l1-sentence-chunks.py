#!/usr/bin/env python3
"""Rebuild L1 event embeddings with sentence-level chunking.

Clears existing chunks and vectors, then re-chunks and re-embeds
all L1 events using chunk_sentences().  Only touches L1 — L2/L3/L4
are left untouched.

Usage:
    python scripts/rebuild-l1-sentence-chunks.py [--batch-size 200] [--base-dir ~/.magi]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_SRC_DIR = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC_DIR))

import aiosqlite  # noqa: E402

from magi.config import get_config  # noqa: E402
from magi.core.sqlite import sqlite_connection_async  # noqa: E402
from magi.llm.factory import create_scenario_llm_pool  # noqa: E402
from magi.memory.embedding.embedding_service import MemoryEmbeddingService  # noqa: E402
from magi.memory.l1.event_store import (  # noqa: E402
    EMBEDDING_STATUS_DISABLED,
    EMBEDDING_PROFILES_TABLE,
    EVENT_CHUNKS_TABLE,
    FACT_EVENTS_TABLE,
    L1EventStore,
)
from magi.utils.runtime import get_runtime_paths, set_runtime_dir  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild L1 event embeddings with sentence-level chunking.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Events per embedding batch (default: 200).",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Magi runtime home override (defaults to ~/.magi).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count events and estimate chunks without writing.",
    )
    return parser.parse_args()


def _format_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


async def _count_events(db_path: str) -> int:
    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        async with db.execute(
            f"SELECT count(*) FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL",
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def _dry_run(store: L1EventStore, db_path: str, total: int) -> None:
    """Preview how many sentence chunks would be generated."""
    from magi.memory.embedding.chunking import chunk_sentences
    from magi.memory.embedding.embedding_text_builders import build_l1_embedding_text

    sample_size = min(1000, total)
    single_chunk = 0
    multi_chunk = 0
    total_chunks = 0

    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM {FACT_EVENTS_TABLE} WHERE deleted_at IS NULL LIMIT ?",
            (sample_size,),
        ) as cursor:
            rows = await cursor.fetchall()

    for row in rows:
        event = store._row_to_memory_event(row)
        text = build_l1_embedding_text(event)
        chunks = chunk_sentences(text)
        total_chunks += len(chunks)
        if len(chunks) <= 1:
            single_chunk += 1
        else:
            multi_chunk += 1

    avg_chunks = total_chunks / max(1, len(rows))
    estimated_total_chunks = int(avg_chunks * total)
    print(f"\n--- Dry run (sampled {len(rows)}/{total} events) ---")
    print(f"  Single-chunk events : {single_chunk} ({single_chunk * 100 // len(rows)}%)")
    print(f"  Multi-chunk events  : {multi_chunk} ({multi_chunk * 100 // len(rows)}%)")
    print(f"  Avg chunks/event    : {avg_chunks:.1f}")
    print(f"  Estimated total     : {estimated_total_chunks:,} chunks (was: ~{total * 2.5:.0f} with passage chunking)")
    print()


async def _rebuild(db_path: str, store: L1EventStore, batch_size: int, total: int) -> int:
    """Clear existing chunks/vectors, then re-embed all events with progress."""

    print(f"\n[1/3] Clearing existing chunks and vectors ...")
    t0 = time.monotonic()
    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        await db.execute(f"DELETE FROM {EVENT_CHUNKS_TABLE}")
        await db.execute(f"DELETE FROM {EMBEDDING_PROFILES_TABLE}")
        await db.execute(
            f"""
            UPDATE {FACT_EVENTS_TABLE}
            SET embedding_status = ?,
                embedding_profile_id = NULL,
                embedding_chunk_count = 0,
                last_embedded_at = NULL
            WHERE deleted_at IS NULL
            """,
            (EMBEDDING_STATUS_DISABLED,),
        )
        await db.commit()
    if store._vector_index is not None:
        await store._vector_index.clear()
    print(f"      Done in {_format_elapsed(time.monotonic() - t0)}")

    print(f"\n[2/3] Re-embedding {total:,} events (batch_size={batch_size}) ...")
    t_start = time.monotonic()
    processed = 0
    offset = 0

    while True:
        async with sqlite_connection_async(db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT *
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                ORDER BY timestamp ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                (batch_size, offset),
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            break

        events = [store._row_to_memory_event(row) for row in rows]
        await store._maybe_upsert_event_embeddings(events)
        processed += len(events)
        offset += len(rows)

        elapsed = time.monotonic() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        pct = processed * 100 / total
        print(
            f"      {processed:>7,}/{total:,} ({pct:5.1f}%)  "
            f"{rate:.0f} events/s  "
            f"elapsed {_format_elapsed(elapsed)}  "
            f"ETA {_format_elapsed(eta)}",
            end="\r",
            flush=True,
        )

    elapsed = time.monotonic() - t_start
    print()
    print(f"      Embedded {processed:,} events in {_format_elapsed(elapsed)}")

    # Report final stats
    print(f"\n[3/3] Verifying ...")
    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        async with db.execute(f"SELECT count(*) FROM {EVENT_CHUNKS_TABLE}") as cursor:
            chunk_count = (await cursor.fetchone())[0]
        async with db.execute(
            f"SELECT embedding_status, count(*) FROM {FACT_EVENTS_TABLE} GROUP BY embedding_status",
        ) as cursor:
            status_rows = await cursor.fetchall()

    print(f"      Total chunks : {chunk_count:,}")
    for status, count in status_rows:
        print(f"      {status:>10s}   : {count:,}")
    print()
    return processed


async def _run() -> int:
    args = _parse_args()
    if args.base_dir:
        set_runtime_dir(args.base_dir)

    runtime_paths = get_runtime_paths()
    db_path = str(runtime_paths.l1_memory_db_path)

    print(f"L1 database : {db_path}")
    print(f"DB size     : {Path(db_path).stat().st_size / 1024 / 1024:.0f} MB")

    config = get_config()
    llm_pool = create_scenario_llm_pool(config)
    embedding_service = MemoryEmbeddingService(llm_pool)

    store = L1EventStore(
        db_path=db_path,
        embedding_service=embedding_service,
        memory_config_getter=lambda: get_config().agent.memory,
        vector_enabled=True,
        async_embeddings=False,
    )
    await store.initialize()

    try:
        total = await _count_events(db_path)
        print(f"Events      : {total:,}")

        if args.dry_run:
            await _dry_run(store, db_path, total)
            return 0

        processed = await _rebuild(db_path, store, args.batch_size, total)
        print(f"Done! Rebuilt {processed:,} event embeddings with sentence-level chunking.")
    finally:
        await store.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
