"""Custom exceptions for Apple Health plugin."""


class HealthKitError(Exception):
    """Base exception for HealthKit-related errors."""
    pass


class PlatformNotSupportedError(HealthKitError):
    """Raised when HealthKit is accessed on unsupported platforms."""

    def __init__(self, message: str = "Apple Health is only available on macOS and iOS"):
        super().__init__(message)


class HealthKitNotAvailableError(HealthKitError):
    """Raised when HealthKit framework is not available on the device."""

    def __init__(self, message: str = "HealthKit framework is not available"):
        super().__init__(message)


class AuthorizationDeniedError(HealthKitError):
    """Raised when user denies HealthKit authorization."""

    def __init__(self, data_type: str):
        self.data_type = data_type
        message = f"Authorization denied for data type: {data_type}"
        super().__init__(message)


class HealthKitQueryError(HealthKitError):
    """Raised when a HealthKit query fails."""

    def __init__(self, message: str, query_type: str | None = None):
        self.query_type = query_type
        if query_type:
            message = f"{message} (Query type: {query_type})"
        super().__init__(message)