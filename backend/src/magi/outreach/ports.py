"""Domain-owned proactive delivery persistence contracts."""

from dataclasses import dataclass

from magi_plugin_sdk.storage_ports.outreach import (
    OutreachOutboxRepository,
    OutreachDeliveryLogRepository,
)

@dataclass(frozen=True)
class OutreachRepositories:
    outbox: OutreachOutboxRepository
    delivery_log: OutreachDeliveryLogRepository
