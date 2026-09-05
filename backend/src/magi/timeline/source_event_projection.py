"""Project source domain events into timeline read-model payloads."""
from __future__ import annotations

from typing import Any

from magi.events.domain_payloads import SourceEventEmitted
from magi.events.source_activity_snapshot import build_source_activity_snapshot


def build_timeline_event_dict(
    payload: SourceEventEmitted,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Build the TimelineEvent dict shape from source payload context."""
    return build_source_activity_snapshot(payload, event_id=event_id)
