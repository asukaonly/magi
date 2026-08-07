"""Temporal ownership tests for grounded L2 Claims."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import ClaimEvidenceInput
from magi.memory.l2.pipeline.claim_grounding import (
    normalize_phase1_claim_raw_time_expressions,
)
from magi.memory.l2.pipeline.source_time_policy import resolve_source_time_semantics
from magi.memory.l2.pipeline.temporal_claims import resolve_claim_temporal_fields
from magi.memory.l2.temporal_trust import MAX_FUTURE_CLOCK_SKEW_SECONDS


def _evidence(
    *,
    event_id: str = "evt-1",
    event_time: float = 1_775_400_000.0,
    timestamp_quality: str = "exact",
    calendar_timezone_id: str | None = "Asia/Shanghai",
) -> ClaimEvidenceInput:
    return ClaimEvidenceInput(
        event_id=event_id,
        link_role="supporting",
        required_for_grounding=False,
        event_time=event_time,
        timestamp_confidence=timestamp_quality,
        timestamp_quality=timestamp_quality,
        evidence_rule_version=2,
        evidence_mode="direct",
        source_type="chat",
        source_domain="user_authored",
        author_type="user",
        calendar_timezone_id=calendar_timezone_id,
    )


def test_raw_time_expression_must_be_an_exact_evidence_substring() -> None:
    payload: dict[str, object] = {
        "fact_claims": [
            {"evidence_text": "我明天去海边", "raw_time_expression": "明天"},
            {"evidence_text": "我明天去海边", "raw_time_expression": "明年"},
        ]
    }

    normalizations = normalize_phase1_claim_raw_time_expressions(payload)

    claims = payload["fact_claims"]
    assert isinstance(claims, list)
    assert claims[0]["raw_time_expression"] == "明天"
    assert claims[1]["raw_time_expression"] == ""
    assert len(normalizations) == 1


def test_chinese_absolute_date_uses_local_calendar_boundaries() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    resolution = resolve_claim_temporal_fields(
        raw_expression="2026年8月3日",
        future_intent=True,
        evidence=[_evidence()],
    )

    assert resolution.target_from == datetime(2026, 8, 3, tzinfo=timezone).timestamp()
    assert resolution.target_to == datetime(2026, 8, 4, tzinfo=timezone).timestamp()
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "calendar_anchor"
    assert resolution.raw_time_frame["calendar"] == {
        "timezone_id": "Asia/Shanghai",
        "precision": "day",
        "civil_start": "2026-08-03",
        "civil_end_exclusive": "2026-08-04",
        "operator": "absolute",
        "anchor_event_ids": [],
    }


def test_relative_day_anchors_to_each_evidence_in_local_timezone() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    anchor = datetime(2026, 8, 3, 23, 30, tzinfo=timezone).timestamp()
    resolution = resolve_claim_temporal_fields(
        raw_expression="明天",
        future_intent=True,
        evidence=[_evidence(event_time=anchor)],
    )

    assert resolution.target_from == datetime(2026, 8, 4, tzinfo=timezone).timestamp()
    assert resolution.target_to == datetime(2026, 8, 5, tzinfo=timezone).timestamp()
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "calendar_anchor"


@pytest.mark.parametrize(
    ("raw", "expected_start", "expected_end", "precision"),
    [
        ("下周一", (2026, 8, 10), (2026, 8, 11), "day"),
        ("今年秋天", (2026, 9, 1), (2026, 12, 1), "season"),
        ("明年冬天", (2027, 12, 1), (2028, 3, 1), "season"),
        ("年底", (2026, 12, 1), (2027, 1, 1), "month"),
        ("上半年", (2026, 1, 1), (2026, 7, 1), "half_year"),
        ("2个月后", (2026, 10, 1), (2026, 11, 1), "month"),
        ("3周后", (2026, 8, 24), (2026, 8, 25), "day"),
    ],
)
def test_ordered_relative_rules_use_frozen_anchor_and_timezone(
    raw: str,
    expected_start: tuple[int, int, int],
    expected_end: tuple[int, int, int],
    precision: str,
) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    anchor = datetime(2026, 8, 3, 12, tzinfo=timezone).timestamp()

    resolution = resolve_claim_temporal_fields(
        raw_expression=raw,
        future_intent=True,
        evidence=[_evidence(event_time=anchor)],
        now=anchor,
    )

    assert resolution.target_from == datetime(*expected_start, tzinfo=timezone).timestamp()
    assert resolution.target_to == datetime(*expected_end, tzinfo=timezone).timestamp()
    assert resolution.raw_time_frame is not None
    calendar = resolution.raw_time_frame["calendar"]
    assert isinstance(calendar, dict)
    assert calendar["precision"] == precision


def test_explicit_winter_crosses_year_without_trusted_event_time() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    resolution = resolve_claim_temporal_fields(
        raw_expression="2026年冬天",
        future_intent=True,
        evidence=[_evidence(timestamp_quality="approximate_recorded")],
    )

    assert resolution.target_from == datetime(2026, 12, 1, tzinfo=timezone).timestamp()
    assert resolution.target_to == datetime(2027, 3, 1, tzinfo=timezone).timestamp()


@pytest.mark.parametrize(
    "timestamp_quality",
    ["approximate_recorded", "derived_order", "low"],
)
def test_untrusted_source_time_cannot_anchor_relative_expression(
    timestamp_quality: str,
) -> None:
    resolution = resolve_claim_temporal_fields(
        raw_expression="今年秋天",
        future_intent=True,
        evidence=[_evidence(timestamp_quality=timestamp_quality)],
    )

    assert resolution.target_from is None
    assert resolution.target_to is None
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "low"


@pytest.mark.parametrize(
    ("raw", "evidence", "reason"),
    [
        ("秋天", [_evidence()], "unresolved_text"),
        ("明天", [_evidence(timestamp_quality="low")], "low"),
        (
            "明天",
            [
                _evidence(event_id="evt-1", event_time=1_775_400_000.0),
                _evidence(event_id="evt-2", event_time=1_775_572_800.0),
            ],
            "ambiguous",
        ),
    ],
)
def test_untrusted_or_underanchored_time_stays_raw_for_review(
    raw: str,
    evidence: list[ClaimEvidenceInput],
    reason: str,
) -> None:
    resolution = resolve_claim_temporal_fields(
        raw_expression=raw,
        future_intent=True,
        evidence=evidence,
    )

    assert resolution.target_from is None
    assert resolution.target_to is None
    assert resolution.raw_time_frame == {
        "raw": raw,
        "kind": "target",
        "resolution": reason,
        "resolved_range": None,
    }


@pytest.mark.parametrize("timestamp_quality", ["exact", "calendar_anchor"])
@pytest.mark.parametrize(
    ("raw_expression", "future_intent"),
    [("明天", True), ("昨天", False)],
)
def test_relative_time_rejects_evidence_beyond_future_clock_skew(
    timestamp_quality: str,
    raw_expression: str,
    future_intent: bool,
) -> None:
    now = 1_900_000_000.0
    resolution = resolve_claim_temporal_fields(
        raw_expression=raw_expression,
        future_intent=future_intent,
        evidence=[
            _evidence(
                event_time=now + MAX_FUTURE_CLOCK_SKEW_SECONDS + 1,
                timestamp_quality=timestamp_quality,
            )
        ],
        now=now,
    )

    assert resolution.fact_valid_from is None
    assert resolution.fact_valid_to is None
    assert resolution.target_from is None
    assert resolution.target_to is None
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "low"


def test_relative_time_accepts_evidence_at_future_clock_skew_boundary() -> None:
    now = 1_900_000_000.0
    resolution = resolve_claim_temporal_fields(
        raw_expression="明天",
        future_intent=True,
        evidence=[
            _evidence(event_time=now + MAX_FUTURE_CLOCK_SKEW_SECONDS),
        ],
        now=now,
    )

    assert resolution.target_from is not None
    assert resolution.target_to is not None
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "calendar_anchor"


def test_one_future_supporting_anchor_makes_relative_time_unresolved() -> None:
    now = 1_900_000_000.0
    resolution = resolve_claim_temporal_fields(
        raw_expression="明天",
        future_intent=True,
        evidence=[
            _evidence(event_id="evt-current", event_time=now),
            _evidence(
                event_id="evt-future",
                event_time=now + MAX_FUTURE_CLOCK_SKEW_SECONDS + 1,
            ),
        ],
        now=now,
    )

    assert resolution.target_from is None
    assert resolution.target_to is None
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "low"


def test_timestamp_quality_is_normalized_per_evidence_source() -> None:
    live_chat = resolve_source_time_semantics(
        source="chat",
        event_type="UserMessage",
        metadata={},
    )
    unknown_sensor = resolve_source_time_semantics(
        source="unknown_sensor",
        event_type="SENSOR_EVENT",
        metadata={"timestamp_confidence": "exact"},
    )
    frontmatter = resolve_source_time_semantics(
        source="history_import",
        event_type="history_import.document",
        metadata={"history_import": {"timestamp_confidence": "frontmatter"}},
    )
    file_mtime = resolve_source_time_semantics(
        source="history_import",
        event_type="history_import.document",
        metadata={"history_import": {"timestamp_confidence": "file_mtime"}},
    )
    source_order = resolve_source_time_semantics(
        source="history_import",
        event_type="history_import.document",
        metadata={"history_import": {"timestamp_confidence": "source_order"}},
    )

    assert (live_chat.timestamp_confidence, live_chat.timestamp_quality) == ("exact", "exact")
    assert (unknown_sensor.timestamp_confidence, unknown_sensor.timestamp_quality) == (
        "unknown",
        "low",
    )
    assert (frontmatter.timestamp_confidence, frontmatter.timestamp_quality) == (
        "frontmatter",
        "calendar_anchor",
    )
    assert (file_mtime.timestamp_confidence, file_mtime.timestamp_quality) == (
        "file_mtime",
        "approximate_recorded",
    )
    assert (source_order.timestamp_confidence, source_order.timestamp_quality) == (
        "source_order",
        "derived_order",
    )


def test_claim_identity_includes_temporal_semantics() -> None:
    base = dict(
        extractor_contract_version=4,
        evidence_rule_version=2,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        canonical_predicate="PLANS_TO",
        fact_kind="future_intent",
        object_type="activity",
        polarity="positive",
        specificity="concrete",
        temporal_cue="one_off",
        fact_valid_from=None,
        fact_valid_to=None,
        evidence_mode="direct",
        object_surface="去海边",
        object_value="去海边",
        supporting_event_ids=["evt-1"],
        antecedent_event_ids=[],
    )
    first = derive_claim_identity_key(
        **base,
        target_from=None,
        target_to=None,
        raw_time_frame={"raw": "秋天", "resolution": "ambiguous"},
    )
    second = derive_claim_identity_key(
        **base,
        target_from=None,
        target_to=None,
        raw_time_frame={"raw": "冬天", "resolution": "ambiguous"},
    )

    assert first != second


def test_claim_identity_excludes_runtime_calendar_epoch_projection() -> None:
    base = dict(
        extractor_contract_version=4,
        evidence_rule_version=2,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        canonical_predicate="PLANS_TO",
        fact_kind="future_intent",
        object_type="activity",
        polarity="positive",
        specificity="concrete",
        temporal_cue="one_off",
        evidence_mode="direct",
        object_surface="去海边",
        object_value="去海边",
        supporting_event_ids=["evt-1"],
        antecedent_event_ids=[],
    )
    utc = resolve_claim_temporal_fields(
        raw_expression="2026-08-04",
        future_intent=True,
        evidence=[_evidence(calendar_timezone_id="UTC")],
    )
    shanghai = resolve_claim_temporal_fields(
        raw_expression="2026-08-04",
        future_intent=True,
        evidence=[_evidence(calendar_timezone_id="Asia/Shanghai")],
    )

    assert utc.target_from != shanghai.target_from
    first = derive_claim_identity_key(
        **base,
        fact_valid_from=utc.fact_valid_from,
        fact_valid_to=utc.fact_valid_to,
        target_from=utc.target_from,
        target_to=utc.target_to,
        raw_time_frame=utc.raw_time_frame,
    )
    second = derive_claim_identity_key(
        **base,
        fact_valid_from=shanghai.fact_valid_from,
        fact_valid_to=shanghai.fact_valid_to,
        target_from=shanghai.target_from,
        target_to=shanghai.target_to,
        raw_time_frame=shanghai.raw_time_frame,
    )

    assert first == second


def test_temporal_resolution_requires_valid_consistent_calendar_provenance() -> None:
    missing = resolve_claim_temporal_fields(
        raw_expression="明天",
        future_intent=True,
        evidence=[_evidence(calendar_timezone_id=None)],
    )
    conflicting = resolve_claim_temporal_fields(
        raw_expression="明天",
        future_intent=True,
        evidence=[
            _evidence(event_id="evt-1", calendar_timezone_id="UTC"),
            _evidence(event_id="evt-2", calendar_timezone_id="Asia/Shanghai"),
        ],
    )

    assert missing.target_from is None
    assert missing.raw_time_frame is not None
    assert missing.raw_time_frame["resolution"] == "low"
    assert conflicting.target_from is None
    assert conflicting.raw_time_frame is not None
    assert conflicting.raw_time_frame["resolution"] == "ambiguous"


def test_equivalent_timezone_aliases_resolve_one_calendar_range() -> None:
    anchor = datetime(2026, 8, 3, 12, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()

    resolution = resolve_claim_temporal_fields(
        raw_expression="tomorrow",
        future_intent=True,
        evidence=[
            _evidence(
                event_id="evt-canonical-zone",
                event_time=anchor,
                calendar_timezone_id="America/Los_Angeles",
            ),
            _evidence(
                event_id="evt-zone-alias",
                event_time=anchor,
                calendar_timezone_id="US/Pacific",
            ),
        ],
    )

    assert (
        resolution.target_from
        == datetime(2026, 8, 4, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    )
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "calendar_anchor"


@pytest.mark.parametrize(
    ("raw", "expected_hours"),
    [("2026-03-08", 23.0), ("2026-11-01", 25.0)],
)
def test_calendar_day_preserves_dst_boundaries(raw: str, expected_hours: float) -> None:
    resolution = resolve_claim_temporal_fields(
        raw_expression=raw,
        future_intent=True,
        evidence=[_evidence(calendar_timezone_id="America/Los_Angeles")],
    )

    assert resolution.target_from is not None
    assert resolution.target_to is not None
    assert (resolution.target_to - resolution.target_from) / 3600 == expected_hours


def test_skipped_civil_day_is_not_a_resolved_calendar_range() -> None:
    resolution = resolve_claim_temporal_fields(
        raw_expression="2011-12-30",
        future_intent=True,
        evidence=[_evidence(calendar_timezone_id="Pacific/Apia")],
    )

    assert resolution.target_from is None
    assert resolution.target_to is None
    assert resolution.raw_time_frame is not None
    assert resolution.raw_time_frame["resolution"] == "ambiguous"
