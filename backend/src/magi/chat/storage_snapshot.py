"""Validated, complete logical chat state for offline transfer and recovery."""

from typing import Protocol

from magi_plugin_sdk.storage_models.chat_snapshot import (
    ChatSnapshotRecord as ChatSnapshotRecord,
    SessionsSnapshot as SessionsSnapshot,
    SessionCreationRequestsSnapshot as SessionCreationRequestsSnapshot,
    TurnsSnapshot as TurnsSnapshot,
    MessagesSnapshot as MessagesSnapshot,
    PostTurnBatchesSnapshot as PostTurnBatchesSnapshot,
    PostTurnOutcomesSnapshot as PostTurnOutcomesSnapshot,
    AssistantMemoryOutboxSnapshot as AssistantMemoryOutboxSnapshot,
    AttachmentsSnapshot as AttachmentsSnapshot,
    CodeDelegationArtifactsSnapshot as CodeDelegationArtifactsSnapshot,
    ContextSummariesSnapshot as ContextSummariesSnapshot,
    ContextUsageSnapshotsSnapshot as ContextUsageSnapshotsSnapshot,
    MessageAssetRefsSnapshot as MessageAssetRefsSnapshot,
    MessageCodeDelegationRefsSnapshot as MessageCodeDelegationRefsSnapshot,
    ModelContextBoundariesSnapshot as ModelContextBoundariesSnapshot,
    ModelContextEpochsSnapshot as ModelContextEpochsSnapshot,
    ModelContextEventsSnapshot as ModelContextEventsSnapshot,
    ModelContextHeadsSnapshot as ModelContextHeadsSnapshot,
    ModelContextRevisionsSnapshot as ModelContextRevisionsSnapshot,
    ModelContextRunHeadsSnapshot as ModelContextRunHeadsSnapshot,
    ModelContextSurfaceNodesSnapshot as ModelContextSurfaceNodesSnapshot,
    OutboundDeliveriesSnapshot as OutboundDeliveriesSnapshot,
    RunConsumedEventsSnapshot as RunConsumedEventsSnapshot,
    TaskExecutionBudgetsSnapshot as TaskExecutionBudgetsSnapshot,
    UserTurnDeliverySnapshot as UserTurnDeliverySnapshot,
    WorkspaceSessionCleanupSnapshot as WorkspaceSessionCleanupSnapshot,
    ClearedMessageScopesSnapshot as ClearedMessageScopesSnapshot,
    ClearedSessionScopesSnapshot as ClearedSessionScopesSnapshot,
    GlobalClearIntentSnapshot as GlobalClearIntentSnapshot,
    RetiredTurnsSnapshot as RetiredTurnsSnapshot,
    ReadRevisionsSnapshot as ReadRevisionsSnapshot,
    ChatStorageSnapshot,
)

class ChatStateTransfer(Protocol):
    async def export_state(self) -> ChatStorageSnapshot: ...
    async def import_state(self, snapshot: ChatStorageSnapshot, *, replace: bool = False) -> None: ...
