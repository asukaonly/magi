"""Product-facing contracts independent of a desktop or runtime implementation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


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


class TurnConfirmationRequest(ClientModel):
    kind: Literal["turn"]
    session_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)


class AnswerConfirmationRequest(ClientModel):
    kind: Literal["ask_response"]
    session_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=100_000)


class SendConfirmationRequest(RootModel[Annotated[
    TurnConfirmationRequest | AnswerConfirmationRequest, Field(discriminator="kind"),
]]):
    pass


class SendConfirmation(ClientModel):
    session_id: str
    identity: str
    status: Literal["confirmed", "absent", "concluded"]
    safe_to_retry: bool
