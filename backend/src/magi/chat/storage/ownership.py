"""Native persistence of run dependencies and private artifact identities."""

import time

from ...core.code_agent_artifacts import CodeAgentDelegationReference
from ..ownership_ports import ChatAssetOwnership
from ..errors import ChatTurnConflictError
from .relational import AsyncChatConnection, ChatDatabase, ChatReadDatabase
from .retired_turns import require_active_turn
from .statements import statement, mysql_ascii_lower


async def require_open_scope(db: AsyncChatConnection, session_id: str) -> None:
    await db.begin_write()
    cursor = await db.execute("SELECT 1 FROM chat_global_clear_intent WHERE intent_key='global'")
    if await cursor.fetchone() is not None:
        raise ChatTurnConflictError("Chat scope is being cleared")
    cursor = await db.execute(statement(
        "SELECT 1 FROM chat_cleared_session_scopes WHERE session_id=? COLLATE NOCASE",
        mysql="SELECT 1 FROM chat_cleared_session_scopes WHERE {left}={right}",
        left=mysql_ascii_lower("session_id"), right=mysql_ascii_lower("?"),
    ), (session_id,))
    if await cursor.fetchone() is not None:
        raise ChatTurnConflictError("Chat scope has been cleared")
    cursor = await db.execute(statement(
        "SELECT session_id,archived_at_ms,deleted_at_ms FROM chat_sessions WHERE session_id=? COLLATE NOCASE",
        mysql="SELECT session_id,archived_at_ms,deleted_at_ms FROM chat_sessions WHERE {left}={right}",
        left=mysql_ascii_lower("session_id"), right=mysql_ascii_lower("?"),
    ), (session_id,))
    row = await cursor.fetchone()
    if row is not None and (row[0] != session_id or row[1] is not None or row[2] is not None):
        raise ChatTurnConflictError("Chat scope is unavailable")


class ChatOwnershipPersistenceMixin:
    database: ChatDatabase

    async def record_consumed(self, *, session_id: str, run_id: str, revision: int, message_ids: list[str]) -> None:
        if not message_ids:
            return
        async with self.database.session() as db:
            await require_open_scope(db, session_id)
            await db.executemany(statement(
                "INSERT OR IGNORE INTO chat_run_consumed_events(session_id,run_id,revision,message_id,recorded_at_ms) VALUES (?,?,?,?,?)",
                mysql="INSERT IGNORE INTO chat_run_consumed_events(session_id,run_id,revision,message_id,recorded_at_ms) VALUES (?,?,?,?,?)",
            ), [(session_id, run_id, int(revision), message_id, int(time.time()*1000)) for message_id in message_ids])
            await db.commit()

    async def find_runs_that_consumed(self, *, session_id: str, message_id: str) -> list[tuple[str, int]]:
        async with self.database.session() as db:
            rows = await db.execute_fetchall(
                "SELECT DISTINCT run_id,revision FROM chat_run_consumed_events WHERE session_id=? AND message_id=? ORDER BY run_id,revision",
                (session_id, message_id),
            )
        return [(str(row[0]), int(row[1])) for row in rows]

    async def clear_for_run(self, *, session_id: str, run_id: str) -> None:
        async with self.database.session() as db:
            await db.execute("DELETE FROM chat_run_consumed_events WHERE session_id=? AND run_id=?", (session_id, run_id))
            await db.commit()

    async def register_code_artifact(self, reference: CodeAgentDelegationReference, *, created_at_ms: int) -> None:
        async with self.database.session() as db:
            await require_active_turn(db, reference.turn_id)
            await require_open_scope(db, reference.session_id)
            await db.execute(statement("""
                INSERT INTO chat_code_delegation_artifacts(workspace_path,session_id,delegation_id,turn_id,created_at_ms)
                VALUES (?,?,?,?,?) ON CONFLICT(workspace_path,session_id,delegation_id) DO UPDATE SET turn_id=excluded.turn_id
            """, mysql="""
                INSERT INTO chat_code_delegation_artifacts(workspace_path,session_id,delegation_id,turn_id,created_at_ms)
                VALUES (?,?,?,?,?) AS incoming ON DUPLICATE KEY UPDATE turn_id=incoming.turn_id
            """), (reference.workspace_path, reference.session_id, reference.delegation_id, reference.turn_id, created_at_ms))
            await db.commit()


def read_asset_ownership(database: ChatReadDatabase) -> ChatAssetOwnership | None:
    """Hold one snapshot while resolving sessions and persisted private owners."""
    if not database.is_present():
        return None
    connection = database.open()
    try:
        connection.begin_read()
        sessions = connection.execute("SELECT session_id FROM chat_sessions WHERE deleted_at_ms IS NULL").fetchall()
        assets = connection.execute("""
            SELECT DISTINCT refs.asset_key FROM chat_message_asset_refs AS refs
            JOIN chat_messages AS message ON message.message_id=refs.message_id
            JOIN chat_sessions AS session ON session.session_id=message.session_id
            WHERE session.deleted_at_ms IS NULL
        """).fetchall()
        return ChatAssetOwnership(tuple(str(row[0]) for row in sessions), tuple(str(row[0]) for row in assets))
    finally:
        connection.close()
