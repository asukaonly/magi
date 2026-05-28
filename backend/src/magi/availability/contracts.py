"""Public contracts for the availability subsystem."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AvailabilityReason(StrEnum):
    """Why a plugin is or isn't available on the current device."""

    AVAILABLE = "available"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    MISSING_FILE = "missing_file"
    MISSING_EXECUTABLE = "missing_executable"
    APP_NOT_INSTALLED = "app_not_installed"
    NO_DESCRIPTOR = "no_descriptor"  # plugin opted out of being suggested
    CHECK_ERROR = "check_error"  # availability probe raised; treat as unavailable


class AvailabilityResult(BaseModel):
    plugin_id: str
    available: bool
    reason: AvailabilityReason
    detail: str | None = Field(
        default=None,
        description="Human-readable detail (e.g. the path that was missing).",
    )
    checked_at: datetime
