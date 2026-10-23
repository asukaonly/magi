"""Chat read and cleanup contracts without storage-driver or path dependencies."""

from __future__ import annotations

from typing import Any, Protocol

from ..core.chat_read_models import (
    ChatAttachmentLocation,
    ChatDisplayMessage,
    ChatMessageSourceIdentity,
    ChatSessionRenameResult,
    ChatSessionSummary,
    SessionWorkspaceUpdateResult,
)
from .contracts import ChatContextUsageSnapshot, ChatUserTurnDeliveryRecord
from .workspace_preferences import RecentWorkspaceRepository
from .ownership_ports import ChatAssetOwnershipRepository


class ChatQueryRepository(Protocol):
    """Read-only conversation queries."""

    def close(self) -> None: ...

    async def aget_session_summary(
        self, user_id: str, session_id: str
    ) -> ChatSessionSummary | None: ...

    async def aget_session_summaries_batch(
        self, user_id: str, session_ids: list[str]
    ) -> dict[str, "ChatSessionSummary"]: ...

    async def alist_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]: ...

    async def alist_session_page(
        self,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
    ) -> dict[str, Any]: ...

    def list_session_page(
        self,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
    ) -> dict[str, Any]: ...

    async def aget_history_page(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]: ...

    def get_history_page(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def alist_workspace_paths(self, user_id: str) -> list[str]: ...

    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]: ...

    async def aget_message_source_identity(
        self, user_id: str, session_id: str, message_id: str
    ) -> ChatMessageSourceIdentity | None: ...

    async def alist_message_replacement_source_identities(
        self, user_id: str, session_id: str, message_id: str
    ) -> list[ChatMessageSourceIdentity]: ...

    async def alist_session_message_source_identities(
        self, user_id: str, session_id: str
    ) -> list[ChatMessageSourceIdentity]: ...

    async def aget_conversation_history(
        self, user_id: str, session_id: str, limit: int | None = 200
    ) -> list[ChatDisplayMessage]: ...

    async def aget_latest_context_usage(
        self, user_id: str, session_id: str
    ) -> "ChatContextUsageSnapshot | None": ...

    async def aget_session_attachment_references(
        self, user_id: str, session_id: str, limit: int = 40
    ) -> list[dict[str, Any]]: ...

    async def aget_display_history(
        self, user_id: str, session_id: str, limit: int = 200
    ) -> list[ChatDisplayMessage]: ...

    async def aget_display_message(
        self, user_id: str, session_id: str, message_id: str, final_only: bool = False
    ) -> ChatDisplayMessage | None: ...

    async def aget_attachment_location(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> ChatAttachmentLocation | None: ...

    def get_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = 200,
        *,
        start_message_id: str | None = None,
    ) -> list[ChatDisplayMessage]: ...

    def get_latest_context_usage(
        self, user_id: str, session_id: str
    ) -> ChatContextUsageSnapshot | None: ...

    def get_session_attachment_references(
        self, user_id: str, session_id: str, limit: int = 40
    ) -> list[dict[str, Any]]: ...

    def get_display_history(
        self, user_id: str, session_id: str, limit: int = 200
    ) -> list[ChatDisplayMessage]: ...

    def get_display_message(
        self, user_id: str, session_id: str, message_id: str, final_only: bool = False
    ) -> ChatDisplayMessage | None: ...

    def get_attachment_location(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> ChatAttachmentLocation | None: ...

    def list_session_turn_ids(self, user_id: str, session_id: str) -> list[str]: ...

    def get_message_source_identity(
        self, user_id: str, session_id: str, message_id: str
    ) -> ChatMessageSourceIdentity | None: ...

    def list_message_replacement_source_identities(
        self, user_id: str, session_id: str, message_id: str
    ) -> list[ChatMessageSourceIdentity]: ...

    def list_session_message_source_identities(
        self, user_id: str, session_id: str
    ) -> list[ChatMessageSourceIdentity]: ...

    def get_session_summary(self, user_id: str, session_id: str) -> ChatSessionSummary | None: ...

    def get_session_summaries_batch(
        self, user_id: str, session_ids: list[str]
    ) -> dict[str, ChatSessionSummary]: ...

    def list_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]: ...

    def list_workspace_paths(self, user_id: str) -> list[str]: ...


