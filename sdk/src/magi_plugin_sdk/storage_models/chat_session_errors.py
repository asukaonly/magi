"""Shared chat persistence contracts and value codecs."""



class ChatSessionCreationConflict(ValueError):
    """A retained creation identity belongs to a terminal or unavailable session."""


class ChatSessionNotFound(ValueError):
    """The caller does not own an active session with this identity."""
