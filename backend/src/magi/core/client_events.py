"""Public event schemas; runtime notifications are projected before transport."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, RootModel

from .chat_read_models import ChatDisplayMessage, ChatSessionSummary
from .client_models import ClientModel


class EventIdentity(ClientModel):
    contract_version: Literal[1]
    server_id: UUID
    epoch: UUID
    sequence: int = Field(ge=0, le=9_007_199_254_740_991)
    event_id: str = Field(min_length=1, max_length=100)


class ProductMessageUpsert(ClientModel):
    user_id: str
    session_id: str
    message_id: str
    message: ChatDisplayMessage
    session_summary: ChatSessionSummary | None = None


class ProductMessageHidden(ClientModel):
    user_id: str
    session_id: str
    message_id: str
    session_summary: ChatSessionSummary | None = None


class ProductTurnIdentity(ClientModel):
    user_id: str
    session_id: str
    turn_id: str


class ProductTurnControl(ProductTurnIdentity):
    run_id: str | None = None
    state: str
    can_cancel: bool
    label: str | None = None
    timestamp: float


class ProductTurnPresentation(ProductTurnIdentity):
    ux_plan: dict[str, JsonValue]
    message_id: str | None = None
    message_kind: str | None = None
    timestamp: float


class ProductTextPreview(ClientModel):
    kind: Literal["text_delta", "text_flush", "text_reset", "status_update", "error", "done"]
    text: str | None = None
    error_kind: str | None = None
    error_message: str | None = None
    step_label: str | None = None


class ProductResponsePreview(ProductTurnIdentity):
    event: ProductTextPreview
    is_final: bool
    seq: int
    timestamp: float
    persona_id: str | None = None


class ProductResponseDisplay(ClientModel):
    user_id: str
    session_id: str
    content: str
    is_final: bool
    timestamp: float
    turn_id: str | None = None
    message_id: str | None = None
    message_kind: str | None = None
    persona_id: str | None = None
    message_payload: dict[str, JsonValue] | None = None
    attachments: list[dict[str, JsonValue]] = Field(default_factory=list)
    reply_to_message_id: str | None = None
    ux_plan: dict[str, JsonValue] | None = None
    trace_available: bool = False


class ProductContextUsage(ProductTurnIdentity):
    used_tokens: int
    window_size: int
    input_capacity: int
    threshold: float
    measurement: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    updated_at_ms: int | None = None
    timestamp: float


class ProductInteractionPointer(ClientModel):
    session_id: str
    user_id: str | None = None
    request_id: str | None = None
    run_id: str | None = None


class ProductResourceChange(ClientModel):
    resource: str


class ProductResyncRequired(ClientModel):
    reason: str


class ProductNotificationCount(ClientModel):
    unread_count: int = Field(ge=0)


class MessageUpsertEvent(EventIdentity):
    event_type: Literal["chat_message_upserted"]
    data: ProductMessageUpsert


class MessageHiddenEvent(EventIdentity):
    event_type: Literal["chat_message_hidden"]
    data: ProductMessageHidden


class TurnControlEvent(EventIdentity):
    event_type: Literal["turn_execution_control"]
    data: ProductTurnControl


class TurnPresentationEvent(EventIdentity):
    event_type: Literal["turn_ux_plan"]
    data: ProductTurnPresentation


class ResponsePreviewEvent(EventIdentity):
    event_type: Literal["agent_response_chunk"]
    data: ProductResponsePreview


class ResponseDisplayEvent(EventIdentity):
    event_type: Literal["agent_response"]
    data: ProductResponseDisplay


class ContextUsageEvent(EventIdentity):
    event_type: Literal["context_usage"]
    data: ProductContextUsage


class InteractionEvent(EventIdentity):
    event_type: Literal["control.ask.requested", "control.ask.answered", "control.permission.requested", "control.permission.resolved", "control.plan.updated", "control.background.suspended", "control.background.resumed"]
    data: ProductInteractionPointer


class ResourceChangeEvent(EventIdentity):
    event_type: Literal["state.changed"]
    data: ProductResourceChange


class ResyncEvent(EventIdentity):
    event_type: Literal["resync_required"]
    data: ProductResyncRequired


class NotificationEvent(EventIdentity):
    event_type: Literal["user_notification_added"]
    data: ProductNotificationCount


class ProductEvent(RootModel[Annotated[
    MessageUpsertEvent | MessageHiddenEvent | TurnControlEvent | TurnPresentationEvent
    | ResponsePreviewEvent | ResponseDisplayEvent | ContextUsageEvent | InteractionEvent
    | ResourceChangeEvent | ResyncEvent | NotificationEvent,
    Field(discriminator="event_type"),
]]):
    pass
