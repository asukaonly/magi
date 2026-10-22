"""Shared database phases for destructive chat operations."""

from __future__ import annotations

from ..statements import statement, mysql_ascii_lower

from ..relational import ChatReadConnection

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
    CHAT_MODEL_CONTEXT_REVISIONS_TABLE,
    CHAT_MODEL_CONTEXT_RUN_HEADS_TABLE,
    CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
)
from ....core.code_agent_artifacts import CodeAgentDelegationReference

DELETION_MESSAGE_IDS_TABLE = "chat_deletion_message_ids"
DELETION_TURN_IDS_TABLE = "chat_deletion_turn_ids"


def replace_deletion_scope(
    conn: ChatReadConnection,
    *,
    message_ids: Iterable[str],
    turn_ids: Iterable[str] = (),
) -> None:
    """Replace the connection-local identity set for one deletion phase."""

    conn.execute(
        statement("""
        CREATE TEMP TABLE IF NOT EXISTS {part0} (
            item_id TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """, mysql="""
        CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
            item_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(HEX(item_id),256)) STORED,
            UNIQUE KEY(__key)
        )
        """, part0=DELETION_MESSAGE_IDS_TABLE)
    )
    conn.execute(
        statement("""
        CREATE TEMP TABLE IF NOT EXISTS {part0} (
            item_id TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """, mysql="""
        CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
            item_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(HEX(item_id),256)) STORED,
            UNIQUE KEY(__key)
        )
        """, part0=DELETION_TURN_IDS_TABLE)
    )
    conn.execute(statement("""DELETE FROM {part0}""", part0=DELETION_MESSAGE_IDS_TABLE))
    conn.execute(statement("""DELETE FROM {part0}""", part0=DELETION_TURN_IDS_TABLE))
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
        statement("""INSERT INTO {part0}(item_id) VALUES (?)""", part0=DELETION_MESSAGE_IDS_TABLE),
        [(message_id,) for message_id in normalized_message_ids],
    )
    conn.executemany(
        statement("""INSERT INTO {part0}(item_id) VALUES (?)""", part0=DELETION_TURN_IDS_TABLE),
        [(turn_id,) for turn_id in normalized_turn_ids],
    )


def redact_scoped_messages(
    conn: ChatReadConnection,
    *,
    user_id: str,
    session_id: str,
) -> None:
    """Hide sensitive message data while retaining private asset retry records."""

    conn.execute(
        statement("""
        UPDATE {part0}
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
              SELECT item_id FROM {part1}
          )
        """, part0=CHAT_MESSAGES_TABLE, part1=DELETION_MESSAGE_IDS_TABLE),
        (user_id, session_id),
    )
    conn.execute(
        statement("""
        UPDATE {part0}
        SET reply_to_message_id = NULL
        WHERE user_id = ?
          AND session_id = ?
          AND reply_to_message_id IN (
              SELECT item_id FROM {part1}
          )
        """, part0=CHAT_MESSAGES_TABLE, part1=DELETION_MESSAGE_IDS_TABLE),
        (user_id, session_id),
    )
    conn.execute(
        statement("""
        DELETE FROM {part0}
        WHERE user_id = ?
          AND session_id = ?
          AND message_id IN (
              SELECT item_id FROM {part1}
          )
        """, part0=CHAT_ATTACHMENTS_TABLE, part1=DELETION_MESSAGE_IDS_TABLE),
        (user_id, session_id),
    )


def delete_scoped_asset_references(conn: ChatReadConnection) -> None:
    """Finalize files already deleted by removing their private retry records."""

    conn.execute(
        statement("""
        DELETE FROM {part0}
        WHERE message_id IN (
            SELECT item_id FROM {part1}
        )
        """, part0=CHAT_MESSAGE_ASSET_REFS_TABLE, part1=DELETION_MESSAGE_IDS_TABLE)
    )


def delete_scoped_code_delegation_references(
    conn: ChatReadConnection,
) -> None:
    """Remove message ownership only after private artifact cleanup succeeds."""

    conn.execute(
        statement("""
        DELETE FROM {part0}
        WHERE message_id IN (
            SELECT item_id FROM {part1}
        )
        """, part0=CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE, part1=DELETION_MESSAGE_IDS_TABLE)
    )


def delete_code_delegation_artifact_records(
    conn: ChatReadConnection,
    *,
    references: Iterable[CodeAgentDelegationReference],
) -> None:
    """Remove exact orphan-cleanup records after their paths are gone."""

    conn.executemany(
        statement("""
        DELETE FROM {part0}
        WHERE workspace_path = ?
          AND session_id = ? COLLATE NOCASE
          AND delegation_id = ?
        """, mysql="""
        DELETE FROM {part0}
        WHERE workspace_path = ?
          AND {fold1} = {fold2}
          AND delegation_id = ?
        """, part0=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE, fold1=mysql_ascii_lower('session_id'), fold2=mysql_ascii_lower('?')),
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
    conn: ChatReadConnection,
    *,
    user_id: str,
    session_id: str,
) -> None:
    """Remove redacted message rows after external cleanup is complete."""

    conn.execute(
        statement("""
        DELETE FROM {part0}
        WHERE user_id = ?
          AND session_id = ?
          AND message_id IN (
              SELECT item_id FROM {part1}
          )
        """, part0=CHAT_MESSAGES_TABLE, part1=DELETION_MESSAGE_IDS_TABLE),
        (user_id, session_id),
    )


def delete_session_model_context(
    conn: ChatReadConnection,
    *,
    session_id: str,
) -> int:
    """Physically clear every model-visible context record for one session."""

    deleted = 0
    for table in (
        CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE,
        CHAT_MODEL_CONTEXT_EPOCHS_TABLE,
        CHAT_MODEL_CONTEXT_RUN_HEADS_TABLE,
        CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
        CHAT_MODEL_CONTEXT_REVISIONS_TABLE,
        CHAT_MODEL_CONTEXT_EVENTS_TABLE,
        CHAT_MODEL_CONTEXT_HEADS_TABLE,
    ):
        cursor = conn.execute(
            statement("""DELETE FROM {part0} WHERE session_id = ? COLLATE NOCASE""", mysql="""DELETE FROM {part0} WHERE {fold1} = {fold2}""", part0=table, fold1=mysql_ascii_lower('session_id'), fold2=mysql_ascii_lower('?')),
            (session_id,),
        )
        deleted += int(cursor.rowcount or 0)
    return deleted


def delete_all_model_context(conn: ChatReadConnection) -> int:
    """Physically clear every model-visible context record."""

    deleted = 0
    for table in (
        CHAT_MODEL_CONTEXT_BOUNDARIES_TABLE,
        CHAT_MODEL_CONTEXT_EPOCHS_TABLE,
        CHAT_MODEL_CONTEXT_RUN_HEADS_TABLE,
        CHAT_MODEL_CONTEXT_SURFACE_NODES_TABLE,
        CHAT_MODEL_CONTEXT_REVISIONS_TABLE,
        CHAT_MODEL_CONTEXT_EVENTS_TABLE,
        CHAT_MODEL_CONTEXT_HEADS_TABLE,
    ):
        cursor = conn.execute(statement("""DELETE FROM {part0}""", part0=table))
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
