"""Delivery attempts and persistence contracts, independent of transport/storage."""
from __future__ import annotations
from ..core.delivery_policy import LEASE_MS

from dataclasses import dataclass
from typing import Literal, Protocol

from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef
from magi_plugin_sdk.audio import AudioPlaybackState

from magi_plugin_sdk.storage_models.delivery_outbox import (
    DeliveryState,
    OutboundDelivery,
    DeliveryStatus,
    DeliveryAttemptQueue,
    DeliveryOutbox,
)
