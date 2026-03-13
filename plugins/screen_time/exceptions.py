"""Custom exceptions for Screen Time plugin."""


class ScreenTimeError(Exception):
    """Base exception for Screen Time-related errors."""
    pass


class PlatformNotSupportedError(ScreenTimeError):
    """Raised when Screen Time is accessed on unsupported platforms."""

    def __init__(self, message: str = "Screen Time is only available on macOS"):
        super().__init__(message)


class DatabaseNotFoundError(ScreenTimeError):
    """Raised when Screen Time database is not found."""

    def __init__(self, message: str = "Screen Time database not found"):
        super().__init__(message)


class DatabaseReadError(ScreenTimeError):
    """Raised when a database query fails."""

    def __init__(self, message: str, query_type: str | None = None):
        self.query_type = query_type
        if query_type:
            message = f"{message} (Query type: {query_type})"
        super().__init__(message)
