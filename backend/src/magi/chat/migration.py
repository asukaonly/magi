"""Legacy-to-chat-store backfill helpers."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from .contracts import ChatMessageRecord, ChatSessionRecord, ChatTurnRecord
from .store import ChatStore

LEGACY_USER_EVENT_TYPES = ("UserMessage",)
LEGACY_ASSISTANT_EVENT_TYPES = ("AIResponse",)


async def backfill_chat_store_from_legacy(*, chat_store: ChatStore, legacy_l1_db_path: Path) -> None:
    """Backfill chat store rows from the legacy L1 transcript tables."""
    legacy_db_path = Path(legacy_l1_db_path).expanduser()
    if not legacy_db_path.exists():
        return

    await chat_store.initialize()
    async with aiosqlite.connect(str(legacy_db_path)) as db:
        db.row_factory = aiosqlite.Row
        table_names = await _list_table_names(db)
        if "chat_sessions" in table_names:
            cursor = await db.execute(
                """
                SELECT session_id, user_id, title, title_overridden, summary, created_at, updated_at,
                       last_message_at, last_user_message_at, last_message_preview,
                       last_user_message_preview, message_count, archived_at, deleted_at
                FROM chat_sessions
                WHERE deleted_at IS NULL
                """
            )
            for row in await cursor.fetchall():
                await chat_store.upsert_session(
                    ChatSessionRecord(
                        session_id=str(row["session_id"]),
                        user_id=str(row["user_id"]),
                        title=str(row["title"] or "New Chat"),
                        title_overridden=bool(int(row["title_overridden"] or 0)),
                        summary=str(row["summary"] or ""),
                        created_at_ms=_to_ms(row["created_at"]),
                        updated_at_ms=_to_ms(row["updated_at"]),
                        last_message_at_ms=_to_optional_ms(row["last_message_at"]),
                        last_user_message_at_ms=_to_optional_ms(row["last_user_message_at"]),
                        last_message_preview=str(row["last_message_preview"] or ""),
                        last_user_message_preview=str(row["last_user_message_preview"] or ""),
                        message_count=int(row["message_count"] or 0),
                        archived_at_ms=_to_optional_ms(row["archived_at"]),
                        deleted_at_ms=_to_optional_ms(row["deleted_at"]),
                    )
                )

        if "fact_events" not in table_names:
            return

        cursor = await db.execute(
            """
            SELECT event_id, event_type, session_id, turn_id, user_id, content, timestamp
            FROM fact_events
            WHERE deleted_at IS NULL
              AND event_type IN ('UserMessage', 'AIResponse')
              AND session_id IS NOT NULL
              AND user_id IS NOT NULL
            ORDER BY timestamp ASC, event_id ASC
            """
        )
        rows = await cursor.fetchall()

    turns: dict[str, dict[str, object]] = {}
    sequence_by_session: dict[str, int] = {}
    for row in rows:
        session_id = str(row["session_id"] or "").strip()
        turn_id = str(row["turn_id"] or "").strip()
        user_id = str(row["user_id"] or "").strip()
        if not session_id or not user_id:
            continue

        timestamp_ms = _to_ms(row["timestamp"])
        if turn_id:
            turn_state = turns.setdefault(
                turn_id,
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "created_at_ms": timestamp_ms,
                    "updated_at_ms": timestamp_ms,
                    "has_final": False,
                },
            )
            turn_state["updated_at_ms"] = max(int(turn_state["updated_at_ms"]), timestamp_ms)
            if str(row["event_type"]) in LEGACY_ASSISTANT_EVENT_TYPES:
                turn_state["has_final"] = True

        next_sequence = sequence_by_session.get(session_id, 0) + 1
        sequence_by_session[session_id] = next_sequence
        event_type = str(row["event_type"])
        message_kind = "user_text" if event_type in LEGACY_USER_EVENT_TYPES else "assistant_final"
        role = "user" if event_type in LEGACY_USER_EVENT_TYPES else "assistant"
        await chat_store.append_message(
            ChatMessageRecord(
                message_id=str(row["event_id"]),
                session_id=session_id,
                turn_id=turn_id or None,
                user_id=user_id,
                role=role,
                message_kind=message_kind,
                content_text=str(row["content"] or ""),
                payload_json="{}",
                is_final=message_kind != "assistant_interim",
                is_visible=True,
                created_at_ms=timestamp_ms,
                sequence_no=next_sequence,
                replaces_message_id=None,
                replaced_by_message_id=None,
            )
        )

    for turn_id, state in turns.items():
        await chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=turn_id,
                session_id=str(state["session_id"]),
                user_id=str(state["user_id"]),
                trace_id=None,
                orchestration_id=None,
                status="completed" if bool(state["has_final"]) else "queued",
                response_mode="final_only",
                execution_mode=None,
                ux_plan_json="{}",
                created_at_ms=int(state["created_at_ms"]),
                updated_at_ms=int(state["updated_at_ms"]),
                completed_at_ms=int(state["updated_at_ms"]) if bool(state["has_final"]) else None,
                error_text=None,
            )
        )


async def _list_table_names(db: aiosqlite.Connection) -> set[str]:
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    rows = await cursor.fetchall()
    return {str(row[0]) for row in rows}


def _to_ms(raw_value: object) -> int:
    return int(float(raw_value or 0) * 1000)


def _to_optional_ms(raw_value: object) -> int | None:
    if raw_value is None:
        return None
    return _to_ms(raw_value)
