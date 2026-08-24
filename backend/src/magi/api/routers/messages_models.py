"""Request and response models for message routes."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...events.recall_feedback import RecallFeedbackKind
from ...events.first_context import normalize_first_context
from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from magi.core.chat_assets.paths import SAFE_CHAT_ASSET_COMPONENT_PATTERN


class RecallFeedbackRequestModel(BaseModel):
    """Structured request to re-evaluate one memory-grounded answer."""

    kind: RecallFeedbackKind
    target_message_id: str = Field(..., min_length=1)
    finding_ref: Optional[str] = None

    @model_validator(mode="after")
    def validate_finding_ref(self) -> "RecallFeedbackRequestModel":
        self.target_message_id = self.target_message_id.strip()
        if not self.target_message_id:
            raise ValueError("target_message_id must not be blank")
        self.finding_ref = str(self.finding_ref or "").strip() or None
        if self.kind == RecallFeedbackKind.ITEM_IRRELEVANT and not self.finding_ref:
            raise ValueError("finding_ref is required for item_irrelevant feedback")
        if self.kind == RecallFeedbackKind.ANSWER_EVIDENCE_MISMATCH:
            self.finding_ref = None
        return self


class FirstContextStoryRequestModel(BaseModel):
    """Reference to the question that the onboarding answer responds to."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(..., min_length=1, max_length=128)
    question_text: str = Field(..., min_length=1, max_length=500)

    @field_validator("question_id", "question_text")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class SkillInvocationRequestModel(BaseModel):
    """Typed inline skill invocation supplied by the composer."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    arguments: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = str(value or "").strip().lstrip("/")
        if not normalized:
            raise ValueError("skill name must not be blank")
        return normalized

    @field_validator("arguments")
    @classmethod
    def normalize_arguments(cls, value: list[str]) -> list[str]:
        return [str(item)[:4096] for item in value]


class UserMessageRequest(BaseModel):
    """User message request."""

    message: str = Field(default="", description="User message content")
    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    attachments: List[Dict[str, Any]] = Field(
        default_factory=list, description="Structured attachment metadata"
    )
    reply_to_message_id: Optional[str] = Field(None, description="Optional replied-to message id")
    workspace_path: Optional[str] = Field(
        None, description="Effective workspace path for this turn"
    )
    client_turn_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=128,
        pattern=SAFE_CHAT_ASSET_COMPONENT_PATTERN,
        description="Optional client-generated turn id",
    )
    recall_feedback: Optional[RecallFeedbackRequestModel] = Field(
        None,
        description="Optional one-turn recall correction request",
    )
    interaction_kind: Optional[Literal["first_context_story"]] = Field(
        None,
        description="Controlled interaction type for a first-context answer",
    )
    first_context: Optional[FirstContextStoryRequestModel] = Field(
        None,
        description="Question context for a first-context answer",
    )
    reasoning_preference: Optional[Literal["auto", "fast", "deep"]] = Field(
        None,
        description="Optional structured reasoning preference for this turn",
    )
    skill_invocation: Optional[SkillInvocationRequestModel] = Field(
        None,
        description="Optional typed inline skill invocation",
    )
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="metadata")

    @model_validator(mode="after")
    def validate_first_context_interaction(self) -> "UserMessageRequest":
        if self.interaction_kind == "first_context_story" and self.first_context is None:
            raise ValueError("first_context is required for first_context_story")
        if self.first_context is not None and self.interaction_kind != "first_context_story":
            raise ValueError("first_context requires interaction_kind=first_context_story")
        if (
            self.first_context is not None
            and normalize_first_context(self.first_context.model_dump(mode="json")) is None
        ):
            raise ValueError("first_context must reference a supported onboarding question")
        if self.first_context is not None and self.recall_feedback is not None:
            raise ValueError("first_context cannot be combined with recall_feedback")
        if self.skill_invocation is not None and (
            self.first_context is not None or self.recall_feedback is not None
        ):
            raise ValueError("skill_invocation cannot be combined with a controlled interaction")
        return self


class MessageResponse(BaseModel):
    """Message response."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ClearHistoryResponse(BaseModel):
    """Confirmed immutable transcript snapshot removed by a history clear."""

    success: bool
    message: str
    user_id: str
    session_id: str
    cleared_message_ids: List[str] = Field(default_factory=list)
    cleared_turn_ids: List[str] = Field(default_factory=list)
    cleanup_pending: bool = False


class DeleteMessageResponse(BaseModel):
    """Confirmed message removal and its remaining cleanup state."""

    success: bool
    user_id: str
    session_id: str
    deleted_message_id: str
    cleanup_pending: bool = False


class DeleteSessionResponse(BaseModel):
    """Confirmed session removal and its remaining cleanup state."""

    success: bool
    user_id: str
    deleted_session_id: str
    cleanup_pending: bool = False


class RenameSessionRequest(BaseModel):
    """Session rename request."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    title: str = Field(..., description="New session title")


class UpdateSessionWorkspaceRequest(BaseModel):
    """Session workspace update request."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    workspace_path: Optional[str] = Field(
        default=None, description="Workspace path for the session"
    )


class CancelSessionRunRequest(BaseModel):
    """Explicit cancel request for the active session run."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    requested_by: str = Field(default="user", description="Cancellation initiator")
    reason: str = Field(default="user_cancel", description="Cancellation reason")
    turn_id: Optional[str] = Field(
        default=None, description="Optional turn id that triggered cancellation"
    )


class DetachSessionRunRequest(BaseModel):
    """Explicit detach request for the active session run."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    requested_by: str = Field(default="user", description="Detach initiator")
    reason: str = Field(default="user_detach", description="Detach reason")
    turn_id: Optional[str] = Field(
        default=None, description="Optional turn id that triggered detaching"
    )


class MessageLabelRequest(BaseModel):
    """Single-label mutation payload for one chat message."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    kind: str = Field(..., description="Label kind")
    text: str = Field(..., description="Label text")
    applied_by: str = Field(..., description="Who applied the label")
    source: str = Field(..., description="How the label was created")
    created_at_ms: Optional[int] = Field(
        default=None, description="Client timestamp in milliseconds"
    )


__all__ = [
    "CancelSessionRunRequest",
    "ClearHistoryResponse",
    "DetachSessionRunRequest",
    "DeleteMessageResponse",
    "DeleteSessionResponse",
    "FirstContextStoryRequestModel",
    "MessageLabelRequest",
    "MessageResponse",
    "RenameSessionRequest",
    "RecallFeedbackRequestModel",
    "SkillInvocationRequestModel",
    "UpdateSessionWorkspaceRequest",
    "UserMessageRequest",
]
