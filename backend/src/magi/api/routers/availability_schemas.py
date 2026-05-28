"""Request/response models for the availability HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from magi.availability.contracts import AvailabilityReason


class AvailabilityEntry(BaseModel):
    plugin_id: str
    available: bool
    reason: AvailabilityReason
    detail: str | None
    checked_at: datetime


class AvailabilityListResponse(BaseModel):
    entries: list[AvailabilityEntry]


class AvailabilityRefreshResponse(BaseModel):
    invalidated_plugin_ids: list[str]
