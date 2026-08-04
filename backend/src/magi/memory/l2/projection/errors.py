"""Projection attempt ownership errors."""


class ProjectionAttemptFencedError(RuntimeError):
    """Raised when a durable projection attempt no longer owns its lease."""


__all__ = ["ProjectionAttemptFencedError"]
