#!/usr/bin/env python3
"""Backfill L1 evidence annotations for existing fact_events rows."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_SRC_DIR = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC_DIR))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill evidence classification and policy columns for L1 events."
    )
    parser.add_argument(
        "--db-path",
        help="L1 SQLite database path. Defaults to the active Magi runtime L1 DB.",
    )
    parser.add_argument("--user-id", help="Limit backfill to one user id.")
    parser.add_argument(
        "--source",
        action="append",
        dest="source_filters",
        help="Limit backfill to one source. Repeat for multiple sources.",
    )
    parser.add_argument("--event-type", help="Limit backfill to one event type.")
    parser.add_argument("--start-time", type=float, help="Minimum event timestamp.")
    parser.add_argument("--end-time", type=float, help="Maximum event timestamp.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per batch.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Reclassify all matching rows, including current classified rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify matching rows and report counts without updating the DB.",
    )
    return parser.parse_args()


def _default_l1_db_path() -> Path:
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import get_runtime_paths

    runtime_paths = get_runtime_paths()
    l1_target = next(target for target in MIGRATION_TARGETS if target.name == "l1")
    run_upgrade_head(runtime_paths, targets=(l1_target,))
    return runtime_paths.l1_memory_db_path


async def _run(args: argparse.Namespace) -> int:
    from magi.memory.l1.event_store import L1EventStore

    db_path = Path(args.db_path).expanduser() if args.db_path else _default_l1_db_path()
    store = L1EventStore(
        db_path=str(db_path),
        vector_enabled=False,
        async_embeddings=False,
    )
    await store.initialize()
    try:
        result = await store.backfill_evidence_annotations(
            user_id=args.user_id,
            source_filters=args.source_filters,
            event_type=args.event_type,
            start_time=args.start_time,
            end_time=args.end_time,
            batch_size=args.batch_size,
            stale_only=not args.all,
            dry_run=args.dry_run,
        )
    finally:
        await store.shutdown()

    payload = asdict(result)
    payload["db_path"] = str(db_path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if result.errors else 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
