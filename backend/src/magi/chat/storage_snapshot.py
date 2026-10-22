"""Validated, complete logical chat state for offline transfer and recovery."""

from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field


class ChatSnapshotRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionsSnapshot(ChatSnapshotRecord):
    session_id: str
    user_id: str
    title: str
    title_overridden: int
    summary: str
    created_at_ms: int
    updated_at_ms: int
    last_message_at_ms: int | None
    last_user_message_at_ms: int | None
    last_message_preview: str
    last_user_message_preview: str
    message_count: int
    workspace_path: str | None
    history_version: int
    archived_at_ms: int | None
    deleted_at_ms: int | None


class SessionCreationRequestsSnapshot(ChatSnapshotRecord):
    user_id: str
    idempotency_key: str
    session_id: str
    created_at_ms: int


class TurnsSnapshot(ChatSnapshotRecord):
    turn_id: str
    session_id: str
    user_id: str
    trace_id: str | None
    status: str
    response_mode: str
    execution_mode: str | None
    ux_plan_json: str
    created_at_ms: int
    updated_at_ms: int
    completed_at_ms: int | None
    error_text: str | None
    run_id: str | None
    run_revision: int
    run_disposition: str | None
    response_anchor_turn_id: str | None
    superseded_by_turn_id: str | None
    supersession_reason: str | None


class MessagesSnapshot(ChatSnapshotRecord):
    message_id: str
    session_id: str
    turn_id: str | None
    user_id: str
    role: str
    message_kind: str
    content_text: str | None
    payload_json: str
    is_final: int
    is_visible: int
    created_at_ms: int
    sequence_no: int
    replaces_message_id: str | None
    replaced_by_message_id: str | None
    persona_id: str | None
    reply_to_message_id: str | None
    label_json: str | None


class PostTurnBatchesSnapshot(ChatSnapshotRecord):
    batch_id: str
    session_id: str
    state: str
    attempt_count: int
    next_attempt_at_ms: int
    lease_token: str | None
    lease_expires_at_ms: int | None
    analysis_json: str | None
    settled_json: str
    last_error: str | None
    updated_at_ms: int


class PostTurnOutcomesSnapshot(ChatSnapshotRecord):
    outcome_id: str
    source_turn_id: str
    session_id: str
    user_id: str
    persona_id: str | None
    source_message_ids: str
    accepted_at_ms: int
    execution_mode: str | None
    delivery_attempt_no: int | None
    task_id: str | None
    task_attempt: int | None
    batch_id: str | None


class AssistantMemoryOutboxSnapshot(ChatSnapshotRecord):
    canonical_message_id: str
    user_id: str
    session_id: str
    turn_id: str
    content_text: str
    created_at_ms: int
    state: str
    attempt_count: int
    next_attempt_at_ms: int
    lease_token: str | None
    lease_expires_at_ms: int | None
    last_error: str | None
    updated_at_ms: int


class AttachmentsSnapshot(ChatSnapshotRecord):
    attachment_id: str
    session_id: str
    turn_id: str | None
    message_id: str
    user_id: str
    kind: str
    original_name: str
    mime_type: str
    size_bytes: int
    storage_rel_path: str
    sha256: str | None
    created_at_ms: int


class CodeDelegationArtifactsSnapshot(ChatSnapshotRecord):
    workspace_path: str
    session_id: str
    delegation_id: str
    turn_id: str
    created_at_ms: int


class ContextSummariesSnapshot(ChatSnapshotRecord):
    summary_id: str
    session_id: str
    parent_summary_id: str | None
    status: str
    summary_kind: str
    persona_scope: str | None
    covered_from_message_id: str | None
    covered_to_message_id: str | None
    first_kept_message_id: str | None
    covered_to_sequence_no: int | None
    session_origin: str
    summary_text: str
    prompt_profile: str
    model_provider: str | None
    model_id: str | None
    token_count_before: int | None
    token_count_after: int | None
    quality_status: str | None
    created_at_ms: int
    updated_at_ms: int


