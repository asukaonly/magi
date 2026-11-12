"""Domain-owned logical channel transfer port."""

from typing import Protocol
from magi_plugin_sdk.storage_models.channels import (
    SnapshotRecord,
    SessionBindingRecord,
    NotificationCursorRecord,
    RelayCursorRecord,
    BindingSettingsRecord,
    DeliveryReceiptRecord,
    OutreachIntentRecord,
    OutreachReceiptRecord,
    ChannelStorageSnapshot
)


class ChannelStateTransfer(Protocol):
    async def export_state(self) -> ChannelStorageSnapshot: ...
    async def import_state(
        self, snapshot: ChannelStorageSnapshot, *, replace: bool = False
    ) -> None: ...
