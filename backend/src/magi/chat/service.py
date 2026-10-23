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
from .ownership_ports import ChatAssetOwnership, ChatAssetOwnershipRepository


from collections.abc import Callable
from typing import TypeVar
from .cleanup_plan import ChatCleanupPlan, ChatCleanupTransactions
from ..utils.runtime import RuntimePaths
from ..core.chat_assets.paths import resolve_chat_attachment_file
from ..core.chat_cleanup import ChatSurfaceCleanupPendingError
from .asset_gc import ChatAssetGC
from ..runtime_trace.content_port import TraceContentRepository
from ..core.code_agent_artifacts import CodeAgentArtifactGC, WorkspaceSessionArtifactGC
from ..core.chat_assets.mutations import run_chat_asset_mutation
from .read_ports import ChatQueryRepository, ChatSessionCommands, ChatDeliveryRecovery

Result = TypeVar("Result")


class ChatSurfacePersistence(
    ChatQueryRepository,
    ChatSessionCommands,
    ChatDeliveryRecovery,
    ChatCleanupTransactions,
    ChatAssetOwnershipRepository,
    Protocol,
):
    workspace_preferences: RecentWorkspaceRepository

    def fork(self) -> ChatSurfacePersistence: ...
    def backfill_cleared_chat_scopes(
        self, session_ids: list[str], message_scopes: list[tuple[str, str]]
    ) -> dict[str, int]: ...
    async def abackfill_cleared_chat_scopes(
        self, session_ids: list[str], message_scopes: list[tuple[str, str]]
    ) -> dict[str, int]: ...
    def complete_global_clear(self) -> bool: ...
    async def acomplete_global_clear(self) -> bool: ...
    def get_interrupted_global_clear_count(self) -> int | None: ...
    async def aget_interrupted_global_clear_count(self) -> int | None: ...


