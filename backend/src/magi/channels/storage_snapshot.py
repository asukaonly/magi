"""Domain-owned logical channel transfer port."""

from typing import Protocol
from magi_plugin_sdk.storage_models.channels import (
    SnapshotRecord as SnapshotRecord,
    SessionBindingRecord as SessionBindingRecord,
    NotificationCursorRecord as NotificationCursorRecord,
    RelayCursorRecord as RelayCursorRecord,
    BindingSettingsRecord as BindingSettingsRecord,
    DeliveryReceiptRecord as DeliveryReceiptRecord,
    OutreachIntentRecord as OutreachIntentRecord,
    OutreachReceiptRecord as OutreachReceiptRecord,
    ChannelStorageSnapshot
)

class ChannelStateTransfer(Protocol):
    async def export_state(self) -> ChannelStorageSnapshot: ...
    async def import_state(
        self, snapshot: ChannelStorageSnapshot, *, replace: bool = False
    ) -> None: ...
