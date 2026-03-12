from __future__ import annotations

import pytest
import sys
from pathlib import Path

_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from calendar_plugin.exceptions import (
    CalendarError,
    PlatformNotSupportedError,
    EventKitNotAvailableError,
    AuthorizationDeniedError,
    EventKitQueryError,
)


def test_calendar_error_base():
    """Test CalendarError base exception."""
    error = CalendarError("Test error")
    assert str(error) == "Test error"


def test_platform_not_supported_error():
    """Test PlatformNotSupportedError has default message."""
    error = PlatformNotSupportedError()
    assert "macOS" in str(error) or "iOS" in str(error)


def test_eventkit_not_available_error():
    """Test EventKitNotAvailableError has default message."""
    error = EventKitNotAvailableError()
    assert "EventKit" in str(error)


def test_authorization_denied_error():
    """Test AuthorizationDeniedError includes context."""
    error = AuthorizationDeniedError("calendar")
    assert error.resource == "calendar"
    assert "calendar" in str(error)


def test_eventkit_query_error():
    """Test EventKitQueryError with optional query type."""
    error1 = EventKitQueryError("Query failed")
    assert str(error1) == "Query failed"

    error2 = EventKitQueryError("Query failed", query_type="events")
    assert "events" in str(error2)