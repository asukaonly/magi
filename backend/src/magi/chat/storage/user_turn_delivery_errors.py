"""Errors raised by durable user-turn acceptance and delivery."""


class ChatTurnConflictError(ValueError):
    """Raised when one client turn id is reused for different user input."""


__all__ = ["ChatTurnConflictError"]
