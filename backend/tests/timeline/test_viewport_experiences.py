from __future__ import annotations

from typing import Any

from magi.timeline.viewport_builder import TimelineViewportBuilder
from magi.timeline.viewport_experiences import TimelineExperienceLinker


class _ExperienceStore:
    def __init__(
        self,
        *,
        experiences: list[dict[str, Any]],
        members: dict[str, list[dict[str, Any]]],
        chapters: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.experiences = experiences
        self.members = members
        self.chapters = chapters or {}
        self.list_kwargs: dict[str, Any] | None = None

    async def list_experiences(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_kwargs = kwargs
        return self.experiences

    async def list_experience_members(
        self,
        *,
        experience_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        del limit
        return self.members.get(experience_id, [])

    async def list_experience_chapters(
        self,
        *,
        experience_id: str,
    ) -> list[dict[str, Any]]:
        return self.chapters.get(experience_id, [])


async def test_experience_linker_adds_existing_chapter_relation() -> None:
    store = _ExperienceStore(
        experiences=[
            {
                "experience_id": "experience-1",
                "status": "active",
                "title": "Generated trip title",
                "user_label": "My Shanghai Trip",
            }
        ],
        members={
            "experience-1": [
                {
                    "member_type": "episode",
                    "member_id": "episode-1",
                    "role": "included",
                }
            ]
        },
        chapters={
            "experience-1": [
                {
                    "chapter_id": "chapter-1",
                    "title": "Arrival",
                    "episode_ids": ["episode-1"],
                    "event_ids": [],
                }
            ]
        },
    )

    clusters = await TimelineExperienceLinker(l2_store=store).decorate(
        [{"block_id": "episode:episode-1", "episode_id": "episode-1"}],
        start=100.0,
        end=200.0,
    )

    assert clusters[0]["experience_id"] == "experience-1"
    assert clusters[0]["experience_title"] == "My Shanghai Trip"
    assert clusters[0]["experience_chapter_id"] == "chapter-1"
    assert clusters[0]["experience_chapter_title"] == "Arrival"
    assert store.list_kwargs == {
        "status": "active",
        "time_start": 100.0,
        "time_end": 200.0,
        "limit": 200,
    }


async def test_experience_linker_does_not_invent_chapter_for_member_only_match() -> None:
    store = _ExperienceStore(
        experiences=[
            {
                "experience_id": "experience-2",
                "status": "active",
                "title": "Research afternoon",
            }
        ],
        members={
            "experience-2": [
                {
                    "member_type": "event",
                    "member_id": "event-2",
                    "role": "included",
                }
            ]
        },
        chapters={
            "experience-2": [
                {
                    "chapter_id": "chapter-other",
                    "title": "Unrelated chapter",
                    "episode_ids": ["episode-other"],
                    "event_ids": ["event-other"],
                }
            ]
        },
    )

    clusters = await TimelineExperienceLinker(l2_store=store).decorate(
        [
            {
                "block_id": "cluster:0",
                "representative_event_ids": ["event-2"],
            }
        ],
        start=100.0,
        end=200.0,
    )

    assert clusters[0]["experience_id"] == "experience-2"
    assert clusters[0]["experience_title"] == "Research afternoon"
    assert "experience_chapter_id" not in clusters[0]
    assert "experience_chapter_title" not in clusters[0]


async def test_experience_linker_ignores_chapter_without_durable_identity() -> None:
    store = _ExperienceStore(
        experiences=[
            {
                "experience_id": "experience-2",
                "status": "active",
                "title": "Research afternoon",
            }
        ],
        members={
            "experience-2": [
                {
                    "member_type": "episode",
                    "member_id": "episode-2",
                    "role": "included",
                }
            ]
        },
        chapters={
            "experience-2": [
                {
                    "chapter_id": "",
                    "title": "Incomplete chapter",
                    "episode_ids": ["episode-2"],
                    "event_ids": [],
                }
            ]
        },
    )

    clusters = await TimelineExperienceLinker(l2_store=store).decorate(
        [{"block_id": "episode:episode-2", "episode_id": "episode-2"}],
        start=100.0,
        end=200.0,
    )

    assert clusters[0]["experience_id"] == "experience-2"
    assert "experience_chapter_id" not in clusters[0]
    assert "experience_chapter_title" not in clusters[0]


async def test_experience_linker_is_noop_when_store_interfaces_are_missing() -> None:
    original = [{"block_id": "cluster:0", "representative_event_ids": ["event-1"]}]

    clusters = await TimelineExperienceLinker(l2_store=object()).decorate(
        original,
        start=100.0,
        end=200.0,
    )

    assert clusters == original
    assert clusters is not original
    assert clusters[0] is not original[0]


class _FakeL1Store:
    async def query_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return [
            {
                "event_id": "event-1",
                "timestamp": 150.0,
                "source": "chat",
                "content": "Discussed the trip.",
                "metadata": {
                    "activity_snapshot": {
                        "title": "Trip planning",
                        "summary": "Discussed the trip.",
                        "tags": ["trip"],
                        "entities": [],
                    }
                },
            }
        ]


class _ExperienceAwareL2Store(_ExperienceStore):
    async def list_tom_assertions(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return []

    async def list_tom_snapshots(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return []

    async def list_episodes(self, **kwargs: Any) -> list[dict[str, Any]]:
        del kwargs
        return [
            {
                "episode_id": "episode-1",
                "episode_type": "activity",
                "time_start": 100.0,
                "time_end": 200.0,
                "label": "Trip planning",
                "summary": "Discussed the trip.",
                "dominant_mode": "chat",
                "primary_entity_ids": [],
                "source_event_count": 1,
            }
        ]


async def test_day_viewport_exposes_existing_experience_and_chapter_links() -> None:
    l2_store = _ExperienceAwareL2Store(
        experiences=[
            {
                "experience_id": "experience-1",
                "status": "active",
                "title": "Shanghai Trip",
            }
        ],
        members={
            "experience-1": [
                {
                    "member_type": "episode",
                    "member_id": "episode-1",
                    "role": "included",
                }
            ]
        },
        chapters={
            "experience-1": [
                {
                    "chapter_id": "chapter-1",
                    "title": "Planning",
                    "episode_ids": ["episode-1"],
                    "event_ids": [],
                }
            ]
        },
    )
    builder = TimelineViewportBuilder(l1_store=_FakeL1Store(), l2_store=l2_store)

    viewport = await builder.build_viewport(
        scale="day",
        start=0.0,
        end=300.0,
        locale="en",
    )

    assert viewport["clusters"][0]["experience_id"] == "experience-1"
    assert viewport["clusters"][0]["experience_title"] == "Shanghai Trip"
    assert viewport["clusters"][0]["experience_chapter_id"] == "chapter-1"
    assert viewport["clusters"][0]["experience_chapter_title"] == "Planning"


async def test_day_viewport_still_renders_when_experience_lookup_fails() -> None:
    class _FailingExperienceStore(_ExperienceAwareL2Store):
        async def list_experiences(self, **kwargs: Any) -> list[dict[str, Any]]:
            del kwargs
            raise RuntimeError("experience store unavailable")

    l2_store = _FailingExperienceStore(experiences=[], members={})
    builder = TimelineViewportBuilder(l1_store=_FakeL1Store(), l2_store=l2_store)

    viewport = await builder.build_viewport(
        scale="day",
        start=0.0,
        end=300.0,
        locale="en",
    )

    assert len(viewport["clusters"]) == 1
    assert "experience_id" not in viewport["clusters"][0]
