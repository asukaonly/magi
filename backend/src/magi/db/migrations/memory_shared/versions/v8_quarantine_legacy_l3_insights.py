"""Quarantine legacy L3 insights without correction dependencies.

Revision ID: v8_quarantine_legacy_l3_insights
Revises: v7_l3_derivation_state
"""

from __future__ import annotations

import re

import sqlite_vec
from alembic import op

revision = "v8_quarantine_legacy_l3_insights"
down_revision = "v7_l3_derivation_state"
branch_labels = None
depends_on = None


_SAFE_VECTOR_TABLE = re.compile(r"l3_summary_chunk_vec_[a-z0-9_]+")


QUARANTINE_SQL = """
UPDATE summaries
SET derivation_state = 'stale',
    embedding_status = 'disabled',
    embedding_profile_id = NULL,
    embedding_chunk_count = 0,
    last_embedded_at = NULL
WHERE summary_type = 'insight'
  AND derivation_state = 'current'
  AND (
      NOT EXISTS (
          SELECT 1
          FROM memory_derivation_dependencies AS dependencies
          WHERE dependencies.artifact_kind = 'l3_insight'
            AND dependencies.artifact_id = summaries.summary_id
      )
      OR EXISTS (
          SELECT 1
          FROM memory_derivation_dependencies AS dependencies
          WHERE dependencies.artifact_kind = 'l3_insight'
            AND dependencies.artifact_id = summaries.summary_id
            AND NOT (
                (
                    dependencies.source_kind = 'assertion'
                    AND EXISTS (
                        SELECT 1
                        FROM tom_trait_assertions AS assertions
                        WHERE assertions.assertion_id = dependencies.source_id
                          AND assertions.status IN ('tentative', 'corroborated', 'stable')
                          AND (assertions.valid_to IS NULL OR assertions.valid_to > unixepoch('subsec'))
                          AND (assertions.expires_at IS NULL OR assertions.expires_at > unixepoch('subsec'))
                    )
                )
                OR (
                    dependencies.source_kind = 'edge'
                    AND EXISTS (
                        SELECT 1
                        FROM knowledge_graph AS edges
                        WHERE edges.triple_id = dependencies.source_id
                          AND edges.status = 'active'
                          AND (edges.valid_to IS NULL OR edges.valid_to > unixepoch('subsec'))
                          AND (edges.expires_at IS NULL OR edges.expires_at > unixepoch('subsec'))
                    )
                )
            )
      )
  );
"""


SEARCH_ARTIFACT_SQL = """
DELETE FROM l3_summary_chunks
WHERE summary_id IN (
    SELECT summary_id FROM summaries WHERE derivation_state = 'stale'
);

DELETE FROM l3_summaries_fts
WHERE summary_id IN (
    SELECT summary_id FROM summaries WHERE derivation_state = 'stale'
);
"""


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.executescript(QUARANTINE_SQL)
    _delete_stale_vectors(connection)
    connection.executescript(SEARCH_ARTIFACT_SQL)


def _delete_stale_vectors(connection) -> None:
    registry_exists = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'l3_summary_chunk_vectors'
        """
    ).fetchone()
    if registry_exists is None:
        return

    rows = connection.execute(
        """
        SELECT vectors.vec_rowid, vectors.vec_table
        FROM l3_summary_chunk_vectors AS vectors
        JOIN l3_summary_chunks AS chunks
          ON chunks.chunk_id = vectors.chunk_id
        JOIN summaries
          ON summaries.summary_id = chunks.summary_id
        WHERE summaries.derivation_state = 'stale'
        """
    ).fetchall()
    if not rows:
        return

    connection.enable_load_extension(True)
    try:
        connection.load_extension(sqlite_vec.loadable_path())
    finally:
        connection.enable_load_extension(False)

    rows_by_table: dict[str, list[int]] = {}
    for vec_rowid, vec_table in rows:
        table_name = str(vec_table)
        if _SAFE_VECTOR_TABLE.fullmatch(table_name):
            rows_by_table.setdefault(table_name, []).append(int(vec_rowid))
    for table_name, rowids in rows_by_table.items():
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if table_exists is None:
            continue
        placeholders = ", ".join("?" for _ in rowids)
        connection.execute(
            f'DELETE FROM "{table_name}" WHERE rowid IN ({placeholders})',
            tuple(rowids),
        )

    vector_rowids = [int(row[0]) for row in rows]
    placeholders = ", ".join("?" for _ in vector_rowids)
    connection.execute(
        f"DELETE FROM l3_summary_chunk_vectors WHERE vec_rowid IN ({placeholders})",
        tuple(vector_rowids),
    )


def downgrade() -> None:
    # The migration cannot distinguish a pre-existing stale insight from one
    # quarantined here, so restoring visibility would be unsafe.
    pass
