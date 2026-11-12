"""Validated, complete logical chat state for offline transfer and recovery."""

from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field

from magi_plugin_sdk.storage_models.chat_snapshot import (
    ChatSnapshotRecord,
    SessionsSnapshot,
    SessionCreationRequestsSnapshot,
    TurnsSnapshot,
    MessagesSnapshot,
    PostTurnBatchesSnapshot,
    PostTurnOutcomesSnapshot,
    AssistantMemoryOutboxSnapshot,
    AttachmentsSnapshot,
    CodeDelegationArtifactsSnapshot,
    ContextSummariesSnapshot,
    ContextUsageSnapshotsSnapshot,
    MessageAssetRefsSnapshot,
    MessageCodeDelegationRefsSnapshot,
    ModelContextBoundariesSnapshot,
    ModelContextEpochsSnapshot,
    ModelContextEventsSnapshot,
    ModelContextHeadsSnapshot,
    ModelContextRevisionsSnapshot,
    ModelContextRunHeadsSnapshot,
    ModelContextSurfaceNodesSnapshot,
    OutboundDeliveriesSnapshot,
    RunConsumedEventsSnapshot,
    TaskExecutionBudgetsSnapshot,
    UserTurnDeliverySnapshot,
    WorkspaceSessionCleanupSnapshot,
    ClearedMessageScopesSnapshot,
    ClearedSessionScopesSnapshot,
    GlobalClearIntentSnapshot,
    RetiredTurnsSnapshot,
    ReadRevisionsSnapshot,
    ChatStorageSnapshot,
)


































































class ChatStateTransfer(Protocol):
    async def export_state(self) -> ChatStorageSnapshot: ...
    async def import_state(self, snapshot: ChatStorageSnapshot, *, replace: bool = False) -> None: ...
