"""Read-side service for chat sessions and conversation history."""

from __future__ import annotations

from magi.core.client_models import TurnSnapshot
from ..ownership_ports import ChatAssetOwnership
from .ownership import read_asset_ownership

from .statements import statement

from .relational import ChatRow, ChatReadConnection, ChatReadDatabase

import asyncio
from typing import TYPE_CHECKING, Any, Optional, Callable, TypeVar

from ...core.logger import get_logger


from ..cleanup_plan import ChatAssetInventory
from ..workspace_preferences import RecentWorkspaceRepository
from ..message_frontier import (
    MESSAGE_FRONTIER_SELECT_SQL,
    MESSAGE_ORDER_SQL,
    build_inclusive_frontier_filter,
)
from magi.core.chat_read_models import (
    ChatDisplayMessage,
    ChatAttachmentLocation,
    ChatMessageSourceIdentity,
    ChatSessionRenameResult,
    ChatSessionSummary,
    SessionWorkspaceUpdateResult,
)
from .relational_read.delivery_operations import ChatDeliveryOperationsMixin
from .relational_read.history_operations import ChatHistoryOperationsMixin
from .relational_read.session_operations import ChatSessionOperationsMixin
from .relational_read.schema import (
    CHAT_MESSAGES_TABLE,
    CHAT_TURNS_TABLE,
)
from .relational_read.serialization import (
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
    from ..contracts import (
        ChatContextUsageSnapshot,
        ChatMessageLabel,
        ChatUserTurnDeliveryRecord,
    )

logger = get_logger(__name__)

ReadResult = TypeVar("ReadResult")

class RelationalChatReadRepository(
    ChatDeliveryOperationsMixin,
    ChatSessionOperationsMixin,
    ChatHistoryOperationsMixin,
):
    """Query chat session and history from persistent storage."""

    def __init__(self, *, database: ChatReadDatabase, asset_inventory: ChatAssetInventory, workspace_preferences: RecentWorkspaceRepository) -> None:
        self.workspace_preferences = workspace_preferences
        self.database = database
        self._asset_inventory = asset_inventory
        self._conn: Optional[ChatReadConnection] = None

    def _get_conn(self) -> ChatReadConnection:
        """Return a connection owned by the selected read adapter."""
        if self._conn is None:
            self._conn = self.database.open()
        return self._conn

    def get_active_asset_ownership(self) -> ChatAssetOwnership | None:
        return read_asset_ownership(self.database)

    def close(self) -> None:
        """Close the cached storage connection."""
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
        return await self._run_threaded(lambda reader: reader.create_new_session(user_id, workspace_path, idempotency_key))

    async def aget_session_summary(
        self,
        user_id: str,
        session_id: str,
    ) -> ChatSessionSummary | None:
        """Load one session summary without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.get_session_summary(user_id, session_id))

    async def aget_session_summaries_batch(
        self,
        user_id: str,
        session_ids: list[str],
    ) -> dict[str, "ChatSessionSummary"]:
        """Fetch multiple session summaries in one query without blocking."""
        return await self._run_threaded(lambda reader: reader.get_session_summaries_batch(user_id, session_ids))

    async def alist_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        """List sessions without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.list_sessions(user_id, limit))

    async def alist_session_page(
        self, user_id: str, limit: int = 50, before: str | None = None,
        known_revision: str | None = None,
    ) -> dict[str, Any]:
        """Read one session page and its revision from the same database snapshot."""
        return await self._run_threaded(lambda reader: reader.list_session_page(user_id, limit, before, known_revision))

    def list_session_page(
        self, user_id: str, limit: int = 50, before: str | None = None,
        known_revision: str | None = None,
    ) -> dict[str, Any]:
        from .relational_read.pagination import session_page

        return session_page(self, user_id, max(1, min(limit, 200)), before, known_revision)

    async def aget_turn_snapshot(self, user_id: str, session_id: str, turn_id: str) -> TurnSnapshot:
        from .relational_read.turn_snapshot import turn_snapshot

        return await self._run_threaded(lambda reader: turn_snapshot(reader, user_id, session_id, turn_id))

    async def aget_history_page(
        self, user_id: str, session_id: str, limit: int = 50, before: str | None = None,
        known_revision: str | None = None, turn_id: str | None = None,
    ) -> dict[str, Any]:
        """Read a bounded transcript page without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.get_history_page(user_id, session_id, limit, before, known_revision, turn_id))

    def get_history_page(
        self, user_id: str, session_id: str, limit: int = 50, before: str | None = None,
        known_revision: str | None = None, turn_id: str | None = None,
    ) -> dict[str, Any]:
        from .relational_read.pagination import history_page

        return history_page(self, user_id, session_id, max(1, min(limit, 200)), before, known_revision, turn_id)

    async def alist_workspace_paths(self, user_id: str) -> list[str]:
        """List all non-deleted session workspaces without loading sessions."""
        return await self._run_threaded(lambda reader: reader.list_workspace_paths(user_id))

    async def arename_session(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRenameResult:
        """Rename a session without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.rename_session(user_id, session_id, title))

    async def aupdate_session_workspace(
        self,
        user_id: str,
        session_id: str,
        workspace_path: str | None,
    ) -> SessionWorkspaceUpdateResult:
        """Update a session workspace path without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.update_session_workspace(user_id, session_id, workspace_path))


    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        """Load all source turn identities before deleting a session."""
        return await self._run_threaded(lambda reader: reader.list_session_turn_ids(user_id, session_id))

    async def abackfill_cleared_chat_scopes(
        self,
        session_ids: list[str],
        message_scopes: list[tuple[str, str]],
    ) -> dict[str, int]:
        """Restore durable chat barriers without blocking the event loop."""

        return await self._run_threaded(lambda reader: reader.backfill_cleared_chat_scopes(session_ids, message_scopes))

    async def aget_message_source_identity(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatMessageSourceIdentity | None:
        """Resolve one persisted message to its exact memory source identity."""
        return await self._run_threaded(lambda reader: reader.get_message_source_identity(user_id, session_id, message_id))

    async def alist_message_replacement_source_identities(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> list[ChatMessageSourceIdentity]:
        """Snapshot every persisted revision of one logical message."""

        return await self._run_threaded(lambda reader: reader.list_message_replacement_source_identities(user_id, session_id, message_id))

    async def alist_session_message_source_identities(
        self,
        user_id: str,
        session_id: str,
    ) -> list[ChatMessageSourceIdentity]:
        """Snapshot message sources before clearing a transcript."""
        return await self._run_threaded(lambda reader: reader.list_session_message_source_identities(user_id, session_id))

    async def aget_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = 200,
    ) -> list[ChatDisplayMessage]:
        """Load conversation history without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.get_conversation_history(user_id, session_id, limit))

    async def aget_latest_context_usage(
        self,
        user_id: str,
        session_id: str,
    ) -> "ChatContextUsageSnapshot | None":
        """Load the latest durable visible-answer usage without blocking."""

        return await self._run_threaded(lambda reader: reader.get_latest_context_usage(user_id, session_id))

    async def aget_session_attachment_references(
        self,
        user_id: str,
        session_id: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Load recent session attachment references without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.get_session_attachment_references(user_id, session_id, limit))

    async def aget_display_history(
        self,
        user_id: str,
        session_id: str,
        limit: int = 200,
    ) -> list[ChatDisplayMessage]:
        """Load display history without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.get_display_history(user_id, session_id, limit))

    async def aget_display_message(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
        final_only: bool = False,
    ) -> ChatDisplayMessage | None:
        """Load one visible display message without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.get_display_message(user_id, session_id, message_id, final_only))

    async def aget_attachment_location(self, user_id: str, session_id: str, attachment_id: str) -> ChatAttachmentLocation | None:
        """Resolve attachment ownership without exposing a database handle to the gateway."""
        return await self._run_threaded(lambda reader: reader.get_attachment_location(user_id, session_id, attachment_id))







    async def acomplete_global_clear(self) -> bool:
        """Release the global barrier after external conversation cleanup."""

        return await self._run_threaded(lambda reader: reader.complete_global_clear())

    async def aget_interrupted_global_clear_count(self) -> int | None:
        """Read the count committed by an interrupted global clear."""

        return await self._run_threaded(lambda reader: reader.get_interrupted_global_clear_count())

    async def areset_user_turn_delivery_after_failed_clear(self) -> int:
        """Make surviving turns replayable after a failed destructive clear."""
        return await self._run_threaded(lambda reader: reader.reset_user_turn_delivery_after_failed_clear())

    async def alist_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: "ChatUserTurnDeliveryRecord | None" = None,
    ) -> list["ChatUserTurnDeliveryRecord"]:
        """Load non-terminal runtime envelopes without blocking the event loop."""
        return await self._run_threaded(lambda reader: reader.list_recoverable_user_turn_deliveries(user_id, session_id, limit, after))

    async def abump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list["ChatUserTurnDeliveryRecord"]:
        """Invalidate session-local survivor attempts without blocking."""
        return await self._run_threaded(lambda reader: reader.bump_nonterminal_user_turn_delivery_attempts(user_id, session_id, excluded_turn_ids, updated_at_ms, bump_survivors))







    def _list_chat_snapshot_asset_references(
        self,
        *,
        session_id: str,
        turn_ids: list[str],
        delete_entire_session: bool,
    ) -> list[tuple[str, str]]:
        return self._asset_inventory.list_snapshot_asset_references(
            session_id=session_id,
            turn_ids=turn_ids,
            delete_entire_session=delete_entire_session,
        )


    def _query_chat_message_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        message_kinds: tuple[str, ...] | None,
        visible_only: bool,
        exclude_replaced: bool,
        start_message_id: str | None = None,
    ) -> list[ChatRow]:
        query = statement("""
            SELECT message_id, session_id, turn_id, user_id, role, message_kind,
                   content_text, payload_json, is_final, is_visible, created_at_ms,
                     sequence_no, replaces_message_id, replaced_by_message_id, persona_id,
                     reply_to_message_id, label_json
            FROM {part0}
            WHERE user_id = ?
              AND session_id = ?
        """, part0=CHAT_MESSAGES_TABLE)
        params: list[Any] = [user_id, session_id]
        if message_kinds:
            query += statement(""" AND message_kind IN ({part0})""", part0=', '.join('?' for _ in message_kinds))
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
        query += statement(""" ORDER BY {part0}""", part0=MESSAGE_ORDER_SQL)
        return conn.execute(query, params).fetchall()

    def _query_turn_rows(self, *, user_id: str, session_id: str) -> list[ChatRow]:
        conn = self._get_conn()
        return conn.execute(
            statement("""
            SELECT turn_id, session_id, user_id, status, response_mode, execution_mode,
                     ux_plan_json, created_at_ms, updated_at_ms, completed_at_ms,
                     error_text, run_id, run_revision, run_disposition
            FROM {part0}
            WHERE user_id = ?
              AND session_id = ?
            ORDER BY created_at_ms ASC, updated_at_ms ASC
            """, part0=CHAT_TURNS_TABLE),
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
    def _row_to_display_message(row: ChatRow) -> ChatDisplayMessage | None:
        return row_to_display_message(row)

    @staticmethod
    def _build_reply_preview(target_row: ChatRow | None) -> dict[str, Any] | None:
        return build_reply_preview(target_row)

    def _attach_reply_previews(
        self,
        *,
        rows: list[ChatRow],
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
                        statement("""
                    SELECT message_id, role, message_kind, content_text
                    FROM {part0}
                    WHERE message_id = ?
                      AND user_id = ?
                      AND session_id = ?
                      AND is_visible = 1
                    """, part0=CHAT_MESSAGES_TABLE),
                        (reply_to_message_id, target_user_id, target_session_id),
                    )
                    .fetchone()
                )
            message.reply_to = self._build_reply_preview(target_row)

    @staticmethod
    def _row_to_session_summary(row: ChatRow) -> ChatSessionSummary:
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

    async def _run_threaded(self, operation: Callable[[RelationalChatReadRepository], ReadResult]) -> ReadResult:
        return await asyncio.to_thread(self._run_isolated, operation)

    def _run_isolated(self, operation: Callable[[RelationalChatReadRepository], ReadResult]) -> ReadResult:
        service = self.fork()
        try:
            return operation(service)
        finally:
            service.close()


    def fork(self) -> RelationalChatReadRepository:
        return RelationalChatReadRepository(
            database=self.database,
            workspace_preferences=self.workspace_preferences,
            asset_inventory=self._asset_inventory,
        )


def get_chat_trace_read_service() -> Any:
    """Get the shared ChatTraceReadService instance."""
    from ...runtime_trace.chat_trace.read_service import (
        get_chat_trace_read_service as _get_chat_trace_read_service,
    )

    return _get_chat_trace_read_service()
