"""Shared chat persistence contracts and value codecs."""

from typing import Literal
from pydantic import BaseModel, ConfigDict


class ClientModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnSnapshot(ClientModel):
    session_id: str
    turn_id: str
    acceptance: Literal["accepted", "absent", "retired"]
    state: Literal["queued", "running", "cancelling", "detaching", "completed", "failed", "cancelled", "blocked", "interrupted", "merged", "discarded", "superseded"] | None
    terminal: bool
    response_complete: bool
    presentation_ends_at_ms: int | None
    can_resubmit: bool
    revision: str
