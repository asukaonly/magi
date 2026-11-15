"""Domain-owned persistence contracts for channel bindings."""

from __future__ import annotations

from dataclasses import dataclass

from magi_plugin_sdk.storage_ports.channels import (
    ChannelSessionRepository,
    DeliveryReceiptsRepository,
    ChannelBindingSettingsRepository,
)

@dataclass(frozen=True)
class ChannelRepositories:
    sessions: ChannelSessionRepository
    receipts: DeliveryReceiptsRepository
    binding_settings: ChannelBindingSettingsRepository
