"""Indexed ownership queries for private code-delegation artifacts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from ...core.code_agent_artifacts import CodeAgentDelegationReference
from .schema import (
    CHAT_CODE_DELEGATION_ARTIFACTS_TABLE,
    CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE,
    CHAT_MESSAGES_TABLE,
    CHAT_SESSIONS_TABLE,
)

TARGET_MESSAGE_IDS_TABLE = "chat_code_target_message_ids"
TARGET_TURN_IDS_TABLE = "chat_code_target_turn_ids"
CANDIDATE_ARTIFACTS_TABLE = "chat_code_candidate_artifacts"


def _replace_string_scope(
    conn: sqlite3.Connection,
    *,
    table: str,
    values: Iterable[str],
) -> None:
    conn.execute(
        f"""
        CREATE TEMP TABLE IF NOT EXISTS {table} (
            item_id TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """
    )
    conn.execute(f"DELETE FROM {table}")
    normalized = sorted(
        {
            value
            for raw_value in values
            if (value := str(raw_value or "").strip())
        }
    )
    conn.executemany(
        f"INSERT INTO {table}(item_id) VALUES (?)",
        [(value,) for value in normalized],
    )


def unshared_code_delegation_references(
    conn: sqlite3.Connection,
    *,
    message_ids: Iterable[str] = (),
    turn_ids: Iterable[str] = (),
    session_id: str | None = None,
    all_artifacts: bool = False,
) -> list[CodeAgentDelegationReference]:
    """Return exact artifacts with no visible owner outside the target scope."""

    _replace_string_scope(
        conn,
        table=TARGET_MESSAGE_IDS_TABLE,
        values=message_ids,
    )
    _replace_string_scope(
        conn,
        table=TARGET_TURN_IDS_TABLE,
        values=turn_ids,
    )
    if all_artifacts:
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {TARGET_MESSAGE_IDS_TABLE}(item_id)
            SELECT message_id
            FROM {CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE}
            """
        )
    conn.execute(
        f"""
        CREATE TEMP TABLE IF NOT EXISTS {CANDIDATE_ARTIFACTS_TABLE} (
            workspace_path TEXT NOT NULL,
            session_id TEXT COLLATE NOCASE NOT NULL,
            delegation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            PRIMARY KEY (workspace_path, session_id, delegation_id)
        ) WITHOUT ROWID
        """
    )
    conn.execute(f"DELETE FROM {CANDIDATE_ARTIFACTS_TABLE}")
    conn.execute(
        f"""
        INSERT OR IGNORE INTO {CANDIDATE_ARTIFACTS_TABLE}(
            workspace_path,
            session_id,
            delegation_id,
            turn_id
        )
        SELECT
            refs.workspace_path,
            refs.session_id,
            refs.delegation_id,
            refs.turn_id
        FROM {CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE} AS refs
        JOIN {TARGET_MESSAGE_IDS_TABLE} AS target
          ON target.item_id = refs.message_id
        """
    )
    if all_artifacts:
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {CANDIDATE_ARTIFACTS_TABLE}(
                workspace_path,
                session_id,
                delegation_id,
                turn_id
            )
            SELECT workspace_path, session_id, delegation_id, turn_id
            FROM {CHAT_CODE_DELEGATION_ARTIFACTS_TABLE}
            """
        )
    else:
        normalized_session_id = str(session_id or "").strip()
        if normalized_session_id:
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {CANDIDATE_ARTIFACTS_TABLE}(
                    workspace_path,
                    session_id,
                    delegation_id,
                    turn_id
                )
                SELECT workspace_path, session_id, delegation_id, turn_id
                FROM {CHAT_CODE_DELEGATION_ARTIFACTS_TABLE}
                WHERE session_id = ? COLLATE NOCASE
                """,
                (normalized_session_id,),
            )
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {CANDIDATE_ARTIFACTS_TABLE}(
                workspace_path,
                session_id,
                delegation_id,
                turn_id
            )
            SELECT
                artifact.workspace_path,
                artifact.session_id,
                artifact.delegation_id,
                artifact.turn_id
            FROM {CHAT_CODE_DELEGATION_ARTIFACTS_TABLE} AS artifact
            JOIN {TARGET_TURN_IDS_TABLE} AS target
              ON target.item_id = artifact.turn_id
            """
        )

    rows = conn.execute(
        f"""
        SELECT
            candidate.workspace_path,
            candidate.session_id,
            candidate.delegation_id,
            candidate.turn_id
        FROM {CANDIDATE_ARTIFACTS_TABLE} AS candidate
        WHERE NOT EXISTS (
            SELECT 1
            FROM {CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE} AS owner
                 INDEXED BY idx_chat_message_code_delegation_scope
            JOIN {CHAT_MESSAGES_TABLE} AS owner_message
              ON owner_message.message_id = owner.message_id
            JOIN {CHAT_SESSIONS_TABLE} AS owner_session
              ON owner_session.session_id = owner_message.session_id
            LEFT JOIN {TARGET_MESSAGE_IDS_TABLE} AS target_owner
              ON target_owner.item_id = owner.message_id
            WHERE owner.workspace_path = candidate.workspace_path
              AND owner.session_id = candidate.session_id COLLATE NOCASE
              AND owner.delegation_id = candidate.delegation_id
              AND target_owner.item_id IS NULL
              AND owner_message.is_visible = 1
              AND owner_session.deleted_at_ms IS NULL
        )
        ORDER BY
            candidate.workspace_path,
            candidate.session_id,
            candidate.delegation_id
        """
    ).fetchall()
    return [
        CodeAgentDelegationReference(
            workspace_path=str(row["workspace_path"]),
            session_id=str(row["session_id"]),
            delegation_id=str(row["delegation_id"]),
            turn_id=str(row["turn_id"]),
        )
        for row in rows
    ]


__all__ = ["unshared_code_delegation_references"]
