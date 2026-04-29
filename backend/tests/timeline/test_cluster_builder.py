from __future__ import annotations

from magi.timeline.cluster_builder import TimelineClusterBuilder


async def test_cluster_builder_groups_adjacent_events_into_activity_blocks() -> None:
    builder = TimelineClusterBuilder()

    events = [
        {
            "event_id": "evt-1",
            "timestamp": 100.0,
            "source": "chat",
            "content": "Discussed refactoring the timeline page.",
            "metadata": {
                "timeline": {
                    "title": "Chat planning",
                    "summary": "Discussed the semantic zoom redesign.",
                    "tags": ["timeline", "planning"],
                    "entities": [{"label": "timeline"}],
                }
            },
        },
        {
            "event_id": "evt-2",
            "timestamp": 130.0,
            "source": "manual_journal",
            "content": "Outlined the redesign structure.",
            "metadata": {
                "timeline": {
                    "title": "Journal note",
                    "summary": "Outlined semantic zoom structure.",
                    "tags": ["timeline", "notes"],
                    "entities": [{"label": "timeline"}],
                }
            },
        },
        {
            "event_id": "evt-3",
            "timestamp": 900.0,
            "source": "chrome_history",
            "content": "Read unrelated article.",
            "metadata": {
                "timeline": {
                    "title": "Browser research",
                    "summary": "Looked at an article.",
                    "tags": ["research"],
                    "entities": [{"label": "browser"}],
                }
            },
        },
    ]

    clusters = builder.build(events, scale="day")

    assert len(clusters) == 2
    assert clusters[0]["block_id"] == "cluster:0"
    assert clusters[0]["event_count"] == 2
    assert clusters[0]["representative_event_ids"] == ["evt-1", "evt-2"]
    assert clusters[0]["source_types"] == ["chat", "manual_journal"]
    assert clusters[0]["dominant_mode"] == "timeline"


async def test_cluster_builder_groups_events_at_month_scale() -> None:
    builder = TimelineClusterBuilder()

    events = [
        {
            "event_id": "evt-a",
            "timestamp": 1000.0,
            "source": "chat",
            "content": "Morning planning session.",
            "metadata": {"timeline": {"tags": ["planning"], "entities": [{"label": "project"}]}},
        },
        {
            "event_id": "evt-b",
            "timestamp": 2000.0,  # 16 min later, same theme
            "source": "chat",
            "content": "Continued planning.",
            "metadata": {"timeline": {"tags": ["planning"], "entities": [{"label": "project"}]}},
        },
        {
            "event_id": "evt-c",
            "timestamp": 20000.0,  # ~5h later, different theme
            "source": "chrome_history",
            "content": "Reading articles.",
            "metadata": {"timeline": {"tags": ["reading"], "entities": [{"label": "browser"}]}},
        },
    ]

    clusters = builder.build(events, scale="month")

    assert len(clusters) == 2
    assert clusters[0]["event_count"] == 2
    assert clusters[1]["event_count"] == 1


async def test_cluster_builder_exposes_episode_user_annotations() -> None:
    builder = TimelineClusterBuilder()

    clusters = builder.build(
        [],
        scale="week",
        episodes=[
            {
                "episode_id": "ep-1",
                "time_start": 100.0,
                "time_end": 200.0,
                "label": "planning",
                "summary": "Planned the week.",
                "source_event_count": 2,
                "user_label": "Weekly Planning",
                "user_note": "Keep this in review.",
                "user_pinned": True,
            }
        ],
    )

    assert clusters[0]["label"] == "Weekly Planning"
    assert clusters[0]["user_label"] == "Weekly Planning"
    assert clusters[0]["user_note"] == "Keep this in review."
    assert clusters[0]["user_pinned"] is True
