"""Preserve the current center's remote cleanup identities across memory replacement."""

from contextlib import closing
from pathlib import Path
import sqlite3

from ...core.sqlite import SqliteProfile, sqlite_transaction


def carry_forward_vector_cleanup(*, live_path: Path, staged_path: Path) -> None:
    """Seed an empty generation in the staged DB; never copy vector payloads or intents.

    The caller owns an offline, fingerprinted restore transaction. Its exact rollback
    database remains untouched. Remote collections belong to this center, not to the
    imported backup, so only the live database can supply their cleanup identities.
    """
    with closing(sqlite3.connect(live_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        namespaces = source.execute(
            "SELECT namespace,backend_identity,instance_id,generation,revision FROM vector_projection_namespaces"
        ).fetchall()
        collections = source.execute(
            "SELECT namespace,collection_id,generation FROM vector_projection_collections"
        ).fetchall()
    with sqlite_transaction(
        staged_path, profile=SqliteProfile(journal_mode="DELETE", synchronous="FULL")
    ) as target:
        target.execute("BEGIN IMMEDIATE")
        for table in (
            "vector_projection_operations",
            "vector_projection_entries",
            "vector_projection_collections",
            "vector_projection_namespaces",
        ):
            target.execute(f"DELETE FROM {table}")
        target.executemany(
            "INSERT INTO vector_projection_namespaces(namespace,backend_identity,instance_id,generation,revision) VALUES (?,?,?,?,?)",
            [(row[0], row[1], row[2], int(row[3]) + 1, int(row[4]) + 1) for row in namespaces],
        )
        target.executemany(
            "INSERT INTO vector_projection_collections(namespace,collection_id,generation) VALUES (?,?,?)",
            [tuple(row) for row in collections],
        )
        target.commit()
