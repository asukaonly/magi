"""Custom exceptions for Calendar plugin."""


class CalendarError(Exception):
    """Base exception for Calendar-related errors."""
    pass


class PlatformNotSupportedError(CalendarError):
    """Raised when EventKit is accessed on unsupported platforms."""

    def __init__(self, message: str = "Calendar is only available on macOS and iOS"):
        super().__init__(message)


class EventKitNotAvailableError(CalendarError):
    """Raised when EventKit framework is not available on the device."""

    def __init__(self, message: str = "EventKit framework is not available"):
        super().__init__(message)


class AuthorizationDeniedError(CalendarError):
    """Raised when user denies Calendar authorization."""

    def __init__(self, resource: str):
        self.resource = resource
        message = f"Authorization denied for: {resource}"
        super().__init__(message)


class EventKitQueryError(CalendarError):
    """Raised when an EventKit query fails."""

    def __init__(self, message: str, query_type: str | None = None):
        self.query_type = query_type
        if query_type:
            message = f"{message} (Query type: {query_type})"
        super().__init__(message)