class ChatService:
    """Coordinate chat capabilities and committed cross-owner cleanup."""

    def __init__(
        self,
        *,
        repository: ChatSurfacePersistence,
        trace_content: TraceContentRepository,
        asset_gc: ChatAssetGC,
        runtime_paths: RuntimePaths,
        code_gc: CodeAgentArtifactGC | None = None,
        workspace_gc: WorkspaceSessionArtifactGC | None = None,
    ) -> None:
        self._runtime_paths = runtime_paths
        self.repository = repository
        self.trace_content = trace_content
        self._asset_gc = asset_gc
        self._code_agent_artifact_gc = code_gc or CodeAgentArtifactGC()
        self._workspace_session_artifact_gc = workspace_gc or WorkspaceSessionArtifactGC()
        self.workspace_preferences = repository.workspace_preferences

    def get_active_asset_ownership(self) -> ChatAssetOwnership | None:
        return self.repository.get_active_asset_ownership()

    def _run_isolated(self, operation: Callable[[ChatService], Result]) -> Result:
        service = ChatService(
            repository=self.repository.fork(),
            trace_content=self.trace_content,
            asset_gc=self._asset_gc,
            runtime_paths=self._runtime_paths,
            code_gc=self._code_agent_artifact_gc,
            workspace_gc=self._workspace_session_artifact_gc,
        )
        try:
            return operation(service)
        finally:
            service.close()

    def _cleanup(self, plan: ChatCleanupPlan, finish: Callable[[ChatCleanupPlan], None]) -> None:
        try:
            if plan.kind == "global":
                self._clear_all_runtime_trace_rows()
                self._clear_all_chat_assets()
            elif plan.whole_session:
                self.trace_content.delete_session(user_id=plan.user_id, session_id=plan.session_id)
            else:
                for turn_id in plan.trace_turn_ids:
                    self.trace_content.delete_turn(
                        user_id=plan.user_id, session_id=plan.session_id, turn_id=turn_id
                    )
            if plan.kind != "global":
                self._asset_gc.delete_message_assets(plan.asset_references)
            self._code_agent_artifact_gc.delete_references(plan.code_references)
            self._workspace_session_artifact_gc.delete_references(plan.workspace_references)
            finish(plan)
        except Exception as exc:
            if plan.kind == "global":
                raise
            raise ChatSurfaceCleanupPendingError(
                "Chat content was removed but private cleanup is pending",
                user_id=plan.user_id,
                session_id=plan.session_id,
                message_ids=plan.message_ids,
                turn_ids=plan.turn_ids,
            ) from exc

    def _clear_all_runtime_trace_rows(self) -> None:
        self.trace_content.clear_all()

    def _clear_all_chat_assets(self) -> None:
        self._asset_gc.clear_all_assets()

    def delete_session(self, user_id: str, session_id: str) -> None:
        plan = self.repository.prepare_session_cleanup(user_id, session_id)
        if plan is not None:
            self._cleanup(plan, self.repository.finish_session_cleanup)

    def forget_message_artifacts(self, user_id: str, session_id: str, message_id: str) -> bool:
        plan = self.repository.prepare_message_cleanup(user_id, session_id, message_id)
        if plan is None:
            return False
        self._cleanup(plan, self.repository.finish_message_cleanup)
        return True

    def clear_conversation_history_snapshot(
        self, user_id: str, session_id: str, message_ids: list[str], turn_ids: list[str]
    ) -> None:
        plan = self.repository.prepare_history_cleanup(user_id, session_id, message_ids, turn_ids)
        if plan is not None:
            self._cleanup(plan, self.repository.finish_history_cleanup)

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        messages, turns = self.repository.history_cleanup_scope(user_id, session_id)
        self.clear_conversation_history_snapshot(user_id, session_id, messages, turns)

    def clear_all_sessions(self) -> int:
        plan = self.repository.prepare_global_cleanup()
        self._cleanup(plan, self.repository.finish_global_cleanup)
        return plan.removed_count

    def recover_interrupted_global_clear(self) -> bool:
        if self.repository.get_interrupted_global_clear_count() is None:
            return False
        self.clear_all_sessions()
        return True

    def close(self) -> None:
        return self.repository.close()

    async def acreate_new_session(
        self, user_id: str, workspace_path: str | None = None, idempotency_key: str | None = None
    ) -> str:
        return await self.repository.acreate_new_session(user_id, workspace_path, idempotency_key)

    async def aget_session_summary(
        self, user_id: str, session_id: str
    ) -> ChatSessionSummary | None:
        return await self.repository.aget_session_summary(user_id, session_id)

    async def aget_session_summaries_batch(
        self, user_id: str, session_ids: list[str]
    ) -> dict[str, "ChatSessionSummary"]:
        return await self.repository.aget_session_summaries_batch(user_id, session_ids)

    async def alist_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        return await self.repository.alist_sessions(user_id, limit)

    async def alist_session_page(
        self,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
    ) -> dict[str, Any]:
        return await self.repository.alist_session_page(user_id, limit, before, known_revision)

    def list_session_page(
        self,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
    ) -> dict[str, Any]:
        return self.repository.list_session_page(user_id, limit, before, known_revision)

    async def aget_history_page(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.repository.aget_history_page(
            user_id, session_id, limit, before, known_revision, turn_id
        )

    def get_history_page(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        known_revision: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        return self.repository.get_history_page(
            user_id, session_id, limit, before, known_revision, turn_id
        )

    async def alist_workspace_paths(self, user_id: str) -> list[str]:
        return await self.repository.alist_workspace_paths(user_id)

    async def arename_session(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRenameResult:
        return await self.repository.arename_session(user_id, session_id, title)

    async def aupdate_session_workspace(
        self, user_id: str, session_id: str, workspace_path: str | None
    ) -> SessionWorkspaceUpdateResult:
        return await self.repository.aupdate_session_workspace(user_id, session_id, workspace_path)

    async def adelete_session(self, user_id: str, session_id: str) -> None:
        return await run_chat_asset_mutation(
            self._run_isolated, lambda service: service.delete_session(user_id, session_id)
        )

    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        return await self.repository.alist_session_turn_ids(user_id, session_id)

    async def abackfill_cleared_chat_scopes(
        self, session_ids: list[str], message_scopes: list[tuple[str, str]]
    ) -> dict[str, int]:
        return await self.repository.abackfill_cleared_chat_scopes(session_ids, message_scopes)

    async def aget_message_source_identity(
        self, user_id: str, session_id: str, message_id: str
    ) -> ChatMessageSourceIdentity | None:
        return await self.repository.aget_message_source_identity(user_id, session_id, message_id)

    async def alist_message_replacement_source_identities(
        self, user_id: str, session_id: str, message_id: str
    ) -> list[ChatMessageSourceIdentity]:
        return await self.repository.alist_message_replacement_source_identities(
            user_id, session_id, message_id
        )

    async def alist_session_message_source_identities(
        self, user_id: str, session_id: str
    ) -> list[ChatMessageSourceIdentity]:
        return await self.repository.alist_session_message_source_identities(user_id, session_id)

    async def aget_conversation_history(
        self, user_id: str, session_id: str, limit: int | None = 200
    ) -> list[ChatDisplayMessage]:
        return await self.repository.aget_conversation_history(user_id, session_id, limit)

    async def aget_latest_context_usage(
        self, user_id: str, session_id: str
    ) -> "ChatContextUsageSnapshot | None":
        return await self.repository.aget_latest_context_usage(user_id, session_id)

    async def aget_session_attachment_references(
        self, user_id: str, session_id: str, limit: int = 40
    ) -> list[dict[str, Any]]:
        return await self.repository.aget_session_attachment_references(user_id, session_id, limit)

    async def aget_display_history(
        self, user_id: str, session_id: str, limit: int = 200
    ) -> list[ChatDisplayMessage]:
        return await self.repository.aget_display_history(user_id, session_id, limit)

    async def aget_display_message(
        self, user_id: str, session_id: str, message_id: str, final_only: bool = False
    ) -> ChatDisplayMessage | None:
        return await self.repository.aget_display_message(
            user_id, session_id, message_id, final_only
        )

    async def aget_attachment_location(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> ChatAttachmentLocation | None:
        return await self.repository.aget_attachment_location(user_id, session_id, attachment_id)

    async def aget_attachment_payload(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> dict[str, Any] | None:
        import asyncio

        return await asyncio.to_thread(
            self._run_isolated,
            lambda service: service.get_attachment_payload(user_id, session_id, attachment_id),
        )

    async def aforget_message_artifacts(
        self, user_id: str, session_id: str, message_id: str
    ) -> bool:
        return await run_chat_asset_mutation(
            self._run_isolated,
            lambda service: service.forget_message_artifacts(user_id, session_id, message_id),
        )

    async def aclear_conversation_history_snapshot(
        self, user_id: str, session_id: str, message_ids: list[str], turn_ids: list[str]
    ) -> None:
        return await run_chat_asset_mutation(
            self._run_isolated,
            lambda service: service.clear_conversation_history_snapshot(
                user_id, session_id, message_ids, turn_ids
            ),
        )

    async def aclear_conversation_history(self, user_id: str, session_id: str) -> None:
        return await run_chat_asset_mutation(
            self._run_isolated,
            lambda service: service.clear_conversation_history(user_id, session_id),
        )

    async def aclear_all_sessions(self) -> int:
        return await run_chat_asset_mutation(
            self._run_isolated, lambda service: service.clear_all_sessions()
        )

    async def arecover_interrupted_global_clear(self) -> bool:
        return await run_chat_asset_mutation(
            self._run_isolated, lambda service: service.recover_interrupted_global_clear()
        )

    async def acomplete_global_clear(self) -> bool:
        return await self.repository.acomplete_global_clear()

    async def aget_interrupted_global_clear_count(self) -> int | None:
        return await self.repository.aget_interrupted_global_clear_count()

    async def areset_user_turn_delivery_after_failed_clear(self) -> int:
        return await self.repository.areset_user_turn_delivery_after_failed_clear()

    async def alist_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: "ChatUserTurnDeliveryRecord | None" = None,
    ) -> list["ChatUserTurnDeliveryRecord"]:
        return await self.repository.alist_recoverable_user_turn_deliveries(
            user_id, session_id, limit, after
        )

    async def abump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list["ChatUserTurnDeliveryRecord"]:
        return await self.repository.abump_nonterminal_user_turn_delivery_attempts(
            user_id, session_id, excluded_turn_ids, updated_at_ms, bump_survivors
        )

    def get_conversation_history(
        self,
        user_id: str,
        session_id: str,
        limit: int | None = 200,
        *,
        start_message_id: str | None = None,
    ) -> list[ChatDisplayMessage]:
        return self.repository.get_conversation_history(
            user_id, session_id, limit, start_message_id=start_message_id
        )

    def get_latest_context_usage(
        self, user_id: str, session_id: str
    ) -> ChatContextUsageSnapshot | None:
        return self.repository.get_latest_context_usage(user_id, session_id)

    def get_session_attachment_references(
        self, user_id: str, session_id: str, limit: int = 40
    ) -> list[dict[str, Any]]:
        return self.repository.get_session_attachment_references(user_id, session_id, limit)

    def get_display_history(
        self, user_id: str, session_id: str, limit: int = 200
    ) -> list[ChatDisplayMessage]:
        return self.repository.get_display_history(user_id, session_id, limit)

    def get_display_message(
        self, user_id: str, session_id: str, message_id: str, final_only: bool = False
    ) -> ChatDisplayMessage | None:
        return self.repository.get_display_message(user_id, session_id, message_id, final_only)

    def get_attachment_location(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> ChatAttachmentLocation | None:
        return self.repository.get_attachment_location(user_id, session_id, attachment_id)

    def get_attachment_payload(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> dict[str, Any] | None:
        """Resolve an owned attachment into the local internal-read representation."""
        location = self.get_attachment_location(user_id, session_id, attachment_id)
        if location is None:
            return None
        storage_path = resolve_chat_attachment_file(
            location.storage_rel_path,
            session_id=location.session_id,
            turn_id=location.turn_id,
            attachment_id=location.attachment_id,
            runtime_paths=self._runtime_paths,
        )
        if storage_path is None:
            return None
        return {
            "attachment_id": location.attachment_id,
            "turn_id": location.turn_id,
            "kind": location.kind,
            "original_name": location.original_name,
            "mime_type": location.mime_type,
            "size_bytes": location.size_bytes,
            "storage_rel_path": location.storage_rel_path,
            "storage_path": str(storage_path),
            "sha256": location.sha256,
        }

    def list_session_turn_ids(self, user_id: str, session_id: str) -> list[str]:
        return self.repository.list_session_turn_ids(user_id, session_id)

    def backfill_cleared_chat_scopes(
        self, session_ids: list[str], message_scopes: list[tuple[str, str]]
    ) -> dict[str, int]:
        return self.repository.backfill_cleared_chat_scopes(session_ids, message_scopes)

    def get_message_source_identity(
        self, user_id: str, session_id: str, message_id: str
    ) -> ChatMessageSourceIdentity | None:
        return self.repository.get_message_source_identity(user_id, session_id, message_id)

    def list_message_replacement_source_identities(
        self, user_id: str, session_id: str, message_id: str
    ) -> list[ChatMessageSourceIdentity]:
        return self.repository.list_message_replacement_source_identities(
            user_id, session_id, message_id
        )

    def list_session_message_source_identities(
        self, user_id: str, session_id: str
    ) -> list[ChatMessageSourceIdentity]:
        return self.repository.list_session_message_source_identities(user_id, session_id)

    def create_new_session(
        self, user_id: str, workspace_path: str | None = None, idempotency_key: str | None = None
    ) -> str:
        return self.repository.create_new_session(user_id, workspace_path, idempotency_key)

    def get_session_summary(self, user_id: str, session_id: str) -> ChatSessionSummary | None:
        return self.repository.get_session_summary(user_id, session_id)

    def get_session_summaries_batch(
        self, user_id: str, session_ids: list[str]
    ) -> dict[str, ChatSessionSummary]:
        return self.repository.get_session_summaries_batch(user_id, session_ids)

    def list_sessions(self, user_id: str, limit: int = 30) -> list[ChatSessionSummary]:
        return self.repository.list_sessions(user_id, limit)

    def list_workspace_paths(self, user_id: str) -> list[str]:
        return self.repository.list_workspace_paths(user_id)

    def rename_session(self, user_id: str, session_id: str, title: str) -> ChatSessionRenameResult:
        return self.repository.rename_session(user_id, session_id, title)

    def update_session_workspace(
        self, user_id: str, session_id: str, workspace_path: str | None
    ) -> SessionWorkspaceUpdateResult:
        return self.repository.update_session_workspace(user_id, session_id, workspace_path)

    def complete_global_clear(self) -> bool:
        return self.repository.complete_global_clear()

    def get_interrupted_global_clear_count(self) -> int | None:
        return self.repository.get_interrupted_global_clear_count()

    def reset_user_turn_delivery_after_failed_clear(self) -> int:
        return self.repository.reset_user_turn_delivery_after_failed_clear()

    def list_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: ChatUserTurnDeliveryRecord | None = None,
    ) -> list[ChatUserTurnDeliveryRecord]:
        return self.repository.list_recoverable_user_turn_deliveries(
            user_id, session_id, limit, after
        )

    def bump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list[ChatUserTurnDeliveryRecord]:
        return self.repository.bump_nonterminal_user_turn_delivery_attempts(
            user_id, session_id, excluded_turn_ids, updated_at_ms, bump_survivors
        )
