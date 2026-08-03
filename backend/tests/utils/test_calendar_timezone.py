"""Contracts for durable event calendar timezone metadata."""

from magi.utils.calendar_timezone import (
    calendar_timezone_id_from_metadata,
    canonical_timezone_id,
    with_calendar_timezone,
)


def test_calendar_timezone_metadata_round_trips_an_iana_identifier() -> None:
    metadata = with_calendar_timezone(
        {"source": "chat"},
        calendar_timezone_id="Asia/Shanghai",
    )

    assert metadata == {
        "source": "chat",
        "_temporal": {"calendar_timezone_id": "Asia/Shanghai"},
    }
    assert calendar_timezone_id_from_metadata(metadata) == "Asia/Shanghai"


def test_calendar_timezone_rejects_abbreviations_and_fixed_offsets() -> None:
    assert canonical_timezone_id("PDT") is None
    assert canonical_timezone_id("+08:00") is None
    assert with_calendar_timezone({"source": "chat"}, calendar_timezone_id="PDT") == {
        "source": "chat"
    }
