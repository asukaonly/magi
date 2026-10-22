"""Chat-owned repository contracts, independent of SQL drivers and filesystem paths."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, Protocol

from magi_plugin_sdk.delivery import DeliveryReceipt
from .ownership_ports import ChatConsumedEventsRepository, ChatArtifactRepository

from ..delivery.outbox import DeliveryState, DeliveryStatus, OutboundDelivery
from ..delivery.routing import DeliveryPlan
from ..memory.post_turn_contracts import PostTurnBatchLease
from .contracts import (
    ChatAssistantMemoryOutboxRecord,
    ChatAssistantMemoryProjection,
    ChatContextSummaryRecord,
    ChatDeliveryFailureFinalization,
    ChatMessageLabel,
    ChatMessageRecord,
    ChatSessionRecord,
    ChatTurnRecord,
    ChatUserTurnDeliveryRecord,
    CreateUserTurnResult,
)
from .model_context import (
    ModelContextBoundary,
    ModelContextCallSnapshot,
    ModelContextItem,
    ModelContextSnapshot,
)


class ChatTranscriptRepository(Protocol):
    async def list_active_workspace_paths(self) -> list[str]: ...

    async def append_message(
        self,
        record: ChatMessageRecord,
        *,
        attachment_payloads: list[dict[str, object]] | None = None,
    ) -> None: ...

    async def append_completion_message_once(
        self, record: ChatMessageRecord
    ) -> tuple[ChatMessageRecord, bool]: ...

    async def mark_message_replaced(
        self, *, message_id: str, replaced_by_message_id: str
    ) -> None: ...

    async def get_latest_message_for_turn(
        self, turn_id: str, *, message_kind: str | None = None
    ) -> ChatMessageRecord | None: ...

    async def get_latest_message_for_session(
        self,
        session_id: str,
        *,
        role: str | None = None,
        message_kind: str | None = None,
        exclude_turn_id: str | None = None,
    ) -> ChatMessageRecord | None: ...

    async def next_sequence_no(self, *, session_id: str) -> int: ...

    async def get_message(self, message_id: str) -> ChatMessageRecord | None: ...

    async def list_messages(
        self, *, session_id: str, start_message_id: str | None = None
    ) -> list[ChatMessageRecord]: ...

    async def list_messages_for_turn(self, *, turn_id: str) -> list[ChatMessageRecord]: ...

    async def update_message_label(
        self,
        *,
        session_id: str,
        message_id: str,
        label: dict[str, object] | ChatMessageLabel | None,
    ) -> ChatMessageRecord | None: ...

    async def hide_message(
        self, *, session_id: str, message_id: str
    ) -> ChatMessageRecord | None: ...

    async def upsert_session(self, record: ChatSessionRecord) -> None: ...

    async def get_history_version(self, session_id: str) -> int: ...

    async def bump_history_version(self, session_id: str) -> int: ...

    async def is_session_available(self, *, user_id: str, session_id: str) -> bool: ...

    async def upsert_turn(self, record: ChatTurnRecord) -> None: ...

    async def get_turn(self, turn_id: str) -> ChatTurnRecord | None: ...

    async def get_latest_superseded_turn(self, *, anchor_turn_id: str) -> ChatTurnRecord | None: ...

    async def get_active_context_summary(
        self, *, session_id: str, summary_kind: str, persona_scope: str | None = None
    ) -> ChatContextSummaryRecord | None: ...

    async def activate_context_summary(self, record: ChatContextSummaryRecord) -> None: ...

    async def activate_context_summary_if_history_version(
        self, record: ChatContextSummaryRecord, *, expected_history_version: int
    ) -> bool: ...


class ChatAcceptanceRepository(Protocol):
    async def create_user_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None = None,
        message_payload: dict[str, object] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        persona_id: str | None = None,
        runtime_envelope: dict[str, object] | None = None,
        request_fingerprint: str = "",
    ) -> ChatMessageRecord: ...

    async def create_user_turn_once(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None = None,
        message_payload: dict[str, object] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        persona_id: str | None = None,
        runtime_envelope: dict[str, object] | None = None,
        request_fingerprint: str = "",
    ) -> CreateUserTurnResult: ...

    async def load_user_turn_once(
        self, *, turn_id: str, request_fingerprint: str
    ) -> CreateUserTurnResult | None: ...

    async def mark_user_turn_projection_completed(
        self, *, turn_id: str, updated_at_ms: int
    ) -> None: ...

    async def get_user_turn_delivery(
        self, *, turn_id: str
    ) -> ChatUserTurnDeliveryRecord | None: ...

    async def prepare_user_turn_delivery_attempt(
        self, *, turn_id: str, expected_attempt_no: int, updated_at_ms: int
    ) -> ChatUserTurnDeliveryRecord | None: ...

    async def mark_user_turn_delivery_queued(
        self, *, turn_id: str, delivery_attempt_no: int, command_id: int, updated_at_ms: int
    ) -> bool: ...

    async def mark_user_turn_delivery_admitted(
        self, *, turn_id: str, delivery_attempt_no: int, command_id: int, updated_at_ms: int
    ) -> bool: ...

    async def mark_user_turn_delivery_terminal(
        self, *, turn_id: str, delivery_attempt_no: int, command_id: int, updated_at_ms: int
    ) -> bool: ...

    async def reconcile_user_turn_terminal_surface(
        self, *, turn_id: str, expected_attempt_no: int, updated_at_ms: int
    ) -> bool: ...

    async def quarantine_invalid_user_turn_delivery(
        self, *, turn_id: str, expected_attempt_no: int, user_message: str, updated_at_ms: int
    ) -> bool: ...


class ChatOutcomeRepository(Protocol):
    async def commit_user_turn_assistant_outcome(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        messages: list[ChatMessageRecord],
        attachment_payloads_by_message_id: dict[str, list[dict[str, object]] | None],
        trace_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_mode: str,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        terminal_status: str = "completed",
        terminal_error: str | None = None,
        delivery_plan: DeliveryPlan | None = None,
    ) -> list[ChatMessageRecord] | None: ...

    async def commit_unmanaged_assistant_outcome(
        self,
        *,
        post_turn_source: Literal["conversation", "bootstrap"],
        turn_id: str,
        messages: list[ChatMessageRecord],
        attachment_payloads_by_message_id: dict[str, list[dict[str, object]] | None],
        trace_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_mode: str,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        terminal_status: str = "completed",
        terminal_error: str | None = None,
        delivery_plan: DeliveryPlan | None = None,
    ) -> list[ChatMessageRecord] | None: ...

    async def cancel_user_turn_delivery_if_active(
        self,
        *,
        turn_id: str,
        expected_session_id: str | None = None,
        expected_user_id: str | None = None,
        run_id: str | None,
        run_revision: int,
        reason: str,
        updated_at_ms: int,
    ) -> bool: ...

    async def finalize_user_turn_delivery_failure(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        user_message: str,
        failure_stage: str,
        error_type: str,
        updated_at_ms: int,
    ) -> ChatDeliveryFailureFinalization: ...


class ChatModelContextRepository(Protocol):
    async def load_model_context(
        self, *, session_id: str, run_id: str | None = None, revision: int | None = None
    ) -> ModelContextSnapshot: ...

    async def append_model_context(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int | None = None,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
    ) -> ModelContextSnapshot: ...

    async def replace_model_context_surface(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
    ) -> ModelContextSnapshot: ...

    async def sync_model_context_surface(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        turn_id: str | None,
        run_id: str,
        step_index: int | None = None,
    ) -> ModelContextSnapshot: ...

    async def prepare_model_context_call(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        system_prompt: str,
        tools: list[dict[str, Any]],
        boundary_kind: str,
        turn_id: str | None,
        run_id: str,
        step_index: int | None = None,
        request_options: Mapping[str, Any] | None = None,
    ) -> tuple[ModelContextSnapshot, ModelContextBoundary]: ...

    async def record_model_context_boundary(
        self,
        *,
        session_id: str,
        surface_revision: int,
        system_prompt: str,
        tools: list[dict[str, Any]],
        boundary_kind: str,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
        request_options: Mapping[str, Any] | None = None,
    ) -> ModelContextBoundary: ...

    async def load_model_context_call(self, *, boundary_id: str) -> ModelContextCallSnapshot: ...

    async def reset_model_context(self, *, session_id: str) -> None: ...


class ChatOutboundRepository(Protocol):
    async def claim_outbound_delivery(
        self, *, now_ms: int, message_id: str | None = None, lease_ms: int = 60000
    ) -> OutboundDelivery | None: ...

    async def begin_outbound_attempt(
        self, item: OutboundDelivery, *, retry_safe: bool, now_ms: int
    ) -> bool: ...

    async def settle_outbound_delivery(
        self,
        item: OutboundDelivery,
        *,
        state: DeliveryState,
        now_ms: int,
        receipt: DeliveryReceipt | None = None,
        error: str | None = None,
        retry_at_ms: int = 0,
    ) -> bool: ...

    async def list_outbound_deliveries(self, *, message_id: str) -> list[OutboundDelivery]: ...

    async def cancel_run_outbound_deliveries(
        self, *, session_id: str, run_id: str, now_ms: int
    ) -> None: ...

    async def list_run_outbound_deliveries(
        self, *, session_id: str, run_id: str
    ) -> list[OutboundDelivery]: ...

    async def list_recent_outbound_status(self, *, limit: int = 50) -> list[DeliveryStatus]: ...


class ChatMemoryHandoffRepository(Protocol):
    async def claim_assistant_memory_projections(
        self, *, limit: int = 10, lease_seconds: float = 60.0, now_ms: int | None = None
    ) -> list[ChatAssistantMemoryOutboxRecord]: ...

    async def complete_assistant_memory_projection(
        self, *, canonical_message_id: str, lease_token: str
    ) -> bool: ...

    async def retry_assistant_memory_projection(
        self,
        *,
        canonical_message_id: str,
        lease_token: str,
        retry_delay_ms: int,
        error: str,
        now_ms: int | None = None,
    ) -> bool: ...

    async def cancel_assistant_memory_projection(self, *, canonical_message_id: str) -> bool: ...

    async def cancel_assistant_memory_projections(
        self,
        *,
        canonical_message_ids: list[str] | tuple[str, ...] = (),
        session_id: str | None = None,
    ) -> int: ...

    async def count_assistant_memory_projections(self) -> int: ...

    async def get_assistant_memory_projection(
        self, canonical_message_id: str
    ) -> ChatAssistantMemoryProjection | None: ...

    async def list_ready_post_turn_outcomes(self) -> list[dict[str, Any]]: ...

    async def claim_post_turn_batch(
        self, outcome_ids: tuple[str, ...], *, lease_seconds: float = 300
    ) -> PostTurnBatchLease | None: ...

    async def ensure_post_turn_lease(self, lease: PostTurnBatchLease) -> None: ...

    async def save_post_turn_analysis(
        self, lease: PostTurnBatchLease, analysis: dict[str, Any]
    ) -> None: ...

    async def settle_post_turn_effect(self, lease: PostTurnBatchLease, effect: str) -> None: ...

    async def replace_post_turn_attention(
        self, lease: PostTurnBatchLease, analysis: dict[str, Any]
    ) -> None: ...

    async def finish_post_turn_batch(
        self, lease: PostTurnBatchLease, *, error: str | None = None
    ) -> bool: ...

    async def cancel_post_turn_outcomes(
        self, *, session_id: str, turn_ids: tuple[str, ...] = (), cutoff_at: float | None = None
    ) -> int: ...

    async def post_turn_status(self) -> dict[str, Any]: ...

    async def retry_failed_post_turn_batches(self, *, limit: int = 100) -> int: ...


class ChatBudgetRepository(Protocol):
    async def ensure_task_execution_budget(
        self, *, root_turn_id: str, max_llm_calls: int, max_worker_launches: int
    ) -> tuple[int, int, int, int]: ...

    async def reserve_task_execution_budget(
        self,
        *,
        root_turn_id: str,
        resource: str,
        count: int,
        max_llm_calls: int,
        max_worker_launches: int,
    ) -> tuple[bool, int, int, int, int]: ...

    async def release_task_execution_llm_calls(
        self, *, root_turn_id: str, count: int
    ) -> tuple[int, int, int, int] | None: ...


class ChatRepository(
    ChatConsumedEventsRepository,
    ChatArtifactRepository,
    ChatTranscriptRepository,
    ChatAcceptanceRepository,
    ChatOutcomeRepository,
    ChatModelContextRepository,
    ChatOutboundRepository,
    ChatMemoryHandoffRepository,
    ChatBudgetRepository,
    Protocol,
):
    """One aggregate owner for accepted messages and their durable outbox writes."""

    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def is_empty(self) -> bool: ...

    def set_assistant_memory_outbox_waker(self, waker: Callable[[], None] | None) -> None: ...
