"""Tests for P5 timeline integration with durable episodes and state transitions."""

from __future__ import annotations

from typing import Any

import pytest

from magi.timeline.cluster_builder import TimelineClusterBuilder
from magi.timeline.context_bundle_builder import TimelineContextBundleBuilder
from magi.timeline.viewport_builder import TimelineViewportBuilder

# ── cluster_builder: episode-aware ───────────────────────────────


def _make_event(event_id: str, timestamp: float, tag: str = "activity") -> dict[str, Any]:
    return {
        "event_id": event_id,
        "timestamp": timestamp,
        "source": "test",
        "content": f"Event {event_id}",
        "metadata": {"activity_snapshot": {"tags": [tag], "entities": []}},
    }


def _make_episode(
    episode_id: str,
    time_start: float,
    time_end: float,
    label: str = "episode",
    user_label: str | None = None,
    user_note: str | None = None,
) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "episode_type": "activity",
        "time_start": time_start,
        "time_end": time_end,
        "label": label,
        "summary": f"Summary of {episode_id}",
        "dominant_mode": "activity",
        "primary_entity_ids": "[]",
        "source_event_count": 5,
        "user_label": user_label,
        "user_note": user_note,
    }


class TestClusterBuilderEpisodes:
    def test_day_scale_uses_episodes(self):
        builder = TimelineClusterBuilder()
        events = [_make_event("e1", 100.0)]
        episodes = [_make_episode("ep1", 50.0, 150.0, label="Morning work")]

        clusters = builder.build(events, scale="day", episodes=episodes)

        assert len(clusters) == 1
        assert clusters[0]["block_id"] == "episode:ep1"
        assert clusters[0]["episode_id"] == "ep1"
        assert "Morning Work" in clusters[0]["label"]

    def test_week_scale_uses_episodes(self):
        builder = TimelineClusterBuilder()
        episodes = [_make_episode("ep1", 100.0, 200.0)]

        clusters = builder.build([], scale="week", episodes=episodes)

        assert len(clusters) == 1
        assert clusters[0]["episode_id"] == "ep1"

    def test_month_scale_ignores_episodes(self):
        """month scale uses transient clustering, not episodes."""
        builder = TimelineClusterBuilder()
        events = [_make_event("e1", 100.0), _make_event("e2", 200.0)]
        episodes = [_make_episode("ep1", 50.0, 250.0)]

        clusters = builder.build(events, scale="month", episodes=episodes)

        # month is not in EPISODE_SCALES, so episodes are ignored
        assert all("episode_id" not in c for c in clusters)

    def test_uncovered_events_get_transient_clusters(self):
        builder = TimelineClusterBuilder()
        # Event at t=500 is NOT covered by the episode (100-200)
        events = [_make_event("e1", 150.0), _make_event("e2", 500.0)]
        episodes = [_make_episode("ep1", 100.0, 200.0)]

        clusters = builder.build(events, scale="day", episodes=episodes)

        assert len(clusters) == 2
        episode_cluster = [c for c in clusters if c.get("episode_id")]
        transient_cluster = [c for c in clusters if not c.get("episode_id")]
        assert len(episode_cluster) == 1
        assert len(transient_cluster) == 1

    def test_episode_user_label_preferred(self):
        builder = TimelineClusterBuilder()
        episodes = [_make_episode("ep1", 100.0, 200.0, label="auto", user_label="My Trip")]

        clusters = builder.build([], scale="day", episodes=episodes)

        assert clusters[0]["label"] == "My Trip"
        assert clusters[0]["user_label"] == "My Trip"

    def test_no_episodes_falls_back_to_transient(self):
        builder = TimelineClusterBuilder()
        events = [_make_event("e1", 100.0), _make_event("e2", 110.0)]

        clusters = builder.build(events, scale="day", episodes=None)

        assert len(clusters) >= 1
        assert all("episode_id" not in c for c in clusters)

    def test_clusters_sorted_by_time(self):
        builder = TimelineClusterBuilder()
        events = [_make_event("e3", 500.0)]
        episodes = [
            _make_episode("ep2", 300.0, 400.0),
            _make_episode("ep1", 100.0, 200.0),
        ]

        clusters = builder.build(events, scale="day", episodes=episodes)

        times = [c["time_start"] for c in clusters]
        assert times == sorted(times)


# ── context_bundle_builder: episode-aware ─────────────────────────


class _FakeL1:
    async def get_user_visible_event(self, event_id: str) -> dict[str, Any] | None:
        return {
            "event_id": event_id,
            "timestamp": 100.0,
            "source": "chat",
            "content": f"Content of {event_id}",
            "metadata": {
                "activity_snapshot": {
                    "title": f"Title {event_id}",
                    "summary": f"Summary {event_id}",
                }
            },
        }


