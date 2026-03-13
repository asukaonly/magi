"""EventKit data reader using pyobjc bridge."""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Optional, List

from .exceptions import PlatformNotSupportedError, EventKitNotAvailableError
from .types import CalendarEvent, Participant


class EventKitReader:
    """EventKit data reader using pyobjc bridge."""

    def __init__(self) -> None:
        self._event_store: Any = None
        self._is_available: Optional[bool] = None
        self._ek_module: dict[str, Any] | None = None
        self._foundation_module: dict[str, Any] | None = None

    def _ensure_platform(self) -> None:
        """Raise error if not running on macOS/iOS."""
        if sys.platform != "darwin":
            raise PlatformNotSupportedError()

    def _import_frameworks(self) -> None:
        """Import EventKit frameworks (macOS only) with lazy loading."""
        # Will be implemented when adding full EventKit support
        pass

    @property
    def event_store(self) -> Any:
        """Get or create EKEventStore instance."""
        if self._event_store is None:
            self._ensure_platform()
            self._import_frameworks()
            # Will be implemented when adding full EventKit support
        return self._event_store

    def is_available(self) -> bool:
        """Check if EventKit is available on this device."""
        if self._is_available is not None:
            return self._is_available

        # Not available on non-darwin platforms
        if sys.platform != "darwin":
            self._is_available = False
            return False

        try:
            self._import_frameworks()
            # Will check actual EventKit availability when implemented
            self._is_available = False  # Stub: return False until implemented
            return self._is_available
        except Exception:
            self._is_available = False
            return False

    def get_authorization_status(self) -> str:
        """
        Get authorization status for calendar access.

        Returns:
            One of: "not_determined", "denied", "authorized", "unavailable"
        """
        if not self.is_available():
            return "unavailable"

        # Stub: return unavailable until EventKit implementation
        return "unavailable"

    def request_authorization(self) -> bool:
        """
        Request calendar access authorization.

        Returns:
            True if authorization was granted, False otherwise
        """
        if not self.is_available():
            return False

        # Stub: return False until EventKit implementation
        return False

    def read_events(
        self,
        start_date: datetime,
        end_date: datetime,
        calendars: Optional[List[str]] = None
    ) -> List[CalendarEvent]:
        """
        Read calendar events within a date range.

        Args:
            start_date: Start date for the query
            end_date: End date for the query
            calendars: Optional list of calendar names to filter

        Returns:
            List of CalendarEvent objects (stub - returns empty list)
        """
        if not self.is_available():
            return []

        # Stub implementation - will be completed in a future task
        return []