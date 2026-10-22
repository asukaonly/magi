"""Storage-independent outcomes shared by chat applications and their callers."""


class ChatSessionCreationConflict(ValueError):
    """A retained creation identity belongs to a terminal or unavailable session."""


class ChatSessionNotFound(ValueError):
    """The caller does not own an active session with this identity."""
