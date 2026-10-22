"""Logical transfer contract for the channel database's complete lifecycle scope."""

from __future__ import annotations
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SnapshotRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionBindingRecord(SnapshotRecord):
    channel_type: str
    external_chat_id: str
    external_thread_id: str
    magi_session_id: str
    magi_user_id: str
    is_group: bool
    created_at_ms: int
    last_active_at_ms: int
    metadata_json: str


class NotificationCursorRecord(SnapshotRecord):
    channel_type: str
    external_chat_id: str
    last_notification_id: int
    updated_at_ms: int


class RelayCursorRecord(SnapshotRecord):
    state_key: str
    value_integer: int
    updated_at_ms: int


class BindingSettingsRecord(SnapshotRecord):
    channel_type: str
    external_user_id: str
    auto_approve: bool
    updated_at_ms: int


class DeliveryReceiptRecord(SnapshotRecord):
    receipt_id: int = Field(gt=0)
    session_id: str
    run_id: str
    revision: int
    channel_id: str
    external_message_id: str | None
    magi_session_id: str
    delivered_at_ms: int
    created_at_ms: int


class OutreachIntentRecord(SnapshotRecord):
    id: int = Field(gt=0)
    correlation_id: str
    channel_scope: str
    intent_fingerprint: str
    intent_json: str
    release_at_ms: int
    status: Literal["pending", "attempting", "delivered", "dropped", "uncertain"]
    created_at_ms: int


class OutreachReceiptRecord(SnapshotRecord):
    correlation_id: str
    user_id: str
    channel_type: str
    delivered_at_ms: int


class ChannelStorageSnapshot(BaseModel):
    """Contains business identities and states, never SQL, paths or adapter keys."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    bindings: list[SessionBindingRecord] = Field(default_factory=list)
    notification_cursors: list[NotificationCursorRecord] = Field(default_factory=list)
    relay_cursors: list[RelayCursorRecord] = Field(default_factory=list)
    binding_settings: list[BindingSettingsRecord] = Field(default_factory=list)
    delivery_receipts: list[DeliveryReceiptRecord] = Field(default_factory=list)
    outreach_intents: list[OutreachIntentRecord] = Field(default_factory=list)
    outreach_receipts: list[OutreachReceiptRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_identities(self) -> ChannelStorageSnapshot:
        keys = (
            (self.bindings, lambda r: (r.channel_type, r.external_chat_id, r.external_thread_id)),
            (self.notification_cursors, lambda r: (r.channel_type, r.external_chat_id)),
            (self.relay_cursors, lambda r: r.state_key),
            (self.binding_settings, lambda r: (r.channel_type, r.external_user_id)),
            (self.delivery_receipts, lambda r: r.receipt_id),
            (self.outreach_intents, lambda r: r.id),
            (self.outreach_intents, lambda r: (r.correlation_id, r.channel_scope)),
            (self.outreach_receipts, lambda r: (r.correlation_id, r.channel_type)),
        )
        for records, key in keys:
            identities = [key(record) for record in records]
            if len(set(identities)) != len(identities):
                raise ValueError("Channel snapshot contains duplicate identities")
        return self

    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in type(self).model_fields if name != "version")


class ChannelStateTransfer(Protocol):
    async def export_state(self) -> ChannelStorageSnapshot: ...
    async def import_state(
        self, snapshot: ChannelStorageSnapshot, *, replace: bool = False
    ) -> None: ...
