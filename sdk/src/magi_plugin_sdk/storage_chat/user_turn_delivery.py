"""Composition entry for durable user-turn acceptance and delivery storage."""

from magi_plugin_sdk.storage_chat.user_turn_acceptance import ChatUserTurnAcceptancePersistenceMixin
from magi_plugin_sdk.storage_chat.user_turn_delivery_ledger import ChatUserTurnDeliveryLedgerPersistenceMixin
from magi_plugin_sdk.storage_chat.user_turn_delivery_recovery import ChatUserTurnDeliveryRecoveryPersistenceMixin


class ChatUserTurnDeliveryPersistenceMixin(
    ChatUserTurnAcceptancePersistenceMixin,
    ChatUserTurnDeliveryLedgerPersistenceMixin,
    ChatUserTurnDeliveryRecoveryPersistenceMixin,
):
    """Compose accepted-turn, delivery-ledger, and recovery transactions."""


__all__ = [
    "ChatUserTurnDeliveryPersistenceMixin",
]
