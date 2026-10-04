"""Tests for L2 experience review backfill behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_backwrite_experience_review_skips_fallback_review():
    from magi.memory.l3.episode_backwrite import backwrite_experience_review

    l2_store = MagicMock()
    l2_store.update_experience = AsyncMock(return_value=True)
    experience = {
        "experience_id": "exp-fallback",
        "title": "Untitled experience",
        "magi_interpretation": "",
    }
    summary = {
        "content": "Magi grouped related episode evidence into a narratable memory.",
        "insight_metadata": {"label": "Untitled experience", "fallback": True},
    }

    updated = await backwrite_experience_review(l2_store, experience=experience, summary=summary)

    assert updated is False
    l2_store.update_experience.assert_not_awaited()


@pytest.mark.asyncio
async def test_backwrite_experience_review_cannot_update_invalidated_experience():
    from magi.memory.l3.episode_backwrite import backwrite_experience_review

    l2_store = MagicMock()
    l2_store.update_experience = AsyncMock(return_value=False)
    updated = await backwrite_experience_review(
        l2_store,
        experience={"experience_id": "exp-private", "status": "active"},
        summary={
            "content": "Private recap",
            "insight_metadata": {"label": "Private title"},
        },
    )

    assert updated is False
    l2_store.update_experience.assert_awaited_once_with(
        experience_id="exp-private",
        expected_status="active",
        title="Private title",
        magi_interpretation="Private recap",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "title,intent,outcome,expected_generated_fields",
    [
        (
            "Untitled experience",
            "Untitled experience",
            "",
            {"intent": "Rebuild the review search path.", "outcome": "Reviews are searchable."},
        ),
        (
            "Search pipeline work",
            "",
            "",
            {"intent": "Rebuild the review search path.", "outcome": "Reviews are searchable."},
        ),
        ("Search pipeline work", "My original goal", "My recorded outcome", {}),
    ],
)
async def test_existing_review_backwrites_generated_fields_and_preserves_user_fields(
    title, intent, outcome, expected_generated_fields
):
    from magi.memory.l2.experiences.summary_generation import generate_missing_experience_summaries

    l1_store = MagicMock()
    experience = {
        "experience_id": "exp-review",
        "title": title,
        "intent": intent,
        "outcome": outcome,
        "magi_interpretation": "Magi grouped related episode evidence into a narratable memory.",
        "user_label": "My title",
        "user_note": "My note",
        "user_pinned": True,
    }
    summary = {
        "summary_id": "sum-valid",
        "content": "Repaired review persistence and search indexing.",
        "insight_metadata": {
            "label": "Review search repair",
            "intent": "Rebuild the review search path.",
            "outcome": "Reviews are searchable.",
        },
    }
    l2_store = MagicMock(
        list_experiences=AsyncMock(return_value=[{"experience_id": "exp-review"}]),
        get_experience=AsyncMock(return_value=experience),
        list_experience_members=AsyncMock(),
        update_experience=AsyncMock(return_value=True),
    )
    l3_store = MagicMock(
        get_episodic_summary_by_experience_id=AsyncMock(return_value=summary),
        generate_experience_summary=AsyncMock(),
    )
    result = await generate_missing_experience_summaries(
        l1_store=l1_store, l2_store=l2_store, l3_store=l3_store
    )
    assert result == {"generated": 0, "errors": []}
    l3_store.generate_experience_summary.assert_not_awaited()
    l2_store.list_experience_members.assert_not_awaited()
    l2_store.update_experience.assert_awaited_once_with(
        experience_id="exp-review",
        expected_status="active",
        title="Review search repair",
        magi_interpretation="Repaired review persistence and search indexing.",
        **expected_generated_fields
    )
    assert {key: experience[key] for key in ("user_label", "user_note", "user_pinned")} == {
        "user_label": "My title",
        "user_note": "My note",
        "user_pinned": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_field",
    [
        "missing",
        "placeholder_label",
        "machine_label",
        "user_label",
        "generic_content",
        "raw_titles",
        "fallback",
    ],
)
async def test_each_invalid_review_field_independently_triggers_refresh_and_backwrite(
    invalid_field,
):
    from magi.memory.l2.experiences.summary_generation import generate_missing_experience_summaries

    l1_store = MagicMock()
    experience = {"experience_id": "exp-review", "title": "Search repair"}
    members = [{"event_id": "event-evidence", "member_role": "core"}]
    existing = {
        "summary_id": "sum-old",
        "content": "Reviewed the search repair work.",
        "insight_metadata": {"label": "Search review"},
    }
    if invalid_field == "missing":
        existing = None
    elif invalid_field == "placeholder_label":
        existing["insight_metadata"]["label"] = "Untitled experience / Untitled exper"
    elif invalid_field == "machine_label":
        existing["insight_metadata"]["label"] = "github / 7e4eb50fae61"
    elif invalid_field == "user_label":
        existing["insight_metadata"]["label"] = "github / local user"
    elif invalid_field == "generic_content":
        existing["content"] = "Magi grouped related episode evidence into a narratable memory."
    elif invalid_field == "raw_titles":
        existing["content"] = (
            "Chrome 浏览 X - Google Search；Chrome 浏览 GitHub pull request；Chrome 浏览 Gmail"
        )
    elif invalid_field == "fallback":
        existing["insight_metadata"]["fallback"] = True
    generated = {
        "summary_id": "sum-new",
        "content": "Repaired review persistence and search indexing.",
        "insight_metadata": {"label": "Review search repair"},
    }
    l2_store = MagicMock(
        get_experience=AsyncMock(return_value=experience),
        list_experience_members=AsyncMock(return_value=members),
        update_experience=AsyncMock(return_value=True),
    )
    l3_store = MagicMock(
        get_episodic_summary_by_experience_id=AsyncMock(return_value=existing),
        generate_experience_summary=AsyncMock(return_value=generated),
    )
    result = await generate_missing_experience_summaries(
        l1_store=l1_store, l2_store=l2_store, l3_store=l3_store, experience_ids=["exp-review"]
    )
    assert result == {"generated": 1, "errors": []}
    l3_store.get_episodic_summary_by_experience_id.assert_awaited_once_with("exp-review")
    l2_store.get_experience.assert_awaited_once_with(experience_id="exp-review")
    l2_store.list_experience_members.assert_awaited_once_with(experience_id="exp-review")
    l3_store.generate_experience_summary.assert_awaited_once_with(
        l1_store=l1_store, l2_store=l2_store, experience=experience, experience_members=members
    )
    l2_store.update_experience.assert_awaited_once_with(
        experience_id="exp-review",
        expected_status="active",
        title="Review search repair",
        magi_interpretation="Repaired review persistence and search indexing.",
    )
