from __future__ import annotations

from magi.timeline.state_band_builder import TimelineStateBandBuilder


async def test_state_band_builder_creates_self_bands_and_markers() -> None:
    builder = TimelineStateBandBuilder()

    summaries = [
        {
            "summary_id": "summary-1",
            "summary_type": "temporal",
            "summary_category": "day",
            "period_start": 100.0,
            "period_end": 200.0,
            "sentiment_summary": {"tone": "steady", "stress_level": 0.25},
            "change_and_pattern": {"changes": ["settled into focus"]},
        },
        {
            "summary_id": "summary-2",
            "summary_type": "temporal",
            "summary_category": "day",
            "period_start": 200.0,
            "period_end": 300.0,
            "sentiment_summary": {"tone": "tense", "stress_level": 0.82},
            "change_and_pattern": {"changes": ["pressure increased"]},
        },
    ]
    assertions = [
        {
            "assertion_id": "assertion-1",
            "entity_id": "user:self",
            "entity_type": "user",
            "trait_name": "mood",
            "trait_value": "focused",
            "confidence_score": 0.74,
            "first_inferred_at": 120.0,
            "last_validated_at": 180.0,
        },
        {
            "assertion_id": "assertion-2",
            "entity_id": "user:self",
            "entity_type": "user",
            "trait_name": "engagement",
            "trait_value": "0.88",
            "confidence_score": 0.67,
            "first_inferred_at": 210.0,
            "last_validated_at": 260.0,
        },
    ]
    snapshots = [
        {
            "snapshot_id": "snapshot-1",
            "entity_id": "user:self",
            "entity_type": "user",
            "current_mood": "focused",
            "current_stress_level": 0.31,
            "current_engagement": 0.81,
            "last_updated_at": 175.0,
        }
    ]

    bands, markers = builder.build(
        start=90.0,
        end=310.0,
        summaries=summaries,
        assertions=assertions,
        snapshots=snapshots,
    )

    assert len(bands) == 2
    assert bands[0]["band_id"] == "state-band:summary-1"
    assert bands[0]["label"] == "focused"
    assert bands[0]["source_summary_ids"] == ["summary-1"]
    assert bands[0]["source_assertion_ids"] == ["assertion-1"]
    assert markers[0]["kind"] == "shift"
    assert markers[0]["source_summary_ids"] == ["summary-2"]

