"""Portable persistence values and deterministic row normalization."""

from __future__ import annotations
from collections.abc import Mapping
from typing import Any

ACTIVITY_SNAPSHOT_METADATA_KEY = "activity_snapshot"


def activity_snapshot_from_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return the neutral activity snapshot embedded in memory metadata."""
    if not isinstance(metadata, Mapping):
        return {}
    snapshot = metadata.get(ACTIVITY_SNAPSHOT_METADATA_KEY)
    return snapshot if isinstance(snapshot, Mapping) else {}
