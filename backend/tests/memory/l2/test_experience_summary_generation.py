"""Tests for L2 experience review backfill behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_generate_missing_experience_summaries_refreshes_placeholder_review():
    from magi.memory.l2.experiences.summary_generation import (
        generate_missing_experience_summaries,
    )

    l1_store = MagicMock()
    l2_store = MagicMock()
    l2_store.list_experiences = AsyncMock(return_value=[{"experience_id": "exp-bad"}])
    l2_store.get_experience = AsyncMock(return_value={"experience_id": "exp-bad"})
    l2_store.list_experience_members = AsyncMock(return_value=[])

    l3_store = MagicMock()
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum-bad",
        "content": "Magi grouped related episode evidence into a narratable memory.",
        "insight_metadata": {"label": "Untitled experience / Untitled exper"},
    })
    l3_store.generate_experience_summary = AsyncMock(return_value={"summary_id": "sum-fixed"})

    result = await generate_missing_experience_summaries(
        l1_store=l1_store,
        l2_store=l2_store,
        l3_store=l3_store,
    )

    assert result == {"generated": 1, "errors": []}
    l3_store.generate_experience_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_missing_experience_summaries_skips_existing_good_review():
    from magi.memory.l2.experiences.summary_generation import (
        generate_missing_experience_summaries,
    )

    l1_store = MagicMock()
    l2_store = MagicMock()
    l2_store.list_experiences = AsyncMock(return_value=[{"experience_id": "exp-good"}])
    l2_store.get_experience = AsyncMock(return_value={"experience_id": "exp-good"})
    l2_store.list_experience_members = AsyncMock(return_value=[])

    l3_store = MagicMock()
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum-good",
        "content": "Reviewed the week of testing AI coding tools.",
        "insight_metadata": {"label": "AI coding tool tests"},
    })
    l3_store.generate_experience_summary = AsyncMock(return_value={"summary_id": "sum-new"})

    result = await generate_missing_experience_summaries(
        l1_store=l1_store,
        l2_store=l2_store,
        l3_store=l3_store,
    )

    assert result == {"generated": 0, "errors": []}
    l3_store.generate_experience_summary.assert_not_awaited()
