"""Indexed ownership queries for managed chat assets."""

from __future__ import annotations

from ..statements import statement

from ..relational import ChatReadConnection

from collections.abc import Iterable

from ...asset_gc import ChatAssetDeletionError
from magi.core.chat_assets.paths import asset_scope_identity_key
from .schema import (
    CHAT_MESSAGE_ASSET_REFS_TABLE,
    CHAT_MESSAGES_TABLE,
    CHAT_SESSIONS_TABLE,
)

TARGET_MESSAGE_IDS_TABLE = "chat_asset_target_message_ids"
TARGET_ASSET_KEYS_TABLE = "chat_asset_target_keys"

TARGET_ASSET_ROWS_SQL = statement("""
    SELECT refs.asset_key, refs.storage_rel_path
    FROM {part0} AS target_ids
    CROSS JOIN {part1} AS refs
    WHERE refs.message_id = target_ids.item_id
    ORDER BY refs.asset_key, refs.message_id
""", part0=TARGET_MESSAGE_IDS_TABLE, part1=CHAT_MESSAGE_ASSET_REFS_TABLE)

SHARED_TARGET_ASSET_KEYS_SQL = statement("""
    SELECT DISTINCT owner.asset_key
    FROM {part0} AS target_key
    CROSS JOIN {part1} AS owner
         INDEXED BY idx_chat_message_asset_refs_asset_key
    JOIN {part2} AS owner_message
      ON owner_message.message_id = owner.message_id
    JOIN {part3} AS owner_session
      ON owner_session.session_id = owner_message.session_id
    LEFT JOIN {part4} AS excluded_owner
      ON excluded_owner.item_id = owner.message_id
    WHERE owner.asset_key = target_key.asset_key
      AND excluded_owner.item_id IS NULL
      AND owner_message.is_visible = 1
      AND owner_session.deleted_at_ms IS NULL
""", mysql="""
    SELECT DISTINCT owner.asset_key
    FROM {part0} AS target_key
    CROSS JOIN {part1} AS owner
         FORCE INDEX (idx_chat_message_asset_refs_asset_key)
    JOIN {part2} AS owner_message
      ON owner_message.message_id = owner.message_id
    JOIN {part3} AS owner_session
      ON owner_session.session_id = owner_message.session_id
    LEFT JOIN {part4} AS excluded_owner
      ON excluded_owner.item_id = owner.message_id
    WHERE owner.asset_key = target_key.asset_key
      AND excluded_owner.item_id IS NULL
      AND owner_message.is_visible = 1
      AND owner_session.deleted_at_ms IS NULL
""", part0=TARGET_ASSET_KEYS_TABLE, part1=CHAT_MESSAGE_ASSET_REFS_TABLE, part2=CHAT_MESSAGES_TABLE, part3=CHAT_SESSIONS_TABLE, part4=TARGET_MESSAGE_IDS_TABLE)


def assert_unambiguous_session_asset_scope(
    conn: ChatReadConnection,
    *,
    session_id: str,
) -> None:
    """Fail closed when active sessions can share one filesystem directory."""

    normalized_session_id = str(session_id or "").strip()
    target_identity_key = asset_scope_identity_key(normalized_session_id)
    rows = conn.execute(
        statement("""
        SELECT session_id
        FROM {part0}
        WHERE deleted_at_ms IS NULL
        """, part0=CHAT_SESSIONS_TABLE)
    ).fetchall()
    if any(
        str(row["session_id"]) != normalized_session_id
        and asset_scope_identity_key(row["session_id"]) == target_identity_key
        for row in rows
    ):
        raise ChatAssetDeletionError(
            "Managed chat session asset scope is ambiguous"
        )


def _replace_target_message_ids(
    conn: ChatReadConnection,
    message_ids: Iterable[str],
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
        """, part0=TARGET_MESSAGE_IDS_TABLE)
    )
    conn.execute(statement("""DELETE FROM {part0}""", part0=TARGET_MESSAGE_IDS_TABLE))
    normalized_ids = sorted(
        {
            str(message_id or "").strip()
            for message_id in message_ids
            if str(message_id or "").strip()
        }
    )
    conn.executemany(
        statement("""INSERT INTO {part0}(item_id) VALUES (?)""", part0=TARGET_MESSAGE_IDS_TABLE),
        [(message_id,) for message_id in normalized_ids],
    )


def unshared_asset_references(
    conn: ChatReadConnection,
    *,
    message_ids: Iterable[str],
    candidate_asset_references: Iterable[tuple[str, str]] = (),
) -> list[tuple[str, str]]:
    """Return target assets that have no other visible active message owner."""

    _replace_target_message_ids(conn, message_ids)
    target_rows = conn.execute(TARGET_ASSET_ROWS_SQL).fetchall()
    target_assets: dict[str, str] = {
        str(row["asset_key"]): str(row["storage_rel_path"])
        for row in target_rows
        if str(row["asset_key"] or "").strip()
        and str(row["storage_rel_path"] or "").strip()
    }
    for raw_asset_key, raw_storage_rel_path in candidate_asset_references:
        asset_key = str(raw_asset_key or "").strip()
        storage_rel_path = str(raw_storage_rel_path or "").strip()
        if asset_key and storage_rel_path:
            target_assets.setdefault(asset_key, storage_rel_path)
    if not target_assets:
        return []
    conn.execute(
        statement("""
        CREATE TEMP TABLE IF NOT EXISTS {part0} (
            asset_key TEXT PRIMARY KEY
        ) WITHOUT ROWID
        """, mysql="""
        CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
            asset_key LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(HEX(asset_key),256)) STORED,
            UNIQUE KEY(__key)
        )
        """, part0=TARGET_ASSET_KEYS_TABLE)
    )
    conn.execute(statement("""DELETE FROM {part0}""", part0=TARGET_ASSET_KEYS_TABLE))
    conn.executemany(
        statement("""INSERT INTO {part0}(asset_key) VALUES (?)""", part0=TARGET_ASSET_KEYS_TABLE),
        [(asset_key,) for asset_key in sorted(target_assets)],
    )
    shared_asset_keys = {
        str(row["asset_key"])
        for row in conn.execute(SHARED_TARGET_ASSET_KEYS_SQL).fetchall()
    }
    return [
        (asset_key, storage_rel_path)
        for asset_key, storage_rel_path in target_assets.items()
        if asset_key not in shared_asset_keys
    ]


__all__ = [
    "SHARED_TARGET_ASSET_KEYS_SQL",
    "TARGET_ASSET_KEYS_TABLE",
    "TARGET_ASSET_ROWS_SQL",
    "TARGET_MESSAGE_IDS_TABLE",
    "assert_unambiguous_session_asset_scope",
    "unshared_asset_references",
]
