"""Failures raised before a streamed generation is confirmed complete."""


class IncompleteStreamError(ConnectionError):
    """The provider stream ended without its required completion event."""
