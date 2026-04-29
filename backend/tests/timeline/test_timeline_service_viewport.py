from __future__ import annotations

from types import SimpleNamespace

from magi.timeline.service import TimelineService


class _FakeL1Store:
    def __init__(self) -> None:
        self.last_query: dict | None = None

    async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_query = kwargs
        events = [
            {
                "event_id": "evt-1",
                "timestamp": 950_000.0,
                "source": "chrome_history",
                "content": "Spent the night reading game guides while feeling low.",
                "metadata": {
                    "timeline": {
                        "title": "Game session",
                        "summary": "Played through a difficult section while feeling low.",
                        "tags": ["game", "recovery"],
                        "entities": [{"label": "game"}],
                    }
                },
            },
            {
                "event_id": "evt-2",
                "timestamp": 1_000_000.0,
                "source": "chat",
                "content": "Discussed the redesign.",
                "metadata": {
                    "timeline": {
                        "title": "Chat planning",
                        "summary": "Discussed semantic zoom.",
                        "tags": ["coding", "timeline"],
                        "entities": [{"label": "timeline"}],
                    }
                },
            }
        ]
        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        if start_time is not None:
            events = [event for event in events if float(event["timestamp"]) >= float(start_time)]
        if end_time is not None:
            events = [event for event in events if float(event["timestamp"]) <= float(end_time)]
        return events

    async def get_event(self, event_id: str):  # type: ignore[no-untyped-def]
        return {
            "event_id": event_id,
            "timestamp": 100.0,
            "source": "chat",
            "content": "Discussed the redesign.",
            "metadata": {"timeline": {"title": "Chat planning", "summary": "Discussed semantic zoom."}},
        }


class _FakeL2Store:
    async def list_tom_assertions(self, **kwargs):  # type: ignore[no-untyped-def]
        return []

    async def list_tom_snapshots(self, **kwargs):  # type: ignore[no-untyped-def]
        return []


class _FakeL3Store:
    db_path = ":memory:"

    async def list_summaries(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return [
            {
                "summary_id": "summary-1",
                "summary_type": "temporal",
                "summary_category": "day",
                "period_start": 949_000.0,
                "period_end": 951_000.0,
                "content": "A low evening centered on games.",
                "key_topics": ["game", "recovery"],
                "key_entities": [{"entity_id": "activity:game"}],
                "sentiment_summary": {"tone": "low"},
                "change_and_pattern": {"patterns": ["late-night gaming"]},
                "source_event_ids": ["evt-1"],
                "source_event_count": 1,
            },
            {
                "summary_id": "summary-2",
                "summary_type": "temporal",
                "summary_category": "day",
                "period_start": 99_900.0,
                "period_end": 100_100.0,
                "content": "A focused planning day.",
                "key_topics": ["timeline", "coding"],
                "key_entities": [{"entity_id": "project:magi"}],
                "sentiment_summary": {"tone": "steady"},
                "change_and_pattern": {"patterns": ["planning"]},
                "source_event_ids": ["evt-2"],
                "source_event_count": 1,
            }
        ]


class _FakeL4Store:
    async def get_all_skills(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return []


async def test_timeline_service_returns_month_viewport() -> None:
    l1_store = _FakeL1Store()
    service = TimelineService(
        SimpleNamespace(
            l1=l1_store,
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(scale="month", start=940_000.0, end=960_000.0, focus="self")

    assert viewport["viewport"]["scale"] == "month"
    assert viewport["overview"]["summary"] == "A low evening centered on games."
    assert viewport["overview"]["key_takeaways"]
    assert viewport["state_summary"]["mood_label"] == "Low"
    assert viewport["state_summary"]["stress_label"] == "Moderate stress"
    assert viewport["reflections"][0]["summary"] == "A low evening centered on games."
    assert viewport["state_bands"][0]["source_summary_ids"] == ["summary-1"]
    assert viewport["source_mix"][0]["source_type"] == "chrome_history"
    assert viewport["source_mix"][0]["event_count"] == 1
    assert viewport["theme_cards"][0]["title"] == "Game, Recovery"
    assert viewport["theme_cards"][0]["anchor"]["anchor_id"] == "evt-1"
    # Month view now includes clusters
    assert viewport["summary"]["cluster_count"] >= 1
    assert len(viewport["clusters"]) >= 1


async def test_timeline_service_interprets_natural_language_query() -> None:
    l1_store = _FakeL1Store()
    service = TimelineService(
        SimpleNamespace(
            l1=l1_store,
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(
        scale="day",
        start=0.0,
        end=14 * 24 * 60 * 60.0,
        query="上周 低落 游戏",
        focus="self",
    )

    assert l1_store.last_query is not None
    assert l1_store.last_query["start_time"] == (14 - 7) * 24 * 60 * 60.0
    assert viewport["overview"]["title"] == "Day overview"
    assert viewport["summary"]["event_count"] == 1
    assert viewport["clusters"][0]["label"] == "Game"


async def test_timeline_service_reads_timeline_projection_from_metadata_json() -> None:
    class _MetadataJsonL1Store(_FakeL1Store):
        async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_query = kwargs
            return [
                {
                    "event_id": "evt-3",
                    "timestamp": 100.0,
                    "source": "calendar",
                    "content": "Interview",
                    "metadata_json": {
                        "timeline": {
                            "title": "Interview (09:00-10:00)",
                            "summary": "Interview",
                            "source_type": "calendar",
                            "tags": ["calendar"],
                            "entities": [{"label": "interview"}],
                        }
                    },
                }
            ]

    service = TimelineService(
        SimpleNamespace(
            l1=_MetadataJsonL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(scale="hour", start=0.0, end=200.0, focus="self")

    assert viewport["raw_events"][0]["title"] == "Interview (09:00-10:00)"
    assert viewport["raw_events"][0]["summary"] == "Interview"
    assert viewport["raw_events"][0]["source_type"] == "calendar"


async def test_timeline_service_uses_idempotency_key_as_source_item_fallback() -> None:
    class _IdempotencyFallbackL1Store(_FakeL1Store):
        async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_query = kwargs
            return [
                {
                    "event_id": "evt-4",
                    "idempotency_key": "calendar_event:42",
                    "timestamp": 100.0,
                    "source": "calendar",
                    "content": "Interview",
                    "metadata_json": {
                        "timeline": {
                            "title": "Interview (09:00-10:00)",
                            "summary": "Interview",
                            "source_type": "calendar",
                        }
                    },
                }
            ]

    service = TimelineService(
        SimpleNamespace(
            l1=_IdempotencyFallbackL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(scale="hour", start=0.0, end=200.0, focus="self")

    assert viewport["raw_events"][0]["source_item_id"] == "calendar_event:42"
