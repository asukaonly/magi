#!/usr/bin/env python3
"""Migrate existing vec0 tables to include a user_id partition key.

This script:
1. Reads all vectors from the old vec0 table (without partition key)
2. Joins with fact_events to get user_id for each vector
3. Drops the old vec0 table
4. Re-creates it with `user_id text partition key`
5. Re-inserts all vectors with their user_id

No re-embedding is needed — the existing vectors are preserved as-is.

Usage:
    python scripts/migrate_vec_partition_key.py [--db-path PATH]

Default db-path: ~/.magi/data/memory/l1_events.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

# Ensure the magi package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

import sqlite_vec  # type: ignore[import-untyped]


def get_default_db_path() -> str:
    return os.path.expanduser("~/.magi/data/memory/l1_events.db")


REGISTRY_TABLE = "l1_event_chunk_vectors"
ENTITY_COLUMN = "chunk_id"


def migrate(db_path: str, *, batch_size: int = 2000) -> None:
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    print(f"Opening database: {db_path}")
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.enable_load_extension(True)
    db.load_extension(sqlite_vec.loadable_path())
    db.enable_load_extension(False)

    # Discover vec0 tables from registry
    vec_tables = db.execute(
        f"SELECT DISTINCT vec_table FROM {REGISTRY_TABLE}"
    ).fetchall()
    vec_table_names = [row["vec_table"] for row in vec_tables]

    if not vec_table_names:
        print("No vec tables found in registry. Nothing to migrate.")
        db.close()
        return

    print(f"Found vec tables: {vec_table_names}")

    for vec_table in vec_table_names:
        _migrate_one_table(db, vec_table, batch_size=batch_size)

    db.close()
    print("\nMigration complete.")


def _migrate_one_table(db: sqlite3.Connection, vec_table: str, *, batch_size: int) -> None:
    # Check if the table already has a partition key by inspecting shadow tables
    # vec0 with partition key creates a `_partition_key_values` shadow table
    shadow_pk_table = f"{vec_table}_partition_key_values"
    has_pk = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (shadow_pk_table,),
    ).fetchone()
    if has_pk:
        print(f"\n[{vec_table}] Already has partition key — skipping.")
        return

    # Detect dimension from the vec0 table info
    info_table = f"{vec_table}_info"
    info_rows = db.execute(f'SELECT * FROM "{info_table}"').fetchall()
    dimension = None
    for row in info_rows:
        key = row[0] if isinstance(row, tuple) else row["key"]
        val = row[1] if isinstance(row, tuple) else row["value"]
        if key == "num_dimensions":
            dimension = int(val)
            break
    if dimension is None:
        # Fallback: read one vector and infer dimension from byte length
        sample = db.execute(f'SELECT embedding FROM "{vec_table}" LIMIT 1').fetchone()
        if sample:
            # float32 = 4 bytes each
            dimension = len(sample[0]) // 4
        else:
            print(f"\n[{vec_table}] Empty table — skipping.")
            return

    print(f"\n[{vec_table}] Dimension: {dimension}")

    # Count total vectors
    total = db.execute(f'SELECT count(*) FROM "{vec_table}_rowids"').fetchone()[0]
    print(f"[{vec_table}] Total vectors: {total}")

    # Read all (rowid, embedding) and join to get user_id
    # Registry: chunk_id -> event_id prefix (before ::)
    # fact_events: event_id -> user_id
    print(f"[{vec_table}] Reading vectors and resolving user_id...")
    t0 = time.time()

    rows = db.execute(
        f"""
        SELECT r.vec_rowid, v.embedding, fe.user_id
        FROM {REGISTRY_TABLE} r
        JOIN "{vec_table}" v ON v.rowid = r.vec_rowid
        LEFT JOIN fact_events fe
            ON fe.event_id = CASE
                WHEN INSTR(r.{ENTITY_COLUMN}, '::') > 0
                THEN SUBSTR(r.{ENTITY_COLUMN}, 1, INSTR(r.{ENTITY_COLUMN}, '::') - 1)
                ELSE r.{ENTITY_COLUMN}
            END
        WHERE r.vec_table = ?
        """,
        (vec_table,),
    ).fetchall()

    t1 = time.time()
    print(f"[{vec_table}] Read {len(rows)} vectors in {t1 - t0:.1f}s")

    if not rows:
        print(f"[{vec_table}] No vectors to migrate.")
        return

    # Count user_id stats
    null_user_count = sum(1 for r in rows if r["user_id"] is None)
    if null_user_count:
        print(f"[{vec_table}] WARNING: {null_user_count}/{len(rows)} vectors have NULL user_id")

    # Drop old vec0 table
    print(f"[{vec_table}] Dropping old vec0 table...")
    db.execute(f'DROP TABLE IF EXISTS "{vec_table}"')
    db.commit()

    # Recreate with partition key
    print(f"[{vec_table}] Creating new vec0 table with partition key...")
    db.execute(
        f'CREATE VIRTUAL TABLE "{vec_table}" USING vec0(embedding float[{dimension}], user_id text partition key)'
    )
    db.commit()

    # Batch insert
    print(f"[{vec_table}] Inserting vectors...")
    t2 = time.time()
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        for row in batch:
            user_id = row["user_id"] if row["user_id"] is not None else "__unknown__"
            db.execute(
                f'INSERT INTO "{vec_table}"(rowid, embedding, user_id) VALUES (?, ?, ?)',
                (row["vec_rowid"], row["embedding"], user_id),
            )
        db.commit()
        inserted += len(batch)
        elapsed = time.time() - t2
        rate = inserted / elapsed if elapsed > 0 else 0
        print(f"  {inserted}/{len(rows)} ({rate:.0f} vec/s)")

    t3 = time.time()
    print(f"[{vec_table}] Inserted {inserted} vectors in {t3 - t2:.1f}s")

    # Verify
    new_count = db.execute(f'SELECT count(*) FROM "{vec_table}_rowids"').fetchone()[0]
    print(f"[{vec_table}] Verification: {new_count} vectors in new table (expected {len(rows)})")
    if new_count != len(rows):
        print(f"[{vec_table}] ERROR: count mismatch!")
        sys.exit(1)

    # Quick KNN sanity check with partition key
    sample_user = None
    for r in rows:
        if r["user_id"] is not None:
            sample_user = r["user_id"]
            break
    if sample_user:
        sample_vec = rows[0]["embedding"]
        knn_result = db.execute(
            f'SELECT rowid, distance FROM "{vec_table}" WHERE embedding MATCH ? AND k = 3 AND user_id = ?',
            (sample_vec, sample_user),
        ).fetchall()
        print(f"[{vec_table}] KNN sanity check (user_id={sample_user!r}): {len(knn_result)} results")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate vec0 tables to use partition key")
    parser.add_argument(
        "--db-path",
        default=get_default_db_path(),
        help="Path to l1_events.db (default: ~/.magi/data/memory/l1_events.db)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Number of vectors per commit batch (default: 2000)",
    )
    args = parser.parse_args()
    migrate(args.db_path, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
