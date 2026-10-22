"""Timeline cover domain model and persistence contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

TimelineCoverPreferenceMode = Literal["asset", "hidden"]
TimelineCoverAssetSource = Literal["current_period", "custom_upload"]
TIMELINE_COVER_ASSET_SOURCES = frozenset({"current_period", "custom_upload"})


@dataclass(frozen=True, slots=True)
class TimelineCoverPreference:
    scope_key: str
    scale: str
    period_start: float
    period_end: float
    mode: TimelineCoverPreferenceMode
    asset_ref: str | None
    source: Literal["current_period", "custom_upload", "hidden"]
    updated_at: float


class TimelineCoverRepository(Protocol):
    async def get_preference(
        self, *, scale: str, period_start: float, period_end: float
    ) -> TimelineCoverPreference | None: ...
    async def set_preference(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        mode: TimelineCoverPreferenceMode,
        asset_ref: str | None = None,
        source: TimelineCoverAssetSource = "current_period",
    ) -> TimelineCoverPreference: ...
    async def clear_preference(
        self, *, scale: str, period_start: float, period_end: float
    ) -> bool: ...
    async def references_asset(self, asset_ref: str) -> bool: ...
