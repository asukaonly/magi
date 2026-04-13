#!/usr/bin/env python3
"""Backfill l1_event_entities from entity_mentions.

The l1_event_entities table was introduced after L2 extraction had already
completed, leaving it empty.  This script reads resolved entity mentions
from memory.db and inserts the (event_id, entity_id) mappings into the
l1_events.db table so that entity co-occurrence expansion works in retrieval.

Usage:
    python scripts/backfill-event-entities.py [--data-dir ~/.magi/data/memory] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path


DEFAULT_DATA_DIR = Path.home() / ".magi" / "data" / "memory"


def backfill(
    *,
    memory_db: Path,
    l1_db: Path,
    dry_run: bool = False,
    batch_size: int = 5000,
) -> int:
    """Read entity_mentions from *memory_db* and write mappings to *l1_db*.

    Returns the number of rows inserted.
    """
    if not memory_db.exists():
        raise FileNotFoundError(f"memory.db not found: {memory_db}")
    if not l1_db.exists():
        raise FileNotFoundError(f"l1_events.db not found: {l1_db}")

    # ── Read entity mentions ──
    src = sqlite3.connect(str(memory_db))
    src.row_factory = sqlite3.Row
    cursor = src.execute(
        "SELECT resolved_entity_id, entity_type, confidence, evidence_event_ids "
        "FROM entity_mentions "
        "WHERE resolved_entity_id IS NOT NULL"
    )

    now = time.time()
    mappings: list[tuple[str, str, str | None, float | None, float]] = []
    mention_count = 0

    for row in cursor:
        mention_count += 1
        entity_id = row["resolved_entity_id"]
        entity_type = row["entity_type"]
        confidence = row["confidence"]
        try:
            event_ids = json.loads(row["evidence_event_ids"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event_ids, list):
            continue
        for eid in event_ids:
            if eid:
                mappings.append((str(eid), entity_id, entity_type, confidence, now))

    src.close()
    print(f"Read {mention_count:,} entity mentions → {len(mappings):,} (event, entity) mappings")

    if dry_run:
        print("[dry-run] Skipping write.")
        return 0

    # ── Write to l1_event_entities ──
    dst = sqlite3.connect(str(l1_db))
    total_inserted = 0

    for i in range(0, len(mappings), batch_size):
        batch = mappings[i : i + batch_size]
        dst.executemany(
            "INSERT OR IGNORE INTO l1_event_entities "
            "(event_id, entity_id, entity_type, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            batch,
        )
        dst.commit()
        total_inserted += dst.total_changes
        done = min(i + batch_size, len(mappings))
        print(f"  Written {done:,}/{len(mappings):,} mappings ({total_inserted:,} new rows)")

    dst.close()
    print(f"Done. Inserted {total_inserted:,} rows into l1_event_entities.")
    return total_inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill l1_event_entities from entity_mentions.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Memory data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Read only, do not write.")
    args = parser.parse_args()

    data_dir: Path = args.data_dir
    memory_db = data_dir / "memory.db"
    l1_db = data_dir / "l1_events.db"

    print(f"Source: {memory_db}")
    print(f"Target: {l1_db}")

    backfill(memory_db=memory_db, l1_db=l1_db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
