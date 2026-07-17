"""Caller-side eager episodic summary generation (L3.generate_missing_episodic_summaries).

These tests exercise the seam used by the /reconsolidate route and the L2
maintenance scheduler: after consolidation, newly-promoted (or all active)
episodes lacking an L3 episodic summary get one generated. The two L3 methods
(``get_episodic_summary_by_episode_id`` dedup check + ``generate_episodic_summary``
generator) are stubbed; L1/L2 are simple fakes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.l3.summary_store import L3SummaryStore


class _FakeL2:
    """Minimal L2 surface: get_episode + list_episode_events."""

    def __init__(self, *, episodes: dict, events: dict) -> None:
        self._episodes = episodes
        self._events = events

    async def get_episode(self, *, episode_id: str):
        episode = self._episodes.get(episode_id)
        if episode is None:
            return None
        return {"status": "active", **episode}

    async def list_episode_events(self, *, episode_id: str):
        return self._events.get(episode_id, [])


class _FakeL2WithBackwrite(_FakeL2):
    """L2 fake that records episode label/summary updates and FTS writes."""

    def __init__(self, *, episodes: dict, events: dict) -> None:
        super().__init__(episodes=episodes, events=events)
        self.updates: list[dict] = []
        self.fts_writes: list[dict] = []

    async def update_episode(self, *, episode_id: str, **fields):
        self.updates.append({"episode_id": episode_id, **fields})
        return episode_id in self._episodes

    async def index_episode_fts(
        self, *, episode_id: str, summary: str, label: str, user_label: str
    ):
        self.fts_writes.append(
            {
                "episode_id": episode_id,
                "summary": summary,
                "label": label,
                "user_label": user_label,
            }
        )


def _build_store(tmp_path) -> L3SummaryStore:
    return L3SummaryStore(db_path=str(tmp_path / "l3.db"), vector_enabled=False)


@pytest.mark.asyncio
async def test_generates_for_promoted_episode_lacking_summary(tmp_path):
    """A newly-promoted episode without a summary gets one generated."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    store.generate_episodic_summary = AsyncMock(return_value={"summary_id": "new"})

    l2 = _FakeL2(
        episodes={"ep_new": {"episode_id": "ep_new", "episode_type": "activity"}},
        events={"ep_new": [{"event_id": "evt1"}]},
    )
    l1 = AsyncMock()

    result = await store.generate_missing_episodic_summaries(
        l1_store=l1, l2_store=l2, episode_ids=["ep_new"]
    )

    assert result["generated"] == 1
    assert result["errors"] == []
    store.generate_episodic_summary.assert_awaited_once()
    kwargs = store.generate_episodic_summary.await_args.kwargs
    assert kwargs["episode_event_ids"] == ["evt1"]
    assert kwargs["episode"]["episode_id"] == "ep_new"


