#!/usr/bin/env python3
"""Rebuild episodic memory from existing L1 events and L2 entity associations.

Episode formation is purely algorithmic (time-gap clustering + entity overlap),
no LLM calls required.  This script:

1. Clears existing episodes / episode_events / episodes_fts
2. Scans L1 fact_events in chronological order
3. Looks up entity associations from l1_event_entities
4. Feeds EpisodeCandidateJob batches into assign_events_to_episode()
5. Runs consolidate_episodes() to promote / merge / invalidate
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
from magi.memory.l1.event_store import L1EventStore  # noqa: E402
from magi.memory.l2.episode_formation import (  # noqa: E402
    assign_events_to_episode,
    consolidate_episodes,
)
from magi.memory.l2.models import EpisodeCandidateJob  # noqa: E402
from magi.memory.l2.store import L2CognitionStore  # noqa: E402
from magi.utils.runtime import get_runtime_paths, set_runtime_dir  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild episodic memory from L1 events + L2 entity associations."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of L1 events to process per batch (default: 200).",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Optional Magi runtime home override (defaults to ~/.magi).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count events and show plan without modifying data.",
    )
    parser.add_argument(
        "--episode-type",
        default="activity",
        help="Episode type hint for formation (default: activity).",
    )
    return parser.parse_args()


async def _clear_episodes(db_path: str) -> None:
    """Delete all rows from episodes, episode_events, and episodes_fts."""
    async with sqlite_connection_async(db_path) as db:
        await db.execute("DELETE FROM episode_events")
        await db.execute("DELETE FROM episodes")
        # FTS5 content table — rebuild to clear
        try:
            await db.execute("DELETE FROM episodes_fts")
        except Exception:
            pass
        await db.commit()


async def _count_l1_events(l1_store: L1EventStore) -> int:
    return await l1_store.count_events()


async def _scan_events_asc(db_path: str, batch_size: int, offset: int) -> list[dict]:
    """Scan L1 events in ascending timestamp order."""
    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT event_id, timestamp FROM fact_events"
            " WHERE deleted_at IS NULL"
            " ORDER BY timestamp ASC"
            " LIMIT ? OFFSET ?",
            (batch_size, offset),
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"event_id": row["event_id"], "timestamp": row["timestamp"]} for row in rows]


async def _run() -> int:
    args = _parse_args()
    if args.base_dir:
        set_runtime_dir(args.base_dir)

    runtime_paths = get_runtime_paths()
    config = get_config()
    memory_cfg = config.agent.memory

    l1_db_path = str(runtime_paths.l1_memory_db_path)
    l2_db_path = str(runtime_paths.memory_db_path)
    batch_size = max(1, args.batch_size)
    episode_type = args.episode_type

    # ── Initialise stores ────────────────────────────────────────
    l1_store = L1EventStore(
        db_path=l1_db_path,
        memory_config_getter=lambda: get_config().agent.memory,
        vector_enabled=False,
        async_embeddings=False,
    )
    await l1_store.initialize()

    l2_store = L2CognitionStore(db_path=l2_db_path)
    await l2_store.initialize()

    # ── Count events ─────────────────────────────────────────────
    total = await _count_l1_events(l1_store)
    print(f"L1 events: {total}")
    print(f"L1 db:     {l1_db_path}")
    print(f"L2 db:     {l2_db_path}")
    print(f"Batch:     {batch_size}")
    print(f"Type:      {episode_type}")

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return 0

    if total == 0:
        print("No L1 events found — nothing to rebuild.")
        return 0

    # ── Clear existing episodes ──────────────────────────────────
    print("\nClearing existing episodes …")
    await _clear_episodes(l2_db_path)
    print("Done.")

    # ── Scan & assign ────────────────────────────────────────────
    print(f"\nProcessing {total} events …")
    t0 = time.monotonic()
    offset = 0
    processed = 0
    episodes_created = 0

    while True:
        events = await _scan_events_asc(l1_db_path, batch_size, offset)
        if not events:
            break

        event_ids = [e["event_id"] for e in events]
        entity_map = await l1_store.get_event_entity_ids(event_ids)

        for ev in events:
            eid = ev["event_id"]
            job = EpisodeCandidateJob(
                event_id=eid,
                event_timestamp=ev["timestamp"],
                entity_ids=entity_map.get(eid, []),
                episode_type_hint=episode_type,
            )
            result = await assign_events_to_episode(l2_store, [job])
            if result:
                episodes_created += 1

        processed += len(events)
        elapsed = time.monotonic() - t0
        eps = processed / elapsed if elapsed > 0 else 0
        print(
            f"  {processed}/{total} events"
            f"  ({processed * 100 // total}%)"
            f"  {eps:.0f} evt/s",
            end="\r",
        )

        if len(events) < batch_size:
            break
        offset += batch_size

    elapsed = time.monotonic() - t0
    print(f"\n\nAssignment done: {processed} events → {episodes_created} episode assignments in {elapsed:.1f}s")

    # ── Consolidate ──────────────────────────────────────────────
    print("\nConsolidating episodes …")
    stats = await consolidate_episodes(l2_store)
    print(f"  Promoted:    {stats.promoted}")
    print(f"  Merged:      {stats.merged}")
    print(f"  Invalidated: {stats.invalidated}")

    # ── Final counts ─────────────────────────────────────────────
    async with sqlite_connection_async(l2_db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM episodes") as cur:
            ep_total = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM episodes WHERE status = 'active'") as cur:
            ep_active = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM episodes WHERE status = 'candidate'") as cur:
            ep_candidate = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM episode_events") as cur:
            link_total = (await cur.fetchone())[0]

    print(f"\nFinal state:")
    print(f"  Episodes total:     {ep_total}")
    print(f"  Episodes active:    {ep_active}")
    print(f"  Episodes candidate: {ep_candidate}")
    print(f"  Event memberships:  {link_total}")

    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
