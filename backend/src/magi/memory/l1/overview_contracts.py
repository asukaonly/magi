"""Bounded, storage-neutral event overview reads."""
from __future__ import annotations

from dataclasses import dataclass, field
import math


from magi_plugin_sdk.storage_models.event_overview import (
    EventOverviewQuery,
    EventOverviewCount,
    EventOverviewPreview,
    EventOverview,
)
