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
                "activity_snapshot": {
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
                "activity_snapshot": {
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
                "activity_snapshot": {
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
            "metadata": {"activity_snapshot": {"tags": ["planning"], "entities": [{"label": "project"}]}},
        },
        {
            "event_id": "evt-b",
            "timestamp": 2000.0,  # 16 min later, same theme
            "source": "chat",
            "content": "Continued planning.",
            "metadata": {"activity_snapshot": {"tags": ["planning"], "entities": [{"label": "project"}]}},
        },
        {
            "event_id": "evt-c",
            "timestamp": 20000.0,  # ~5h later, different theme
            "source": "chrome_history",
            "content": "Reading articles.",
            "metadata": {"activity_snapshot": {"tags": ["reading"], "entities": [{"label": "browser"}]}},
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


async def test_cluster_builder_surfaces_photo_asset_ref_from_transient_cluster() -> None:
    builder = TimelineClusterBuilder()

    clusters = builder.build(
        [
            {
                "event_id": "photo-1",
                "timestamp": 300.0,
                "source": "photo_library_apple_photos",
                "metadata": {
                    "representative_photos": [
                        {"asset_local_id": "apple-photos:asset-1"}
                    ],
                    "activity_snapshot": {"tags": ["photo_library"]},
                },
            }
        ],
        scale="day",
    )

    assert clusters[0]["representative_asset_ref"] == "photo-library://apple-photos:asset-1"


async def test_cluster_builder_surfaces_photo_asset_ref_from_episode_events() -> None:
    builder = TimelineClusterBuilder()

    clusters = builder.build(
        [
            {
                "event_id": "photo-1",
                "timestamp": 150.0,
                "source": "photo_library_apple_photos",
                "metadata": {
                    "representative_photos": [
                        {"asset_local_id": "apple-photos:asset-1"}
                    ],
                    "activity_snapshot": {"tags": ["photo_library"]},
                },
            }
        ],
        scale="day",
        episodes=[
            {
                "episode_id": "ep-1",
                "time_start": 100.0,
                "time_end": 200.0,
                "label": "activity",
                "source_event_count": 1,
            }
        ],
    )

    assert clusters[0]["representative_asset_ref"] == "photo-library://apple-photos:asset-1"


# ──────────────────────────────────────────────────────────────────────
# Event-derived label fallback (P12-T2)
# ──────────────────────────────────────────────────────────────────────


def _chrome_event(*, event_id: str, ts: float, domain: str) -> dict:
    """Build a Chrome-history-shaped L1 event for the cluster builder."""
    return {
        "event_id": event_id,
        "timestamp": ts,
        "source": "chrome_history",
        "metadata": {
            "activity_snapshot": {
                # The shape the Chrome source actually writes today —
                # source-name tag + the visited domain. cluster_builder
                # must filter out the source-name and surface the domain.
                "tags": ["chrome_history", domain],
                "title": f"Some page at {domain}",
            },
        },
    }


async def test_cluster_builder_derives_label_from_event_tags_when_episode_is_placeholder() -> None:
    """Episode with default label='activity' but Chrome events carrying
    a domain tag should surface the domain, not the placeholder."""
    builder = TimelineClusterBuilder()
    events = [
        _chrome_event(event_id="e1", ts=110.0, domain="openai.com"),
        _chrome_event(event_id="e2", ts=130.0, domain="openai.com"),
        _chrome_event(event_id="e3", ts=170.0, domain="openai.com"),
    ]
    clusters = builder.build(
        events,
        scale="day",
        episodes=[
            {
                "episode_id": "ep-1",
                "time_start": 100.0,
                "time_end": 200.0,
                "label": "activity",  # the default placeholder
                "summary": "",
                "source_event_count": 3,
            }
        ],
    )
    assert len(clusters) == 1
    assert clusters[0]["label"] == "openai.com"
    # Display label should NOT be title-cased (would mangle the domain).
    assert "Openai" not in clusters[0]["label"]


async def test_cluster_builder_joins_top_two_domains_with_ideographic_comma() -> None:
    """Mixed-domain cluster: top 2 by frequency joined with 、."""
    builder = TimelineClusterBuilder()
    events = [
        _chrome_event(event_id="e1", ts=110.0, domain="openai.com"),
        _chrome_event(event_id="e2", ts=120.0, domain="openai.com"),
        _chrome_event(event_id="e3", ts=130.0, domain="anthropic.com"),
        _chrome_event(event_id="e4", ts=140.0, domain="news.ycombinator.com"),
    ]
    clusters = builder.build(
        events,
        scale="day",
        episodes=[{
            "episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0,
            "label": "", "source_event_count": 4,
        }],
    )
    # Top 2 by frequency are openai.com (2) and a tie between the other
    # two (1 each). The first-listed in Counter insertion order wins
    # the tie — Counter preserves insertion order for equal counts.
    assert clusters[0]["label"].startswith("openai.com、")
    assert "、" in clusters[0]["label"]


async def test_cluster_builder_keeps_existing_episode_label_when_meaningful() -> None:
    """Don't override when the episode itself has a real label."""
    builder = TimelineClusterBuilder()
    events = [_chrome_event(event_id="e1", ts=110.0, domain="openai.com")]
    clusters = builder.build(
        events,
        scale="day",
        episodes=[{
            "episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0,
            "label": "planning", "source_event_count": 1,
        }],
    )
    # "planning" gets title-cased the historical way ("Planning"), not
    # replaced by the event-derived domain.
    assert clusters[0]["label"] == "Planning"


async def test_cluster_builder_falls_back_to_episode_type_when_no_specific_tags() -> None:
    """Events with only the generic source-name tag (no domain) should
    fall through to the episode_type fallback, not produce an empty
    label."""
    builder = TimelineClusterBuilder()
    events = [{
        "event_id": "e1", "timestamp": 110.0, "source": "chrome_history",
        "metadata": {"activity_snapshot": {"tags": ["chrome_history"]}},  # no domain
    }]
    clusters = builder.build(
        events,
        scale="day",
        episodes=[{
            "episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0,
            "label": "activity", "episode_type": "session",
            "source_event_count": 1,
        }],
    )
    assert clusters[0]["label"] == "Session"


async def test_cluster_builder_marks_source_derived_label_non_themeable() -> None:
    """Transient path: a chat-only group has no tags, so its label is
    synthesized from the source id ("chat_projector" -> "Chat Projector").
    That's plumbing, not a concern — flag it non-themeable so the themes
    row skips it. A tag-backed label stays themeable."""
    builder = TimelineClusterBuilder()

    source_only = builder.build(
        [{
            "event_id": "c1", "timestamp": 100.0, "source": "chat_projector",
            "metadata": {"activity_snapshot": {"tags": []}},
        }],
        scale="day",  # no episodes -> transient _build_cluster path
    )
    assert source_only[0]["label"] == "Chat Projector"
    assert source_only[0]["label_is_themeable"] is False

    tagged = builder.build(
        [{
            "event_id": "t1", "timestamp": 100.0, "source": "chat",
            "metadata": {"activity_snapshot": {"tags": ["planning"]}},
        }],
        scale="day",
    )
    assert tagged[0]["label_is_themeable"] is True


async def test_cluster_builder_marks_placeholder_episode_label_non_themeable() -> None:
    """Episode path: an episode resolving to the episode_type/"activity"
    placeholder is non-themeable; a real or event-derived label is not."""
    builder = TimelineClusterBuilder()

    placeholder = builder.build(
        [{
            "event_id": "e1", "timestamp": 110.0, "source": "chrome_history",
            "metadata": {"activity_snapshot": {"tags": ["chrome_history"]}},  # no domain
        }],
        scale="day",
        episodes=[{
            "episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0,
            "label": "activity", "episode_type": "session", "source_event_count": 1,
        }],
    )
    assert placeholder[0]["label"] == "Session"
    assert placeholder[0]["label_is_themeable"] is False

    derived = builder.build(
        [_chrome_event(event_id="e1", ts=110.0, domain="openai.com")],
        scale="day",
        episodes=[{
            "episode_id": "ep-2", "time_start": 100.0, "time_end": 200.0,
            "label": "activity", "source_event_count": 1,
        }],
    )
    assert derived[0]["label"] == "openai.com"
    assert derived[0]["label_is_themeable"] is True