class ContextUsageSnapshotsSnapshot(ChatSnapshotRecord):
    turn_id: str
    session_id: str
    user_id: str
    used_tokens: int
    context_window: int
    input_capacity: int
    compaction_threshold: int
    measurement: str
    model_provider: str | None
    model_id: str | None
    updated_at_ms: int


class MessageAssetRefsSnapshot(ChatSnapshotRecord):
    message_id: str
    asset_key: str
    storage_rel_path: str
    asset_kind: str
    created_at_ms: int


class MessageCodeDelegationRefsSnapshot(ChatSnapshotRecord):
    message_id: str
    session_id: str
    delegation_id: str
    turn_id: str
    workspace_path: str
    created_at_ms: int


class ModelContextBoundariesSnapshot(ChatSnapshotRecord):
    boundary_id: str
    session_id: str
    generation: int
    boundary_no: int
    surface_revision: int
    epoch_id: str
    boundary_kind: str
    turn_id: str | None
    run_id: str | None
    step_index: int | None
    request_options_json: str
    created_at_ms: int


class ModelContextEpochsSnapshot(ChatSnapshotRecord):
    epoch_id: str
    session_id: str
    generation: int
    system_hash: str
    system_prompt: str
    tools_hash: str
    tools_json: str
    created_at_ms: int


class ModelContextEventsSnapshot(ChatSnapshotRecord):
    event_id: str
    session_id: str
    generation: int
    sequence_no: int
    operation: str
    item_kind: str
    item_json: str
    turn_id: str | None
    run_id: str | None
    step_index: int | None
    created_at_ms: int


class ModelContextHeadsSnapshot(ChatSnapshotRecord):
    session_id: str
    generation: int
    revision: int
    accepted_revision: int
    last_sequence_no: int
    updated_at_ms: int


class ModelContextRevisionsSnapshot(ChatSnapshotRecord):
    session_id: str
    generation: int
    revision: int
    parent_revision: int
    branch_kind: str
    run_id: str | None
    item_count: int
    created_at_ms: int


class ModelContextRunHeadsSnapshot(ChatSnapshotRecord):
    session_id: str
    run_id: str
    turn_id: str | None
    generation: int
    base_revision: int
    working_revision: int
    status: str
    updated_at_ms: int


class ModelContextSurfaceNodesSnapshot(ChatSnapshotRecord):
    session_id: str
    generation: int
    revision: int
    position: int
    event_sequence_no: int


class OutboundDeliveriesSnapshot(ChatSnapshotRecord):
    delivery_id: str
    message_id: str
    session_id: str
    user_id: str
    endpoint_json: str
    content_json: str
    state: str
    attempt_count: int
    retry_safe: int
    next_attempt_at_ms: int
    lease_token: str | None
    lease_expires_at_ms: int | None
    expires_at_ms: int
    receipt_json: str | None
    last_error: str | None
    created_at_ms: int
    updated_at_ms: int


class RunConsumedEventsSnapshot(ChatSnapshotRecord):
    session_id: str
    run_id: str
    revision: int
    message_id: str
    recorded_at_ms: int


class TaskExecutionBudgetsSnapshot(ChatSnapshotRecord):
    root_turn_id: str
    max_llm_calls: int
    llm_calls_used: int
    max_worker_launches: int
    worker_launches_used: int
    created_at_ms: int


class UserTurnDeliverySnapshot(ChatSnapshotRecord):
    turn_id: str
    projection_completed: int
    delivery_attempt_no: int
    delivery_state: str
    current_command_id: int | None
    runtime_envelope_json: str
    request_fingerprint: str
    created_at_ms: int
    updated_at_ms: int


class WorkspaceSessionCleanupSnapshot(ChatSnapshotRecord):
    workspace_path: str
    session_id: str
    created_at_ms: int


