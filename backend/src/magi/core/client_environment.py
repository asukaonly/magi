"""Advisory client facts captured for one turn, never an authorization identity."""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

CLIENT_ENVIRONMENT_MAX_AGE_SECONDS = 30 * 60


def validate_timezone_id(value: str | None) -> str | None:
    """Validate timezone identity before it enters runtime context."""
    if value is not None:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


class ClientEnvironment(BaseModel):
    """Minimal client-reported context; raw user agents and device IDs stay out."""

    model_config = ConfigDict(extra="forbid", strict=True)

    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    os: Literal["macos", "windows", "linux", "ios", "android", "unknown"] = "unknown"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return validate_timezone_id(value)
