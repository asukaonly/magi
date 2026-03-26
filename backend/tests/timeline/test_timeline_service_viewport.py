from __future__ import annotations

from types import SimpleNamespace

from magi.timeline.service import TimelineService


class _FakeL1Store:
    async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "event_id": "evt-1",
                "timestamp": 100.0,
                "source": "chat",
                "content": "Discussed the redesign.",
                "metadata": {
                    "timeline": {
                        "title": "Chat planning",
                        "summary": "Discussed semantic zoom.",
                        "tags": ["timeline"],
                        "entities": [{"label": "timeline"}],
                    }
                },
            }
        ]

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
                "period_start": 90.0,
                "period_end": 140.0,
                "content": "A focused day.",
                "key_topics": ["timeline"],
                "key_entities": [{"entity_id": "project:magi"}],
                "sentiment_summary": {"tone": "steady"},
                "change_and_pattern": {"patterns": ["planning"]},
                "source_event_ids": ["evt-1"],
                "source_event_count": 1,
            }
        ]


class _FakeL4Store:
    async def get_all_skills(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return []


async def test_timeline_service_returns_month_viewport() -> None:
    service = TimelineService(
        SimpleNamespace(
            l1=_FakeL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(scale="month", start=80.0, end=180.0, focus="self")

    assert viewport["viewport"]["scale"] == "month"
    assert viewport["reflections"][0]["summary"] == "A focused day."
    assert viewport["state_bands"][0]["source_summary_ids"] == ["summary-1"]

