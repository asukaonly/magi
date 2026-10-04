"""Model-extraction admission precedence and durable frequency promotion."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from magi.memory.l2.pipeline.extraction import resolve_llm_extraction
from magi.memory.l2.promotion_counter import L2PromotionCounter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({}, True),
        ({"allow_llm_extraction": False}, False),
        ({"allow_llm_extraction": False, "promotion_threshold": 1, "promotion_key": "x"}, False),
        ({"allow_llm_extraction": False, "promotion_override": "force_full"}, True),
        (
            {"promotion_threshold": 5, "promotion_key": "x", "promotion_override": "force_full"},
            True,
        ),
        (
            {
                "promotion_threshold": 1,
                "promotion_key": "x",
                "promotion_override": "force_structured_only",
            },
            False,
        ),
        ({"promotion_override": "bogus"}, True),
        ({"promotion_threshold": 5}, True),
    ],
)
async def test_static_admission_precedence_does_not_consume_frequency_budget(metadata, expected):
    counter = SimpleNamespace(
        bump=AsyncMock(side_effect=RuntimeError("Unexpected frequency access"))
    )
    event = SimpleNamespace(metadata_json=metadata, source="chrome", event_id="event")
    assert await resolve_llm_extraction(event, counter) is expected
    counter.bump.assert_not_awaited()


@pytest.mark.asyncio
async def test_frequency_admission_survives_restart_and_preserves_missing_counter_fallback(
    tmp_path,
):
    metadata = {"promotion_threshold": 2, "promotion_key": "github.com"}
    path = str(tmp_path / "promotion.db")
    outcomes = []
    for event_id in ["e1", "e2", "e3"]:
        event = SimpleNamespace(metadata_json=metadata, source="chrome", event_id=event_id)
        outcomes.append(await resolve_llm_extraction(event, L2PromotionCounter(path)))
    assert outcomes == [False, True, True]
    assert (
        await resolve_llm_extraction(
            SimpleNamespace(
                metadata_json={"promotion_threshold": 5, "promotion_key": "k"},
                source="chrome",
                event_id="other",
            ),
            None,
        )
        is True
    )
