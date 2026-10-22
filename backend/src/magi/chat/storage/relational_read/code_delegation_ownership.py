"""Indexed ownership queries for private code-delegation artifacts."""

from __future__ import annotations

from ..statements import statement, mysql_ascii_lower

from ..relational import ChatReadConnection

from collections.abc import Iterable

from ....core.code_agent_artifacts import CodeAgentDelegationReference
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
    conn: ChatReadConnection,
    *,
    table: str,
    values: Iterable[str],
) -> None:
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
        """, part0=table)
    )
    conn.execute(statement("""DELETE FROM {part0}""", part0=table))
    normalized = sorted(
        {
            value
            for raw_value in values
            if (value := str(raw_value or "").strip())
        }
    )
    conn.executemany(
        statement("""INSERT INTO {part0}(item_id) VALUES (?)""", part0=table),
        [(value,) for value in normalized],
    )


def unshared_code_delegation_references(
    conn: ChatReadConnection,
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
            statement("""
            INSERT OR IGNORE INTO {part0}(item_id)
            SELECT message_id
            FROM {part1}
            """, mysql="""
            INSERT IGNORE INTO {part0}(item_id)
            SELECT message_id
            FROM {part1}
            """, part0=TARGET_MESSAGE_IDS_TABLE, part1=CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE)
        )
    conn.execute(
        statement("""
        CREATE TEMP TABLE IF NOT EXISTS {part0} (
            workspace_path TEXT NOT NULL,
            session_id TEXT COLLATE NOCASE NOT NULL,
            delegation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            PRIMARY KEY (workspace_path, session_id, delegation_id)
        ) WITHOUT ROWID
        """, mysql="""
        CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
            workspace_path LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            session_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            delegation_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            turn_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(CONCAT(HEX(workspace_path),':',HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')),':',HEX(delegation_id)),256)) STORED,
            UNIQUE KEY(__key)
        )
        """, part0=CANDIDATE_ARTIFACTS_TABLE)
    )
    conn.execute(statement("""DELETE FROM {part0}""", part0=CANDIDATE_ARTIFACTS_TABLE))
    conn.execute(
        statement("""
        INSERT OR IGNORE INTO {part0}(
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
        FROM {part1} AS refs
        JOIN {part2} AS target
          ON target.item_id = refs.message_id
        """, mysql="""
        INSERT IGNORE INTO {part0}(
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
        FROM {part1} AS refs
        JOIN {part2} AS target
          ON target.item_id = refs.message_id
        """, part0=CANDIDATE_ARTIFACTS_TABLE, part1=CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE, part2=TARGET_MESSAGE_IDS_TABLE)
    )
    if all_artifacts:
        conn.execute(
            statement("""
            INSERT OR IGNORE INTO {part0}(
                workspace_path,
                session_id,
                delegation_id,
                turn_id
            )
            SELECT workspace_path, session_id, delegation_id, turn_id
            FROM {part1}
            """, mysql="""
            INSERT IGNORE INTO {part0}(
                workspace_path,
                session_id,
                delegation_id,
                turn_id
            )
            SELECT workspace_path, session_id, delegation_id, turn_id
            FROM {part1}
            """, part0=CANDIDATE_ARTIFACTS_TABLE, part1=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE)
        )
    else:
        normalized_session_id = str(session_id or "").strip()
        if normalized_session_id:
            conn.execute(
                statement("""
                INSERT OR IGNORE INTO {part0}(
                    workspace_path,
                    session_id,
                    delegation_id,
                    turn_id
                )
                SELECT workspace_path, session_id, delegation_id, turn_id
                FROM {part1}
                WHERE session_id = ? COLLATE NOCASE
                """, mysql="""
                INSERT IGNORE INTO {part0}(
                    workspace_path,
                    session_id,
                    delegation_id,
                    turn_id
                )
                SELECT workspace_path, session_id, delegation_id, turn_id
                FROM {part1}
                WHERE {fold2} = {fold3}
                """, part0=CANDIDATE_ARTIFACTS_TABLE, part1=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE, fold2=mysql_ascii_lower('session_id'), fold3=mysql_ascii_lower('?')),
                (normalized_session_id,),
            )
        conn.execute(
            statement("""
            INSERT OR IGNORE INTO {part0}(
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
            FROM {part1} AS artifact
            JOIN {part2} AS target
              ON target.item_id = artifact.turn_id
            """, mysql="""
            INSERT IGNORE INTO {part0}(
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
            FROM {part1} AS artifact
            JOIN {part2} AS target
              ON target.item_id = artifact.turn_id
            """, part0=CANDIDATE_ARTIFACTS_TABLE, part1=CHAT_CODE_DELEGATION_ARTIFACTS_TABLE, part2=TARGET_TURN_IDS_TABLE)
        )

    rows = conn.execute(
        statement("""
        SELECT
            candidate.workspace_path,
            candidate.session_id,
            candidate.delegation_id,
            candidate.turn_id
        FROM {part0} AS candidate
        WHERE NOT EXISTS (
            SELECT 1
            FROM {part1} AS owner
                 INDEXED BY idx_chat_message_code_delegation_scope
            JOIN {part2} AS owner_message
              ON owner_message.message_id = owner.message_id
            JOIN {part3} AS owner_session
              ON owner_session.session_id = owner_message.session_id
            LEFT JOIN {part4} AS target_owner
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
        """, mysql="""
        SELECT
            candidate.workspace_path,
            candidate.session_id,
            candidate.delegation_id,
            candidate.turn_id
        FROM {part0} AS candidate
        WHERE NOT EXISTS (
            SELECT 1
            FROM {part1} AS owner
                 FORCE INDEX (idx_chat_message_code_delegation_scope)
            JOIN {part2} AS owner_message
              ON owner_message.message_id = owner.message_id
            JOIN {part3} AS owner_session
              ON owner_session.session_id = owner_message.session_id
            LEFT JOIN {part4} AS target_owner
              ON target_owner.item_id = owner.message_id
            WHERE owner.workspace_path = candidate.workspace_path
              AND {fold5} = {fold6}
              AND owner.delegation_id = candidate.delegation_id
              AND target_owner.item_id IS NULL
              AND owner_message.is_visible = 1
              AND owner_session.deleted_at_ms IS NULL
        )
        ORDER BY
            candidate.workspace_path,
            candidate.session_id,
            candidate.delegation_id
        """, part0=CANDIDATE_ARTIFACTS_TABLE, part1=CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE, part2=CHAT_MESSAGES_TABLE, part3=CHAT_SESSIONS_TABLE, part4=TARGET_MESSAGE_IDS_TABLE, fold5=mysql_ascii_lower('owner.session_id'), fold6=mysql_ascii_lower('candidate.session_id'))
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
