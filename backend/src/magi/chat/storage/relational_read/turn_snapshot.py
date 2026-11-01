"""Read exact turn acceptance and completion from one chat storage snapshot."""

from typing import Any

from ....core.client_models import TurnSnapshot
from ....db.identities import identity_key
from ...rhythm_completion import MAX_RHYTHM_SEGMENT_COUNT, complete_rhythm_payloads
from .pagination import read_revision

TERMINAL_STATES = frozenset({
    "completed", "failed", "cancelled", "blocked", "interrupted", "merged",
    "discarded", "superseded",
})


def turn_snapshot(host: Any, user_id: str, session_id: str, turn_id: str) -> TurnSnapshot:
    """Never infer absence from unavailable storage or a limited history page."""
    if not host.database.is_present():
        raise RuntimeError("Chat storage is unavailable")
    conn = host._get_conn()
    conn.begin_read()
    try:
        revision = read_revision(conn, user_id, session_id)
        session = conn.execute(
            "SELECT 1 FROM chat_sessions WHERE user_id=? AND session_id=? AND deleted_at_ms IS NULL AND archived_at_ms IS NULL",
            (user_id, session_id),
        ).fetchone()
        retired = conn.execute(
            "SELECT 1 FROM chat_retired_turns WHERE turn_key=?", (identity_key("chat-turn", turn_id),),
        ).fetchone()
        base = dict(session_id=session_id, turn_id=turn_id, revision=revision)
        if session is None or retired is not None:
            return TurnSnapshot(**base, acceptance="retired", state=None, terminal=False,
                                response_complete=False, presentation_ends_at_ms=None, can_resubmit=False)
        anchor = conn.execute(
            """SELECT 1 FROM chat_messages WHERE user_id=? AND session_id=? AND turn_id=?
               AND role='user' AND message_kind='user_text' AND is_visible=1 LIMIT 1""",
            (user_id, session_id, turn_id),
        ).fetchone()
        if anchor is None:
            return TurnSnapshot(**base, acceptance="absent", state=None, terminal=False,
                                response_complete=False, presentation_ends_at_ms=None, can_resubmit=True)
        turn = conn.execute(
            "SELECT status FROM chat_turns WHERE user_id=? AND session_id=? AND turn_id=?",
            (user_id, session_id, turn_id),
        ).fetchone()
        state = str(turn["status"]) if turn is not None else "queued"
        terminal = state in TERMINAL_STATES
        segments = conn.execute(
            """SELECT payload_json,created_at_ms FROM chat_messages
               WHERE user_id=? AND session_id=? AND turn_id=? AND role='assistant'
                 AND message_kind='assistant_rhythm_segment' AND is_visible=1 AND is_final=1
                 AND replaced_by_message_id IS NULL LIMIT ?""",
            (user_id, session_id, turn_id, MAX_RHYTHM_SEGMENT_COUNT + 1),
        ).fetchall()
        complete = terminal and (not segments or complete_rhythm_payloads(row["payload_json"] for row in segments))
        ends_at = max((int(row["created_at_ms"]) for row in segments), default=None)
        return TurnSnapshot(**base, acceptance="accepted", state=state, terminal=terminal,
                            response_complete=complete, presentation_ends_at_ms=ends_at, can_resubmit=False)
    finally:
        conn.rollback()
