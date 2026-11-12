"""Shared chat persistence contracts and value codecs."""



class ChatTurnConflictError(ValueError):
    """An accepted turn identity conflicts with the requested transition."""


class ChatMessageConflictError(ValueError):
    """A stable message identity was reused with different content."""
