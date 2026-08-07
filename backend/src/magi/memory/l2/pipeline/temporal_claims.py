"""Strict host resolution for raw Claim time expressions."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable
from zoneinfo import ZoneInfo

from ....utils.calendar_timezone import canonical_timezone_id
from ..claims.models import ClaimEvidenceInput
from ..temporal_trust import normalized_event_timestamp, trusted_event_timestamp
from .temporal_expressions import (
    CalendarRange,
    TRUSTED_CURRENTNESS_QUALITIES,
    resolve_calendar_expression,
)


@dataclass(frozen=True, slots=True)
class ClaimTemporalResolution:
    """Resolved semantic window and auditable raw expression metadata."""

    fact_valid_from: float | None
    fact_valid_to: float | None
    target_from: float | None
    target_to: float | None
    raw_time_frame: dict[str, object] | None


def resolve_claim_temporal_fields(
    *,
    raw_expression: str,
    future_intent: bool,
    evidence: Iterable[ClaimEvidenceInput],
    now: float | None = None,
) -> ClaimTemporalResolution:
    """Resolve grounded expressions only under an explicit source-time policy."""

    raw = str(raw_expression or "").strip()
    if not raw:
        return ClaimTemporalResolution(None, None, None, None, None)

    supporting = [item for item in evidence if item.link_role == "supporting"]
    timezone_evidence = tuple(
        (item, canonical_timezone_id(item.calendar_timezone_id)) for item in supporting
    )
    if not supporting or any(timezone_id is None for _item, timezone_id in timezone_evidence):
        return _unresolved(raw, future_intent=future_intent, quality="low")
    timezone_ids = {str(timezone_id) for _item, timezone_id in timezone_evidence}
    timezone_id = sorted(timezone_ids)[0]

    absolute_ranges = _resolve_ranges(
        raw,
        timezone_evidence=timezone_evidence,
        anchor_timestamp=None,
        anchor_quality="low",
    )
    if absolute_ranges:
        if len(absolute_ranges) != 1:
            return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
        return _result(
            raw,
            future_intent=future_intent,
            calendar_range=next(iter(absolute_ranges)),
            timezone_id=timezone_id,
            quality="calendar_anchor",
        )

    if any(
        item.event_time is None
        or item.timestamp_quality not in TRUSTED_CURRENTNESS_QUALITIES
        for item in supporting
    ):
        return _unresolved(raw, future_intent=future_intent, quality="low")

    anchor_times = [normalized_event_timestamp(item.event_time) for item in supporting]
    if any(anchor_time is None for anchor_time in anchor_times):
        return _unresolved(raw, future_intent=future_intent, quality="low")

    resolved_now = float(time.time() if now is None else now)
    if any(
        trusted_event_timestamp(anchor_time, now=resolved_now) is None
        for anchor_time in anchor_times
    ):
        return _unresolved(raw, future_intent=future_intent, quality="low")

    anchored_ranges = {
        resolved
        for item, item_timezone_id in timezone_evidence
        if item.event_time is not None
        for resolved in [
            resolve_calendar_expression(
                raw,
                anchor_timestamp=float(item.event_time),
                anchor_quality=item.timestamp_quality,
                local_timezone=ZoneInfo(str(item_timezone_id)),
            )
        ]
        if resolved is not None
    }
    if len(anchored_ranges) != 1:
        quality = "ambiguous" if anchored_ranges else "unresolved_text"
        return _unresolved(raw, future_intent=future_intent, quality=quality)
    return _result(
        raw,
        future_intent=future_intent,
        calendar_range=next(iter(anchored_ranges)),
        timezone_id=timezone_id,
        anchor_event_ids=(item.event_id for item in supporting),
        quality="calendar_anchor",
    )


def _resolve_ranges(
    raw: str,
    *,
    timezone_evidence: tuple[tuple[ClaimEvidenceInput, str | None], ...],
    anchor_timestamp: float | None,
    anchor_quality: str,
) -> set[CalendarRange]:
    return {
        resolved
        for _item, timezone_id in timezone_evidence
        if timezone_id is not None
        for resolved in [
            resolve_calendar_expression(
                raw,
                anchor_timestamp=anchor_timestamp,
                anchor_quality=anchor_quality,
                local_timezone=ZoneInfo(str(timezone_id)),
            )
        ]
        if resolved is not None
    }


def _result(
    raw: str,
    *,
    future_intent: bool,
    calendar_range: CalendarRange,
    timezone_id: str,
    quality: str,
    anchor_event_ids: Iterable[str] = (),
) -> ClaimTemporalResolution:
    try:
        start, end = calendar_range.epochs
    except (OSError, OverflowError, ValueError):
        return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
    if end <= start:
        return _unresolved(raw, future_intent=future_intent, quality="ambiguous")
    frame = {
        "raw": raw,
        "kind": "target" if future_intent else "fact_validity",
        "resolution": quality,
        "resolved_range": [start, end],
        "calendar": calendar_range.descriptor(
            timezone_id=timezone_id,
            anchor_event_ids=anchor_event_ids,
        ),
    }
    if future_intent:
        return ClaimTemporalResolution(None, None, start, end, frame)
    return ClaimTemporalResolution(start, end, None, None, frame)


def _unresolved(
    raw: str,
    *,
    future_intent: bool,
    quality: str,
) -> ClaimTemporalResolution:
    return ClaimTemporalResolution(
        None,
        None,
        None,
        None,
        {
            "raw": raw,
            "kind": "target" if future_intent else "fact_validity",
            "resolution": quality,
            "resolved_range": None,
        },
    )


__all__ = ["ClaimTemporalResolution", "resolve_claim_temporal_fields"]