class ClearedMessageScopesSnapshot(ChatSnapshotRecord):
    session_id: str
    message_id: str
    cleared_at_ms: int


class ClearedSessionScopesSnapshot(ChatSnapshotRecord):
    session_id: str
    cleared_at_ms: int


class GlobalClearIntentSnapshot(ChatSnapshotRecord):
    intent_key: str
    requested_at_ms: int
    session_count: int


class RetiredTurnsSnapshot(ChatSnapshotRecord):
    turn_key: str
    retired_at_ms: int


class ReadRevisionsSnapshot(ChatSnapshotRecord):
    user_id: str
    scope: str
    epoch: str
    revision: int


class ChatStorageSnapshot(ChatSnapshotRecord):
    version: Literal[1] = 1
    sessions: list[SessionsSnapshot] = Field(default_factory=list)
    session_creation_requests: list[SessionCreationRequestsSnapshot] = Field(default_factory=list)
    turns: list[TurnsSnapshot] = Field(default_factory=list)
    messages: list[MessagesSnapshot] = Field(default_factory=list)
    post_turn_batches: list[PostTurnBatchesSnapshot] = Field(default_factory=list)
    post_turn_outcomes: list[PostTurnOutcomesSnapshot] = Field(default_factory=list)
    assistant_memory_outbox: list[AssistantMemoryOutboxSnapshot] = Field(default_factory=list)
    attachments: list[AttachmentsSnapshot] = Field(default_factory=list)
    code_delegation_artifacts: list[CodeDelegationArtifactsSnapshot] = Field(default_factory=list)
    context_summaries: list[ContextSummariesSnapshot] = Field(default_factory=list)
    context_usage_snapshots: list[ContextUsageSnapshotsSnapshot] = Field(default_factory=list)
    message_asset_refs: list[MessageAssetRefsSnapshot] = Field(default_factory=list)
    message_code_delegation_refs: list[MessageCodeDelegationRefsSnapshot] = Field(default_factory=list)
    model_context_boundaries: list[ModelContextBoundariesSnapshot] = Field(default_factory=list)
    model_context_epochs: list[ModelContextEpochsSnapshot] = Field(default_factory=list)
    model_context_events: list[ModelContextEventsSnapshot] = Field(default_factory=list)
    model_context_heads: list[ModelContextHeadsSnapshot] = Field(default_factory=list)
    model_context_revisions: list[ModelContextRevisionsSnapshot] = Field(default_factory=list)
    model_context_run_heads: list[ModelContextRunHeadsSnapshot] = Field(default_factory=list)
    model_context_surface_nodes: list[ModelContextSurfaceNodesSnapshot] = Field(default_factory=list)
    outbound_deliveries: list[OutboundDeliveriesSnapshot] = Field(default_factory=list)
    run_consumed_events: list[RunConsumedEventsSnapshot] = Field(default_factory=list)
    task_execution_budgets: list[TaskExecutionBudgetsSnapshot] = Field(default_factory=list)
    user_turn_delivery: list[UserTurnDeliverySnapshot] = Field(default_factory=list)
    workspace_session_cleanup: list[WorkspaceSessionCleanupSnapshot] = Field(default_factory=list)
    cleared_message_scopes: list[ClearedMessageScopesSnapshot] = Field(default_factory=list)
    cleared_session_scopes: list[ClearedSessionScopesSnapshot] = Field(default_factory=list)
    global_clear_intent: list[GlobalClearIntentSnapshot] = Field(default_factory=list)
    retired_turns: list[RetiredTurnsSnapshot] = Field(default_factory=list)
    read_revisions: list[ReadRevisionsSnapshot] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in type(self).model_fields if name != "version")


class ChatStateTransfer(Protocol):
    async def export_state(self) -> ChatStorageSnapshot: ...
    async def import_state(self, snapshot: ChatStorageSnapshot, *, replace: bool = False) -> None: ...