class _FakeL2WithEpisodes:
    async def list_episode_events(self, episode_id: str) -> list[dict[str, Any]]:
        if episode_id == "ep-1":
            return [{"event_id": "ev1"}, {"event_id": "ev2"}]
        return []

    async def find_edges_by_event_id(self, event_id: str) -> list[dict[str, Any]]:
        return []

    async def list_tom_assertions(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


class _FakeL3:
    async def list_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []


class TestContextBundleEpisode:
    @pytest.mark.asyncio
    async def test_episode_anchor_loads_member_events(self):
        builder = TimelineContextBundleBuilder(
            l1_store=_FakeL1(),
            l2_store=_FakeL2WithEpisodes(),
            l3_store=_FakeL3(),
        )
        anchor = {"episode_id": "ep-1", "user_label": "My Trip", "user_note": "Great time"}

        bundle = await builder.build(anchor=anchor)

        assert bundle["episode_id"] == "ep-1"
        assert bundle["user_label"] == "My Trip"
        assert bundle["user_note"] == "Great time"
        assert len(bundle["l1_events"]) == 2

    @pytest.mark.asyncio
    async def test_non_episode_anchor_uses_event_ids(self):
        builder = TimelineContextBundleBuilder(
            l1_store=_FakeL1(),
            l2_store=_FakeL2WithEpisodes(),
            l3_store=_FakeL3(),
        )
        anchor = {"representative_event_ids": ["ev1"]}

        bundle = await builder.build(anchor=anchor)

        assert "episode_id" not in bundle
        assert len(bundle["l1_events"]) == 1


# ── viewport_builder: episodes + state_transitions ────────────────


class _FakeL1Viewport:
    async def query_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [_make_event("evt-1", 1000.0)]

    async def get_user_visible_event(self, event_id: str) -> dict[str, Any] | None:
        return _make_event(event_id, 1000.0)


class _FakeL2Viewport:
    def __init__(
        self,
        *,
        episodes: list[dict[str, Any]] | None = None,
        assertions: list[dict[str, Any]] | None = None,
    ):
        self._episodes = episodes or []
        self._assertions = assertions or []

    async def list_tom_assertions(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._assertions

    async def list_tom_snapshots(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def list_episodes(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._episodes


class _FakeL3Viewport:
    async def list_summaries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []


class TestViewportEpisodes:
    @pytest.mark.asyncio
    async def test_day_viewport_includes_episodes(self):
        episodes = [_make_episode("ep1", 900.0, 1100.0)]
        builder = TimelineViewportBuilder(
            l1_store=_FakeL1Viewport(),
            l2_store=_FakeL2Viewport(episodes=episodes),
            l3_store=_FakeL3Viewport(),
        )

        result = await builder.build_viewport(scale="day", start=800.0, end=1200.0)

        assert len(result["episodes"]) == 1
        assert result["episodes"][0]["episode_id"] == "ep1"

    @pytest.mark.asyncio
    async def test_hour_viewport_excludes_episodes(self):
        episodes = [_make_episode("ep1", 900.0, 1100.0)]
        builder = TimelineViewportBuilder(
            l1_store=_FakeL1Viewport(),
            l2_store=_FakeL2Viewport(episodes=episodes),
            l3_store=_FakeL3Viewport(),
        )

        result = await builder.build_viewport(scale="hour", start=800.0, end=1200.0)

        assert result["episodes"] == []

    @pytest.mark.asyncio
    async def test_state_transitions_from_superseded_assertions(self):
        assertions = [
            {
                "assertion_id": "a-old",
                "entity_id": "user:self",
                "trait_name": "city",
                "trait_value": "Hangzhou",
                "status": "superseded",
                "superseded_by": "a-new",
                "superseded_at": 2000.0,
                "updated_at": 2000.0,
            },
            {
                "assertion_id": "a-new",
                "entity_id": "user:self",
                "trait_name": "city",
                "trait_value": "Shanghai",
                "status": "stable",
            },
        ]
        builder = TimelineViewportBuilder(
            l1_store=_FakeL1Viewport(),
            l2_store=_FakeL2Viewport(assertions=assertions),
            l3_store=_FakeL3Viewport(),
        )

        result = await builder.build_viewport(scale="day", start=800.0, end=3000.0)

        transitions = result["state_transitions"]
        assert len(transitions) == 1
        assert transitions[0]["trait_name"] == "city"
        assert transitions[0]["old_value"] == "Hangzhou"
        assert transitions[0]["new_value"] == "Shanghai"

    @pytest.mark.asyncio
    async def test_empty_state_transitions_when_no_superseded(self):
        assertions = [
            {
                "assertion_id": "a1",
                "entity_id": "user:self",
                "trait_name": "mood",
                "trait_value": "happy",
                "status": "stable",
            },
        ]
        builder = TimelineViewportBuilder(
            l1_store=_FakeL1Viewport(),
            l2_store=_FakeL2Viewport(assertions=assertions),
            l3_store=_FakeL3Viewport(),
        )

        result = await builder.build_viewport(scale="day", start=800.0, end=3000.0)

        assert result["state_transitions"] == []

    @pytest.mark.asyncio
    async def test_viewport_has_new_keys(self):
        """Verify the viewport payload shape includes episodes and state_transitions."""
        builder = TimelineViewportBuilder(
            l1_store=_FakeL1Viewport(),
            l2_store=_FakeL2Viewport(),
            l3_store=_FakeL3Viewport(),
        )

        result = await builder.build_viewport(scale="day", start=0.0, end=2000.0)

        assert "episodes" in result
        assert "overview" in result
        assert "state_summary" in result
        assert "state_transitions" in result
        assert "source_mix" in result
        assert "theme_cards" in result
        assert "state_bands" in result
        assert "clusters" in result
