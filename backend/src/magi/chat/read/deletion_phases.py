"""Shared database phases for destructive chat operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .schema import (
    CHAT_ATTACHMENTS_TABLE,
    CHAT_CODE_DELEGATION_ARTIFACTS_TABLE,
    CHAT_MESSAGE_ASSET_REFS_TABLE,
    CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE,
    CHAT_MESSAGES_TABLE,
    CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE,
    CHAT_MODEL_CONTEXT_EPOCHS_TABLE,
    CHAT_MODEL_CONTEXT_EVENTS_TABLE,
    CHAT_MODEL_CONTEXT_HEADS_TABLE,
    CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
)
from ...core.code_agent_artifacts import CodeAgentDelegationReference

DELETION_MESSAGE_IDS_TABLE = "chat_deletion_message_ids"
DELETION_TURN_IDS_TABLE = "chat_deletion_turn_ids"


def replace_deletion_scope(
    conn: sqlite3.Connection,
    *,
    message_ids: Iterable[str],
    turn_ids: Iterable[str] = (),
) -> None:
    """Replace the connection-local identity set for one deletion phase."""

    conn.execute(
        f"""
        CREATE TEMP TABLE IF NOT EXISTS {DELETION_MESSAGE_IDS_TABLE} (
            item_id TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        f"""
        CREATE TEMP TABLE IF NOT EXISTS {DELETION_TURN_IDS_TABLE} (
            item_id TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """
    )
    conn.execute(f"DELETE FROM {DELETION_MESSAGE_IDS_TABLE}")
    conn.execute(f"DELETE FROM {DELETION_TURN_IDS_TABLE}")
    normalized_message_ids = sorted(
        {
            str(message_id or "").strip()
            for message_id in message_ids
            if str(message_id or "").strip()
        }
    )
    normalized_turn_ids = sorted(
        {
            str(turn_id or "").strip()
            for turn_id in turn_ids
            if str(turn_id or "").strip()
        }
    )
    conn.executemany(
        f"INSERT INTO {DELETION_MESSAGE_IDS_TABLE}(item_id) VALUES (?)",
        [(message_id,) for message_id in normalized_message_ids],
    )
    conn.executemany(
        f"INSERT INTO {DELETION_TURN_IDS_TABLE}(item_id) VALUES (?)",
        [(turn_id,) for turn_id in normalized_turn_ids],
    )


def redact_scoped_messages(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    session_id: str,
) -> None:
    """Hide sensitive message data while retaining private asset retry records."""

    conn.execute(
        f"""
        UPDATE {CHAT_MESSAGES_TABLE}
        SET content_text = '',
            payload_json = '{{}}',
            is_visible = 0,
            replaces_message_id = NULL,
            replaced_by_message_id = NULL,
            persona_id = NULL,
            reply_to_message_id = NULL,
            label_json = NULL
        WHERE user_id = ?
          AND session_id = ?
          AND message_id IN (
              SELECT item_id FROM {DELETION_MESSAGE_IDS_TABLE}
          )
        """,
        (user_id, session_id),
    )
    conn.execute(
        f"""
        UPDATE {CHAT_MESSAGES_TABLE}
        SET reply_to_message_id = NULL
        WHERE user_id = ?
          AND session_id = ?
          AND reply_to_message_id IN (
              SELECT item_id FROM {DELETION_MESSAGE_IDS_TABLE}
          )
        """,
        (user_id, session_id),
    )
    conn.execute(
        f"""
        DELETE FROM {CHAT_ATTACHMENTS_TABLE}
        WHERE user_id = ?
          AND session_id = ?
          AND message_id IN (
              SELECT item_id FROM {DELETION_MESSAGE_IDS_TABLE}
          )
        """,
        (user_id, session_id),
    )


def delete_scoped_asset_references(conn: sqlite3.Connection) -> None:
    """Finalize files already deleted by removing their private retry records."""

    conn.execute(
        f"""
        DELETE FROM {CHAT_MESSAGE_ASSET_REFS_TABLE}
        WHERE message_id IN (
            SELECT item_id FROM {DELETION_MESSAGE_IDS_TABLE}
        )
        """
    )


def delete_scoped_code_delegation_references(
    conn: sqlite3.Connection,
) -> None:
    """Remove message ownership only after private artifact cleanup succeeds."""

    conn.execute(
        f"""
        DELETE FROM {CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE}
        WHERE message_id IN (
            SELECT item_id FROM {DELETION_MESSAGE_IDS_TABLE}
        )
        """
    )


def delete_code_delegation_artifact_records(
    conn: sqlite3.Connection,
    *,
    references: Iterable[CodeAgentDelegationReference],
) -> None:
    """Remove exact orphan-cleanup records after their paths are gone."""

    conn.executemany(
        f"""
        DELETE FROM {CHAT_CODE_DELEGATION_ARTIFACTS_TABLE}
        WHERE workspace_path = ?
          AND session_id = ? COLLATE NOCASE
          AND delegation_id = ?
        """,
        [
            (
                reference.workspace_path,
                reference.session_id,
                reference.delegation_id,
            )
            for reference in references
        ],
    )


def delete_scoped_message_tombstones(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    session_id: str,
) -> None:
    """Remove redacted message rows after external cleanup is complete."""

    conn.execute(
        f"""
        DELETE FROM {CHAT_MESSAGES_TABLE}
        WHERE user_id = ?
          AND session_id = ?
          AND message_id IN (
              SELECT item_id FROM {DELETION_MESSAGE_IDS_TABLE}
          )
        """,
        (user_id, session_id),
    )


def delete_session_model_context(
    conn: sqlite3.Connection,
    *,
    session_id: str,
) -> int:
    """Physically clear every model-visible context record for one session."""

    deleted = 0
    for table in (
        CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE,
        CHAT_MODEL_CONTEXT_EPOCHS_TABLE,
        CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
        CHAT_MODEL_CONTEXT_EVENTS_TABLE,
        CHAT_MODEL_CONTEXT_HEADS_TABLE,
    ):
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE session_id = ? COLLATE NOCASE",
            (session_id,),
        )
        deleted += int(cursor.rowcount or 0)
    return deleted


def delete_all_model_context(conn: sqlite3.Connection) -> int:
    """Physically clear every model-visible context record."""

    deleted = 0
    for table in (
        CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE,
        CHAT_MODEL_CONTEXT_EPOCHS_TABLE,
        CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
        CHAT_MODEL_CONTEXT_EVENTS_TABLE,
        CHAT_MODEL_CONTEXT_HEADS_TABLE,
    ):
        cursor = conn.execute(f"DELETE FROM {table}")
        deleted += int(cursor.rowcount or 0)
    return deleted


__all__ = [
    "DELETION_MESSAGE_IDS_TABLE",
    "DELETION_TURN_IDS_TABLE",
    "delete_code_delegation_artifact_records",
    "delete_all_model_context",
    "delete_session_model_context",
    "delete_scoped_asset_references",
    "delete_scoped_code_delegation_references",
    "delete_scoped_message_tombstones",
    "redact_scoped_messages",
    "replace_deletion_scope",
]
