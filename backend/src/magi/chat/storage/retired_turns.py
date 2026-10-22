"""Content-free identity receipts for irreversibly cleared chat turns."""

from collections.abc import Iterable
import time

from ...db.identities import identity_key
from ..errors import ChatTurnConflictError
from .relational import AsyncChatConnection, ChatReadConnection
from .statements import statement


def retire_turns(connection: ChatReadConnection, turn_ids: Iterable[str]) -> None:
    """Retire identities in the same write transaction that erases their content."""
    retired_at_ms = int(time.time() * 1000)
    connection.executemany(
        statement(
            "INSERT OR IGNORE INTO chat_retired_turns(turn_key, retired_at_ms) VALUES (?, ?)",
            mysql="INSERT IGNORE INTO chat_retired_turns(turn_key, retired_at_ms) VALUES (?, ?)",
        ),
        [(identity_key("chat-turn", turn_id), retired_at_ms) for turn_id in set(turn_ids) if turn_id],
    )


async def require_active_turn(connection: AsyncChatConnection, turn_id: str | None) -> None:
    """Reject delayed writes under a retired identity while holding the writer lock."""
    if not turn_id:
        return
    await connection.begin_write()
    cursor = await connection.execute(
        "SELECT 1 FROM chat_retired_turns WHERE turn_key = ?",
        (identity_key("chat-turn", turn_id),),
    )
    if await cursor.fetchone() is not None:
        raise ChatTurnConflictError("The requested turn has been permanently cleared")
