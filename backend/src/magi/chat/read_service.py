"""Read-side service for chat sessions and conversation history."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..agent.orchestration import get_orchestration_store
from ..config import get_config
from ..core.logger import get_logger
from ..core.code_agent_artifacts import (
    CodeAgentArtifactGC,
    CodeAgentDelegationReference,
)
from ..core.sqlite import connect_sqlite
from ..utils.runtime import RuntimePaths, get_runtime_paths
from .asset_gc import ChatAssetGC
from magi.core.chat_assets.mutations import run_chat_asset_mutation
from .message_frontier import (
    MESSAGE_FRONTIER_SELECT_SQL,
    MESSAGE_ORDER_SQL,
    build_inclusive_frontier_filter,
)
from .read.models import (
    ChatDisplayMessage,
    ChatMessageSourceIdentity,
    ChatSessionRenameResult,
    ChatSessionSummary,
    SessionWorkspaceUpdateResult,
)
from .read.delivery_operations import ChatDeliveryOperationsMixin
from .read.history_operations import ChatHistoryOperationsMixin
from .read.session_operations import ChatSessionOperationsMixin
from .read.schema import (
    CHAT_MESSAGES_TABLE,
    CHAT_TURNS_TABLE,
)
from .read.serialization import (
    apply_turn_ux_preferences,
    build_reply_preview,
    normalize_workspace_path,
    parse_label_payload,
    parse_message_payload_json,
    parse_turn_ux_preferences,
    row_to_display_message,
    row_to_session_summary,
)

if TYPE_CHECKING:
    from .contracts import (
        ChatContextUsageSnapshot,
        ChatMessageLabel,
        ChatUserTurnDeliveryRecord,
    )

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"


class ChatReadService(
    ChatDeliveryOperationsMixin,
    ChatSessionOperationsMixin,
    ChatHistoryOperationsMixin,
):
    """Query chat session and history from persistent storage."""

    def __init__(self, *, runtime_paths: RuntimePaths | None = None) -> None:
        runtime_paths = runtime_paths or get_runtime_paths()
        self._runtime_paths = runtime_paths
        self._chat_db_path: Path = runtime_paths.chat_db_path
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path
        self._asset_gc = ChatAssetGC(runtime_paths=runtime_paths)
        self._code_agent_artifact_gc = CodeAgentArtifactGC()
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Return a reusable SQLite connection, creating one lazily."""
        if self._conn is None:
            self._chat_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect_sqlite(self._chat_db_path, profile="mixed")
        return self._conn

    def close(self) -> None:
        """Close the cached SQLite connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def acreate_new_session(
        self,
        user_id: str,
        workspace_path: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Create a session without blocking the event loop."""
        return await self._run_threaded(
            "create_new_session",
            user_id,
            workspace_path,
            idempotency_key,
        )

    async def aget_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        """Load a worker result without blocking the event loop."""
        return await self._run_threaded("get_worker_result", worker_id)

    async def aget_session_summary(
        self,
        user_id: str,
        session_id: str,
    ) -> ChatSessionSummary | None:
        """Load one session summary without blocking the event loop."""
        return await self._run_threaded("get_session_summary", user_id, session_id)

    async def aget_session_summaries_batch(
        self,
        user_id: str,
        session_ids: list[str],
    ) -> dict[str, "ChatSessionSummary"]:
        """Fetch multiple session summaries in one query without blocking."""
        return await self._run_threaded("get_session_summaries_batch", user_id, session_ids)

    async def alist_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List sessions without blocking the event loop."""
        return await self._run_threaded("list_sessions", user_id, limit)

    async def alist_workspace_paths(self, user_id: str) -> list[str]:
        """List all non-deleted session workspaces without loading sessions."""
        return await self._run_threaded("list_workspace_paths", user_id)

    async def arename_session(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRenameResult:
        """Rename a session without blocking the event loop."""
        return await self._run_threaded("rename_session", user_id, session_id, title)

    async def aupdate_session_workspace(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str | None,
    ) -> SessionWorkspaceUpdateResult:
        """Update a session workspace path without blocking the event loop."""
        return await self._run_threaded(
            "update_session_workspace", user_id, session_id, workspace_path
        )

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        """Delete a session without blocking the event loop."""
        await run_chat_asset_mutation(
            self._run_isolated,
            "delete_session",
            user_id,
            session_id,
        )

    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        """Load all source turn identities before deleting a session."""
        return await self._run_threaded("list_session_turn_ids", user_id, session_id)

    async def abackfill_cleared_chat_scopes(
        self,
        session_ids: list[str],
        message_scopes: list[tuple[str, str]],
    ) -> dict[str, int]:
        """Restore durable chat barriers without blocking the event loop."""

        return await self._run_threaded(
            "backfill_cleared_chat_scopes",
            session_ids,
            message_scopes,
        )

    async def aget_message_source_identity(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatMessageSourceIdentity | None:
        """Resolve one persisted message to its exact memory source identity."""
        return await self._run_threaded(
            "get_message_source_identity",
            user_id,
            session_id,
            message_id,
        )

    async def alist_message_replacement_source_identities(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> list[ChatMessageSourceIdentity]:
        """Snapshot every persisted revision of one logical message."""

        return await self._run_threaded(
            "list_message_replacement_source_identities",
            user_id,
            session_id,
            message_id,
        )

    async def alist_session_message_source_identities(
        self,
        user_id: str,
        session_id: str,
    ) -> list[ChatMessageSourceIdentity]:
        """Snapshot message sources before clearing a transcript."""
        return await self._run_threaded(
            "list_session_message_source_identities",
            user_id,
            session_id,
        )

    async def aget_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = 200,
    ) -> list[ChatDisplayMessage]:
        """Load conversation history without blocking the event loop."""
        return await self._run_threaded("get_conversation_history", user_id, session_id, limit)

    async def aget_latest_context_usage(
        self,
        user_id: str,
        session_id: str,
    ) -> "ChatContextUsageSnapshot | None":
        """Load the latest durable visible-answer usage without blocking."""

        return await self._run_threaded(
            "get_latest_context_usage",
            user_id,
            session_id,
        )

    async def aget_session_attachment_references(
        self,
        user_id: str,
        session_id: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Load recent session attachment references without blocking the event loop."""
        return await self._run_threaded(
            "get_session_attachment_references",
            user_id,
            session_id,
            limit,
        )

    async def aget_display_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 200,
    ) -> list[ChatDisplayMessage]:
        """Load display history without blocking the event loop."""
        return await self._run_threaded("get_display_history", user_id, session_id, limit)

    async def aget_display_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatDisplayMessage | None:
        """Load one visible display message without blocking the event loop."""
        return await self._run_threaded("get_display_message", user_id, session_id, message_id)

    async def aget_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Load one persisted attachment payload without blocking the event loop."""
        return await self._run_threaded(
            "get_attachment_payload", user_id, session_id, attachment_id
        )

    async def aforget_message_artifacts(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        """Remove every chat-owned copy of one governed message."""
        return await run_chat_asset_mutation(
            self._run_isolated,
            "forget_message_artifacts",
            user_id,
            session_id,
            message_id,
        )

    async def aclear_conversation_history_snapshot(
        self,
        user_id: str,
        session_id: str,
        message_ids: list[str],
        turn_ids: list[str],
    ) -> None:
        """Physically remove one governed transcript snapshot."""
        await run_chat_asset_mutation(
            self._run_isolated,
            "clear_conversation_history_snapshot",
            user_id,
            session_id,
            message_ids,
            turn_ids,
        )

    async def aclear_conversation_history(self, user_id: str, session_id: str) -> None:
        """Clear a session history without blocking the event loop."""
        await run_chat_asset_mutation(
            self._run_isolated,
            "clear_conversation_history",
            user_id,
            session_id,
        )

    async def aclear_all_sessions(self) -> int:
        """Clear all sessions without blocking the event loop."""
        return await run_chat_asset_mutation(
            self._run_isolated,
            "clear_all_sessions",
        )

    async def arecover_interrupted_global_clear(self) -> bool:
        """Finish an interrupted global chat clear before runtime work starts."""

        return await run_chat_asset_mutation(
            self._run_isolated,
            "recover_interrupted_global_clear",
        )

    async def acomplete_global_clear(self) -> bool:
        """Release the global barrier after external conversation cleanup."""

        return await self._run_threaded("complete_global_clear")

    async def aget_interrupted_global_clear_count(self) -> int | None:
        """Read the count committed by an interrupted global clear."""

        return await self._run_threaded("get_interrupted_global_clear_count")

    async def areset_user_turn_delivery_after_failed_clear(self) -> int:
        """Make surviving turns replayable after a failed destructive clear."""
        return await self._run_threaded("reset_user_turn_delivery_after_failed_clear")

    async def alist_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: "ChatUserTurnDeliveryRecord | None" = None,
    ) -> list["ChatUserTurnDeliveryRecord"]:
        """Load non-terminal runtime envelopes without blocking the event loop."""
        return await self._run_threaded(
            "list_recoverable_user_turn_deliveries",
            user_id,
            session_id,
            limit,
            after,
        )

    async def abump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list["ChatUserTurnDeliveryRecord"]:
        """Invalidate session-local survivor attempts without blocking."""
        return await self._run_threaded(
            "bump_nonterminal_user_turn_delivery_attempts",
            user_id,
            session_id,
            excluded_turn_ids,
            updated_at_ms,
            bump_survivors,
        )

    def get_worker_result(self, worker_id: str) -> Optional[dict[str, Any]]:
        if not worker_id.strip():
            return None
        store = get_orchestration_store()
        return store.get_worker_result_sync(worker_id)

    def _query_fact_rows(
        self,
        *,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str | None,
        limit: int | None,
        ascending: bool,
    ) -> list[tuple[str, str, float, str | None, str | None]]:
        return self._query_rows(
            table=FACT_EVENTS_TABLE,
            event_types=event_types,
            user_id=user_id,
            session_id=session_id,
            limit=limit,
            ascending=ascending,
        )

    def _query_rows(
        self,
        *,
        table: str,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str | None,
        limit: int | None,
        ascending: bool,
    ) -> list[tuple[str, str, float, str | None, str | None]]:
        if not event_types:
            return []
        order_direction = "ASC" if ascending else "DESC"
        query = f"""
            SELECT event_type, content, timestamp, session_id, turn_id
            FROM {table}
            WHERE deleted_at IS NULL
              AND event_type IN ({", ".join("?" for _ in event_types)})
              AND user_id = ?
        """
        params: list[Any] = [*event_types, user_id]
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += f" ORDER BY timestamp {order_direction}"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))

        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        return rows

    def _delete_runtime_trace_rows(self, *, user_id: str, session_id: str) -> None:
        if not self._runtime_trace_db_path.exists():
            return
        conn = connect_sqlite(self._runtime_trace_db_path, profile="hot_write")
        try:
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "trace_turns" in existing_tables:
                for table in (
                    "trace_intent_resolutions",
                    "trace_llm_calls",
                    "trace_tools",
                    "trace_spans",
                ):
                    if table in existing_tables:
                        conn.execute(
                            f"""
                            DELETE FROM {table}
                            WHERE turn_id IN (
                                SELECT turn_id FROM trace_turns
                                WHERE user_id = ? AND session_id = ?
                            )
                            """,
                            (user_id, session_id),
                        )
                conn.execute(
                    "DELETE FROM trace_turns WHERE user_id = ? AND session_id = ?",
                    (user_id, session_id),
                )
            if "runtime_notifications" in existing_tables:
                conn.execute(
                    """
                    DELETE FROM runtime_notifications
                    WHERE user_id = ? AND session_id = ?
                    """,
                    (user_id, session_id),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            logger.exception("Failed to delete runtime trace rows")
            raise
        finally:
            conn.close()

    def _delete_runtime_trace_turn_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> None:
        """Strictly delete every runtime-trace copy owned by one chat turn."""
        if not self._runtime_trace_db_path.exists():
            return
        conn = connect_sqlite(self._runtime_trace_db_path, profile="hot_write")
        try:
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            owns_turn = False
            if "trace_turns" in existing_tables:
                owns_turn = (
                    conn.execute(
                        """
                        SELECT 1 FROM trace_turns
                        WHERE user_id = ? AND session_id = ? AND turn_id = ?
                        LIMIT 1
                        """,
                        (user_id, session_id, turn_id),
                    ).fetchone()
                    is not None
                )
            if owns_turn:
                for table in (
                    "trace_intent_resolutions",
                    "trace_llm_calls",
                    "trace_tools",
                    "trace_spans",
                ):
                    if table in existing_tables:
                        conn.execute(f"DELETE FROM {table} WHERE turn_id = ?", (turn_id,))
                conn.execute(
                    """
                    DELETE FROM trace_turns
                    WHERE user_id = ? AND session_id = ? AND turn_id = ?
                    """,
                    (user_id, session_id, turn_id),
                )
            if "runtime_notifications" in existing_tables:
                conn.execute(
                    """
                    DELETE FROM runtime_notifications
                    WHERE user_id = ? AND session_id = ? AND turn_id = ?
                    """,
                    (user_id, session_id, turn_id),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            logger.exception("Failed to delete runtime trace turn rows")
            raise
        finally:
            conn.close()

    def _clear_all_runtime_trace_rows(self) -> None:
        """Delete execution traces and every persisted user-facing notification."""
        if not self._runtime_trace_db_path.exists():
            return
        conn = connect_sqlite(self._runtime_trace_db_path, profile="hot_write")
        try:
            existing_tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in (
                "trace_intent_resolutions",
                "trace_llm_calls",
                "trace_tools",
                "trace_spans",
                "trace_turns",
            ):
                if table in existing_tables:
                    conn.execute(f"DELETE FROM {table}")
            if "runtime_notifications" in existing_tables:
                conn.execute("DELETE FROM runtime_notifications")
            if "user_notifications" in existing_tables:
                conn.execute("DELETE FROM user_notifications")
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to clear runtime trace rows")
            raise
        finally:
            conn.close()

    def _delete_chat_message_assets(
        self,
        *,
        asset_references: list[tuple[str, str]],
    ) -> None:
        self._asset_gc.delete_message_assets(asset_references)

    def _delete_code_delegation_artifacts(
        self,
        *,
        references: list[CodeAgentDelegationReference],
    ) -> None:
        gc = getattr(self, "_code_agent_artifact_gc", None)
        if gc is None:
            gc = CodeAgentArtifactGC()
            self._code_agent_artifact_gc = gc
        gc.delete_references(references)

    def _list_chat_snapshot_asset_references(
        self,
        *,
        session_id: str,
        turn_ids: list[str],
        delete_entire_session: bool,
    ) -> list[tuple[str, str]]:
        return self._asset_gc.list_snapshot_asset_references(
            session_id=session_id,
            turn_ids=turn_ids,
            delete_entire_session=delete_entire_session,
        )

    def _clear_all_chat_assets(self) -> None:
        if not get_config().lifecycle.chat_assets.delete_on_clear_memory:
            return
        self._asset_gc.clear_all_assets()

    def _query_chat_message_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        message_kinds: tuple[str, ...] | None,
        visible_only: bool,
        exclude_replaced: bool,
        start_message_id: str | None = None,
    ) -> list[sqlite3.Row]:
        query = f"""
            SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                   content_text, payload_json, is_final, is_visible, created_at_ms,
                     sequence_no, replaces_message_id, replaced_by_message_id, persona_id,
                     reply_to_message_id, label_json
            FROM {CHAT_MESSAGES_TABLE}
            WHERE user_id = ?
              AND session_id = ?
        """
        params: list[Any] = [user_id, session_id]
        if message_kinds:
            query += f" AND message_kind IN ({', '.join('?' for _ in message_kinds)})"
            params.extend(message_kinds)
        if visible_only:
            query += " AND is_visible = 1"
        if exclude_replaced:
            query += " AND replaced_by_message_id IS NULL"
        conn = self._get_conn()
        normalized_start = str(start_message_id or "").strip()
        if normalized_start:
            boundary = conn.execute(
                MESSAGE_FRONTIER_SELECT_SQL,
                (session_id, normalized_start),
            ).fetchone()
            if boundary is not None:
                frontier_sql, frontier_params = build_inclusive_frontier_filter(
                    boundary,
                    message_id=normalized_start,
                )
                query += frontier_sql
                params.extend(frontier_params)
        query += f" ORDER BY {MESSAGE_ORDER_SQL}"
        return conn.execute(query, params).fetchall()

    def _query_turn_rows(self, *, user_id: str, session_id: str) -> list[sqlite3.Row]:
        conn = self._get_conn()
        return conn.execute(
            f"""
            SELECT turn_id, session_id, user_id, status, response_mode, execution_mode,
                     ux_plan_json, created_at_ms, updated_at_ms, completed_at_ms,
                     error_text, run_id, run_revision, run_disposition
            FROM {CHAT_TURNS_TABLE}
            WHERE user_id = ?
              AND session_id = ?
            ORDER BY created_at_ms ASC, updated_at_ms ASC
            """,
            (user_id, session_id),
        ).fetchall()

    @staticmethod
    def _parse_turn_ux_preferences(raw_ux_plan_json: str | None) -> dict[str, Any]:
        return parse_turn_ux_preferences(raw_ux_plan_json)

    @staticmethod
    def _apply_turn_ux_preferences(
        message: ChatDisplayMessage,
        preferences: dict[str, Any] | None,
    ) -> None:
        apply_turn_ux_preferences(message, preferences)

    @staticmethod
    def _row_to_display_message(row: sqlite3.Row) -> ChatDisplayMessage | None:
        return row_to_display_message(row)

    @staticmethod
    def _build_reply_preview(target_row: sqlite3.Row | None) -> dict[str, Any] | None:
        return build_reply_preview(target_row)

    def _attach_reply_previews(
        self,
        *,
        rows: list[sqlite3.Row],
        messages: list[ChatDisplayMessage],
    ) -> None:
        rows_by_message_id = {
            str(row["message_id"]): row for row in rows if row["message_id"] is not None
        }
        for row, message in zip(rows, messages):
            reply_to_message_id = str(row["reply_to_message_id"] or "").strip()
            if not reply_to_message_id:
                message.reply_to = None
                continue
            target_row = rows_by_message_id.get(reply_to_message_id)
            if target_row is None:
                target_user_id = str(row["user_id"] or "").strip()
                target_session_id = str(row["session_id"] or "").strip()
                target_row = (
                    self._get_conn()
                    .execute(
                        f"""
                    SELECT message_id, role, message_kind, content_text
                    FROM {CHAT_MESSAGES_TABLE}
                    WHERE message_id = ?
                      AND user_id = ?
                      AND session_id = ?
                      AND is_visible = 1
                    """,
                        (reply_to_message_id, target_user_id, target_session_id),
                    )
                    .fetchone()
                )
            message.reply_to = self._build_reply_preview(target_row)

    @staticmethod
    def _row_to_session_summary(row: sqlite3.Row) -> ChatSessionSummary:
        return row_to_session_summary(row)

    @staticmethod
    def _parse_message_payload_json(raw_payload_json: str | None) -> dict[str, Any]:
        return parse_message_payload_json(raw_payload_json)

    @staticmethod
    def _parse_label_payload(raw_label_json: str | None) -> ChatMessageLabel | None:
        return parse_label_payload(raw_label_json)

    @staticmethod
    def _normalize_workspace_path(workspace_path: str | None) -> str | None:
        return normalize_workspace_path(workspace_path)

    async def _run_threaded(self, method_name: str, *args: Any) -> Any:
        return await asyncio.to_thread(self._run_isolated, method_name, *args)

    def _run_isolated(self, method_name: str, *args: Any) -> Any:
        service = object.__new__(ChatReadService)
        service._runtime_paths = self._runtime_paths
        service._chat_db_path = self._chat_db_path
        service._l1_db_path = self._l1_db_path
        service._runtime_trace_db_path = self._runtime_trace_db_path
        service._asset_gc = ChatAssetGC(runtime_paths=self._runtime_paths)
        service._conn = None
        try:
            method = getattr(service, method_name)
            return method(*args)
        finally:
            service.close()


def get_chat_read_service() -> ChatReadService:
    """Get the shared ChatReadService instance."""
    from .read.provider import (
        get_chat_read_service as _get_chat_read_service,
    )

    return _get_chat_read_service()


def get_chat_trace_read_service() -> Any:
    """Get the shared ChatTraceReadService instance."""
    from ..runtime_trace.chat_trace.read_service import (
        get_chat_trace_read_service as _get_chat_trace_read_service,
    )

    return _get_chat_trace_read_service()