@pytest.mark.asyncio
async def test_skips_episode_that_already_has_summary(tmp_path):
    """An episode that already has an L3 episodic summary is not regenerated (dedup)."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(
        side_effect=lambda eid: {"summary_id": "x"} if eid == "ep_has" else None
    )
    store.generate_episodic_summary = AsyncMock(return_value={"summary_id": "new"})

    l2 = _FakeL2(
        episodes={
            "ep_has": {"episode_id": "ep_has"},
            "ep_need": {"episode_id": "ep_need"},
        },
        events={"ep_has": [{"event_id": "e0"}], "ep_need": [{"event_id": "e1"}]},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_has", "ep_need"]
    )

    assert result["generated"] == 1
    store.generate_episodic_summary.assert_awaited_once()
    assert store.generate_episodic_summary.await_args.kwargs["episode"]["episode_id"] == "ep_need"


@pytest.mark.asyncio
async def test_skips_episode_with_no_events(tmp_path):
    """Episodes with no event memberships are skipped."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    store.generate_episodic_summary = AsyncMock()

    l2 = _FakeL2(
        episodes={"ep_empty": {"episode_id": "ep_empty"}},
        events={"ep_empty": []},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_empty"]
    )

    assert result["generated"] == 0
    store.generate_episodic_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_errors_are_captured_not_raised(tmp_path):
    """One bad episode does not block the rest; the error is collected."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    store.generate_episodic_summary = AsyncMock(
        side_effect=[RuntimeError("LLM timeout"), {"summary_id": "ok"}]
    )

    l2 = _FakeL2(
        episodes={"ep_bad": {"episode_id": "ep_bad"}, "ep_ok": {"episode_id": "ep_ok"}},
        events={"ep_bad": [{"event_id": "e1"}], "ep_ok": [{"event_id": "e2"}]},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_bad", "ep_ok"]
    )

    assert result["generated"] == 1
    assert len(result["errors"]) == 1
    assert "ep_bad" in result["errors"][0]


@pytest.mark.asyncio
async def test_duplicate_ids_deduped(tmp_path):
    """The same episode id appearing twice is generated at most once."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    store.generate_episodic_summary = AsyncMock(return_value={"summary_id": "ok"})

    l2 = _FakeL2(
        episodes={"ep_dup": {"episode_id": "ep_dup"}},
        events={"ep_dup": [{"event_id": "e1"}]},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_dup", "ep_dup"]
    )

    assert result["generated"] == 1
    store.generate_episodic_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_summary_is_backwritten_to_episode_and_fts(tmp_path):
    """A freshly generated summary lands on the episode row and its FTS entry."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(return_value=None)
    store.generate_episodic_summary = AsyncMock(
        return_value={
            "summary_id": "new",
            "content": "下午两小时在 v2ex 看 AI 讨论。",
            "insight_metadata": {"label": "v2ex 闲逛", "source_episode_id": "ep_new"},
        }
    )

    l2 = _FakeL2WithBackwrite(
        episodes={"ep_new": {"episode_id": "ep_new", "user_label": "自定义标签"}},
        events={"ep_new": [{"event_id": "evt1"}]},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_new"]
    )

    assert result["generated"] == 1
    assert l2.updates == [
        {
            "episode_id": "ep_new",
            "expected_status": "active",
            "label": "v2ex 闲逛",
            "summary": "下午两小时在 v2ex 看 AI 讨论。",
        }
    ]
    assert l2.fts_writes == [
        {
            "episode_id": "ep_new",
            "summary": "下午两小时在 v2ex 看 AI 讨论。",
            "label": "v2ex 闲逛",
            "user_label": "自定义标签",
        }
    ]


@pytest.mark.asyncio
async def test_existing_summary_backfills_empty_episode_row(tmp_path):
    """Episodes summarized before back-writing existed get backfilled on rerun."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(
        return_value={
            "summary_id": "old",
            "content": "调了一晚上内存系统。",
            "insight_metadata": '{"label": "调内存系统"}',
        }
    )
    store.generate_episodic_summary = AsyncMock()

    l2 = _FakeL2WithBackwrite(
        episodes={"ep_old": {"episode_id": "ep_old", "label": "", "summary": ""}},
        events={"ep_old": [{"event_id": "e1"}]},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_old"]
    )

    assert result["generated"] == 0
    store.generate_episodic_summary.assert_not_awaited()
    assert l2.updates == [
        {
            "episode_id": "ep_old",
            "expected_status": "active",
            "label": "调内存系统",
            "summary": "调了一晚上内存系统。",
        }
    ]
    assert len(l2.fts_writes) == 1


@pytest.mark.asyncio
async def test_existing_summary_does_not_overwrite_populated_episode_row(tmp_path):
    """Backfill only fires when the episode row has no label/summary yet."""
    store = _build_store(tmp_path)
    store.get_episodic_summary_by_episode_id = AsyncMock(
        return_value={
            "summary_id": "old",
            "content": "新内容",
            "insight_metadata": {"label": "新标签"},
        }
    )
    store.generate_episodic_summary = AsyncMock()

    l2 = _FakeL2WithBackwrite(
        episodes={"ep_full": {"episode_id": "ep_full", "label": "已有标签", "summary": "已有摘要"}},
        events={"ep_full": [{"event_id": "e1"}]},
    )

    result = await store.generate_missing_episodic_summaries(
        l1_store=AsyncMock(), l2_store=l2, episode_ids=["ep_full"]
    )

    assert result["generated"] == 0
    assert l2.updates == []
    assert l2.fts_writes == []
