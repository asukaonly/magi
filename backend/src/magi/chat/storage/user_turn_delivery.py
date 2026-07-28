"""Composition entry for durable user-turn acceptance and delivery storage."""

from .user_turn_acceptance import ChatUserTurnAcceptancePersistenceMixin
from .user_turn_delivery_errors import ChatTurnConflictError
from .user_turn_delivery_ledger import (
    ChatUserTurnDeliveryLedgerPersistenceMixin,
)
from .user_turn_delivery_recovery import (
    ChatUserTurnDeliveryRecoveryPersistenceMixin,
)


class ChatUserTurnDeliveryPersistenceMixin(
    ChatUserTurnAcceptancePersistenceMixin,
    ChatUserTurnDeliveryLedgerPersistenceMixin,
    ChatUserTurnDeliveryRecoveryPersistenceMixin,
):
    """Compose accepted-turn, delivery-ledger, and recovery transactions."""


__all__ = [
    "ChatTurnConflictError",
    "ChatUserTurnDeliveryPersistenceMixin",
]
