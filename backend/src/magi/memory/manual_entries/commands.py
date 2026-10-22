"""Validated commands and creation receipts for manual-entry workflows."""

from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ManualEntryCreateBody(BaseModel):
    entry_id: str = Field(
        min_length=4,
        max_length=131,
        pattern=r"^me-[A-Za-z0-9][A-Za-z0-9-]*$",
    )
    body: str
    # Optional ProseMirror JSON document for the rich-text editor
    # (Phase B-2). The plain `body` field is still required — it's the
    # canonical text projection consumed by L1, search, and the diary
    # LLM. Clients send both, derived from the same editor state.
    body_doc: Optional[dict] = None
    event_at: Optional[float] = None
    mood: Optional[str] = None
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    attachment_refs: list[str] = Field(default_factory=list)


class ManualEntryUpdateBody(BaseModel):
    expected_revision: str | None = None
    body: Optional[str] = None
    body_doc: Optional[dict] = None
    # Explicit flag for clearing body_doc — there's no natural "empty"
    # JSON dict so we can't reuse the empty-string-clears convention.
    clear_body_doc: bool = False
    event_at: Optional[float] = None
    mood: Optional[str] = None
    attachment_refs: Optional[list[str]] = None
    user_pinned: Optional[bool] = None
    # Text fields use the empty-string-clears convention: omit (=None)
    # means "don't touch"; "" means "clear to NULL"; other strings set.
    # This lets the UI's ✕ buttons persist without needing a separate
    # delete-this-field endpoint per attribute.
    location_label: Optional[str] = None


class ManualEntryCreateResponse(BaseModel):
    """Public entry plus the readiness of its derived memory."""

    entry_id: str
    revision: str
    created_at: float
    event_at: float
    kind: str
    body: str
    body_doc: Optional[dict[str, Any]] = None
    mood: Optional[str] = None
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    attachments: list[str]
    exclude_from_llm: bool
    user_pinned: bool
    deleted_at: Optional[float] = None
    l1_event_id: Optional[str] = None
    weather: Optional[dict[str, Any]] = None
    memory_status: Literal["ready", "pending"]
