"""Delivery attempts and persistence contracts, independent of transport/storage."""
from __future__ import annotations

from magi_plugin_sdk.delivery import DeliveryContent as DeliveryContent, DeliveryReceipt as DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef as EndpointRef
from magi_plugin_sdk.audio import AudioPlaybackState as AudioPlaybackState

from magi_plugin_sdk.storage_models.delivery_outbox import (
    DeliveryState as DeliveryState,
    OutboundDelivery as OutboundDelivery,
    DeliveryStatus as DeliveryStatus,
    DeliveryAttemptQueue as DeliveryAttemptQueue,
    DeliveryOutbox as DeliveryOutbox,
)
