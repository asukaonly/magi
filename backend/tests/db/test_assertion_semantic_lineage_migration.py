"""Schema contract for assertion semantic lineage and target windows."""

from __future__ import annotations

import asyncio
import sqlite3

from _shared.memory_schema import apply_memory_shared_schema
from magi.db.migrations.memory_shared.versions.v43_assertion_semantic_lineage import (
    revision,
)


def test_assertion_semantic_lineage_is_release_head(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(db_path)))

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]: row[2]
            for row in connection.execute(
                "PRAGMA table_info(tom_trait_assertions)"
            ).fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(tom_trait_assertions)"
            ).fetchall()
        }
    finally:
        connection.close()

    assert revision == "v43_assertion_semantic_lineage"
    assert columns["semantic_lineage_key"] == "TEXT"
    assert columns["target_window_json"] == "TEXT"
    assert "idx_tom_assertions_semantic_lineage" in indexes
