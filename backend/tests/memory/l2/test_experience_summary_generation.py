"""Tests for L2 experience review backfill behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_backwrite_experience_review_updates_generated_template_fields():
    from magi.memory.l3.episode_backwrite import backwrite_experience_review

    l2_store = MagicMock()
    l2_store.update_experience = AsyncMock(return_value=True)
    experience = {
        "experience_id": "exp-template",
        "title": "Untitled experience",
        "magi_interpretation": "Magi 看到这段经历主要围绕「Repeated activity around github」展开。",
        "user_label": "用户自己的标题",
        "user_note": "用户自己的备注",
        "user_pinned": True,
    }
    summary = {
        "content": "你集中处理了 Magi 经历链路的 review 回写，并让检索能吃到这段结果。",
        "insight_metadata": {"label": "Magi 经历链路回写"},
    }

    updated = await backwrite_experience_review(l2_store, experience=experience, summary=summary)

    assert updated is True
    l2_store.update_experience.assert_awaited_once_with(
        experience_id="exp-template",
        title="Magi 经历链路回写",
        magi_interpretation="你集中处理了 Magi 经历链路的 review 回写，并让检索能吃到这段结果。",
    )


@pytest.mark.asyncio
async def test_backwrite_experience_review_preserves_existing_good_title():
    from magi.memory.l3.episode_backwrite import backwrite_experience_review

    l2_store = MagicMock()
    l2_store.update_experience = AsyncMock(return_value=True)
    experience = {
        "experience_id": "exp-good-title",
        "title": "东京旅行规划",
        "magi_interpretation": "magi grouped related episode evidence into a narratable memory.",
    }
    summary = {
        "content": "你围绕东京夏季旅行做了路线筛选，并把动漫巡礼和避暑节奏放在一起比较。",
        "insight_metadata": {"label": "东京夏季路线筛选"},
    }

    updated = await backwrite_experience_review(l2_store, experience=experience, summary=summary)

    assert updated is True
    l2_store.update_experience.assert_awaited_once_with(
        experience_id="exp-good-title",
        magi_interpretation="你围绕东京夏季旅行做了路线筛选，并把动漫巡礼和避暑节奏放在一起比较。",
    )


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
async def test_generate_missing_experience_summaries_backfills_existing_good_review():
    from magi.memory.l2.experiences.summary_generation import (
        generate_missing_experience_summaries,
    )

    l1_store = MagicMock()
    l2_store = MagicMock()
    l2_store.list_experiences = AsyncMock(return_value=[{"experience_id": "exp-backfill"}])
    l2_store.get_experience = AsyncMock(return_value={
        "experience_id": "exp-backfill",
        "title": "Untitled experience",
        "magi_interpretation": "magi grouped related episode evidence into a narratable memory.",
    })
    l2_store.list_experience_members = AsyncMock(return_value=[])
    l2_store.update_experience = AsyncMock(return_value=True)

    l3_store = MagicMock()
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum-good",
        "content": "你把经历链路里 review 和检索之间断开的地方补上了。",
        "insight_metadata": {"label": "经历链路回写"},
    })
    l3_store.generate_experience_summary = AsyncMock(return_value={"summary_id": "sum-new"})

    result = await generate_missing_experience_summaries(
        l1_store=l1_store,
        l2_store=l2_store,
        l3_store=l3_store,
    )

    assert result == {"generated": 0, "errors": []}
    l3_store.generate_experience_summary.assert_not_awaited()
    l2_store.update_experience.assert_awaited_once_with(
        experience_id="exp-backfill",
        title="经历链路回写",
        magi_interpretation="你把经历链路里 review 和检索之间断开的地方补上了。",
    )


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
async def test_generate_missing_experience_summaries_refreshes_machine_id_review_label():
    from magi.memory.l2.experiences.summary_generation import (
        generate_missing_experience_summaries,
    )

    l1_store = MagicMock()
    l2_store = MagicMock()
    l2_store.list_experiences = AsyncMock(return_value=[{"experience_id": "exp-machine"}])
    l2_store.get_experience = AsyncMock(return_value={"experience_id": "exp-machine"})
    l2_store.list_experience_members = AsyncMock(return_value=[])

    l3_store = MagicMock()
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum-machine",
        "content": "Reviewed real activity.",
        "insight_metadata": {"label": "github / 7e4eb50fae61 / local user"},
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
async def test_generate_missing_experience_summaries_refreshes_fallback_title_dump_review():
    from magi.memory.l2.experiences.summary_generation import (
        generate_missing_experience_summaries,
    )

    l1_store = MagicMock()
    l2_store = MagicMock()
    l2_store.list_experiences = AsyncMock(return_value=[{"experience_id": "exp-raw"}])
    l2_store.get_experience = AsyncMock(return_value={"experience_id": "exp-raw"})
    l2_store.list_experience_members = AsyncMock(return_value=[])

    l3_store = MagicMock()
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value={
        "summary_id": "sum-raw",
        "content": (
            "Chrome 浏览 X - Google Search（访问 2 次）；"
            "Chrome 浏览 GitHub pull request；"
            "Chrome 浏览 Gmail"
        ),
        "insight_metadata": {"label": "Chrome / Google", "fallback": True},
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
    l2_store.get_experience = AsyncMock(return_value={
        "experience_id": "exp-good",
        "title": "AI coding tool tests",
        "magi_interpretation": "Reviewed the week of testing AI coding tools.",
    })
    l2_store.list_experience_members = AsyncMock(return_value=[])
    l2_store.update_experience = AsyncMock(return_value=True)

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
    l2_store.update_experience.assert_not_awaited()
