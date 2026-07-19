"""Layer-neutral delivery outcome contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from magi_plugin_sdk.channels import ChannelTarget
    from magi_plugin_sdk.delivery import DeliveryReceipt


@dataclass(frozen=True, slots=True)
class DeliveryFailure:
    """One target that did not return a delivery receipt."""

    target: "ChannelTarget"
    error: Exception
    delivery_attempted: bool


@dataclass(frozen=True, slots=True)
class DeliveryFanoutResult:
    """Complete outcome of one fanout operation."""

    receipts: tuple["DeliveryReceipt", ...] = ()
    failures: tuple[DeliveryFailure, ...] = ()


__all__ = [
    "DeliveryFailure",
    "DeliveryFanoutResult",
]
