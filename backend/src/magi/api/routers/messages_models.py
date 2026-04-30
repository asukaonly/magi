"""Request and response models for message routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ...runtime_defaults import DEFAULT_USER_ID


class UserMessageRequest(BaseModel):
    """User message request."""

    message: str = Field(default="", description="User message content")
    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Structured attachment metadata")
    reply_to_message_id: Optional[str] = Field(None, description="Optional replied-to message id")
    workspace_path: Optional[str] = Field(None, description="Effective workspace path for this turn")
    client_turn_id: Optional[str] = Field(None, description="Optional client-generated turn id")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="metadata")


class MessageResponse(BaseModel):
    """Message response."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class RenameSessionRequest(BaseModel):
    """Session rename request."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    title: str = Field(..., description="New session title")


class UpdateSessionWorkspaceRequest(BaseModel):
    """Session workspace update request."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    workspace_path: Optional[str] = Field(default=None, description="Workspace path for the session")


class CancelSessionRunRequest(BaseModel):
    """Explicit cancel request for the active session run."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    requested_by: str = Field(default="user", description="Cancellation initiator")
    reason: str = Field(default="user_cancel", description="Cancellation reason")
    turn_id: Optional[str] = Field(default=None, description="Optional turn id that triggered cancellation")


class DetachSessionRunRequest(BaseModel):
    """Explicit detach request for the active session run."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    requested_by: str = Field(default="user", description="Detach initiator")
    reason: str = Field(default="user_detach", description="Detach reason")
    turn_id: Optional[str] = Field(default=None, description="Optional turn id that triggered detaching")


class MessageLabelRequest(BaseModel):
    """Single-label mutation payload for one chat message."""

    user_id: str = Field(default=DEFAULT_USER_ID, description="User ID")
    kind: str = Field(..., description="Label kind")
    text: str = Field(..., description="Label text")
    applied_by: str = Field(..., description="Who applied the label")
    source: str = Field(..., description="How the label was created")
    created_at_ms: Optional[int] = Field(default=None, description="Client timestamp in milliseconds")


__all__ = [
    "CancelSessionRunRequest",
    "DetachSessionRunRequest",
    "MessageLabelRequest",
    "MessageResponse",
    "RenameSessionRequest",
    "UpdateSessionWorkspaceRequest",
    "UserMessageRequest",
]