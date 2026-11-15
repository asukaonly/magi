"""Product-facing contracts independent of a desktop or runtime implementation."""

from typing import Annotated, Literal

from pydantic import Field, RootModel

from magi_plugin_sdk.storage_models.chat_client import (
    ClientModel,
    TurnSnapshot as TurnSnapshot,
)

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