class ChatReadRepository(ChatQueryRepository, Protocol):
    def get_attachment_payload(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> dict[str, Any] | None: ...

    async def aget_attachment_payload(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> dict[str, Any] | None: ...


class ChatSessionCommands(Protocol):
    """Session metadata mutations."""

    async def acreate_new_session(
        self, user_id: str, workspace_path: str | None = None, idempotency_key: str | None = None
    ) -> str: ...

    async def arename_session(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRenameResult: ...

    async def aupdate_session_workspace(
        self, user_id: str, session_id: str, workspace_path: str | None
    ) -> SessionWorkspaceUpdateResult: ...

    def create_new_session(
        self, user_id: str, workspace_path: str | None = None, idempotency_key: str | None = None
    ) -> str: ...

    def rename_session(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRenameResult: ...

    def update_session_workspace(
        self, user_id: str, session_id: str, workspace_path: str | None
    ) -> SessionWorkspaceUpdateResult: ...


class ChatCleanupCommands(Protocol):
    """Application-owned durable content deletion."""

    async def adelete_session(self, user_id: str, session_id: str) -> None: ...

    async def abackfill_cleared_chat_scopes(
        self, session_ids: list[str], message_scopes: list[tuple[str, str]]
    ) -> dict[str, int]: ...

    async def aforget_message_artifacts(
        self, user_id: str, session_id: str, message_id: str
    ) -> bool: ...

    async def aclear_conversation_history_snapshot(
        self, user_id: str, session_id: str, message_ids: list[str], turn_ids: list[str]
    ) -> None: ...

    async def aclear_conversation_history(self, user_id: str, session_id: str) -> None: ...

    async def aclear_all_sessions(self) -> int: ...

    async def arecover_interrupted_global_clear(self) -> bool: ...

    async def acomplete_global_clear(self) -> bool: ...

    async def aget_interrupted_global_clear_count(self) -> int | None: ...

    def forget_message_artifacts(self, user_id: str, session_id: str, message_id: str) -> bool: ...

    def clear_conversation_history(self, user_id: str, session_id: str) -> None: ...

    def clear_conversation_history_snapshot(
        self, user_id: str, session_id: str, message_ids: list[str], turn_ids: list[str]
    ) -> None: ...

    def backfill_cleared_chat_scopes(
        self, session_ids: list[str], message_scopes: list[tuple[str, str]]
    ) -> dict[str, int]: ...

    def delete_session(self, user_id: str, session_id: str) -> None: ...

    def clear_all_sessions(self) -> int: ...

    def recover_interrupted_global_clear(self) -> bool: ...

    def complete_global_clear(self) -> bool: ...

    def get_interrupted_global_clear_count(self) -> int | None: ...


class ChatDeliveryRecovery(Protocol):
    """Runtime acceptance recovery and retry fences."""

    async def areset_user_turn_delivery_after_failed_clear(self) -> int: ...

    async def alist_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: "ChatUserTurnDeliveryRecord | None" = None,
    ) -> list["ChatUserTurnDeliveryRecord"]: ...

    async def abump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list["ChatUserTurnDeliveryRecord"]: ...

    def reset_user_turn_delivery_after_failed_clear(self) -> int: ...

    def list_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: ChatUserTurnDeliveryRecord | None = None,
    ) -> list[ChatUserTurnDeliveryRecord]: ...

    def bump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list[ChatUserTurnDeliveryRecord]: ...


class ChatApplication(
    ChatReadRepository,
    ChatSessionCommands,
    ChatCleanupCommands,
    ChatDeliveryRecovery,
    ChatAssetOwnershipRepository,
    Protocol,
):
    """Composition contract; consumers select their capability-specific port."""

    workspace_preferences: RecentWorkspaceRepository
