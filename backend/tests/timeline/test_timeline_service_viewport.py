from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
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
                    "activity_snapshot": {
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
                    "activity_snapshot": {
                        "title": "Chat planning",
                        "summary": "Discussed semantic zoom.",
                        "tags": ["coding", "timeline"],
                        "entities": [{"label": "timeline"}],
                    }
                },
            },
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
            "metadata": {
                "activity_snapshot": {
                    "title": "Chat planning",
                    "summary": "Discussed semantic zoom.",
                }
            },
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
            },
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

    viewport = await service.get_viewport(
        scale="month", start=940_000.0, end=960_000.0, focus="self"
    )

    assert viewport["viewport"]["scale"] == "month"
    assert viewport["overview"]["summary"] == "A low evening centered on games."
    assert viewport["overview"]["key_takeaways"]
    assert viewport["overview"]["key_takeaways"][0] == "Main source: Chrome history"
    assert viewport["state_summary"]["mood_label"] == "Low"
    assert viewport["state_summary"]["stress_label"] == "Moderate stress"
    assert viewport["reflections"][0]["summary"] == "A low evening centered on games."
    assert viewport["state_bands"][0]["source_summary_ids"] == ["summary-1"]
    assert viewport["source_mix"][0]["source_type"] == "chrome_history"
    assert viewport["source_mix"][0]["label"] == "Chrome history"
    assert viewport["source_mix"][0]["event_count"] == 1
    assert viewport["theme_cards"][0]["title"] == "Game, Recovery"
    assert viewport["theme_cards"][0]["anchor"]["anchor_id"] == "evt-1"
    # Month view now includes clusters
    assert viewport["summary"]["cluster_count"] >= 1
    assert len(viewport["clusters"]) >= 1
    assert l1_store.last_query is not None
    assert l1_store.last_query["l1_retrieval_scopes"] == list(USER_VISIBLE_L1_RETRIEVAL_SCOPES)


async def test_timeline_service_localizes_viewport_chrome() -> None:
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
        scale="month",
        start=940_000.0,
        end=960_000.0,
        focus="self",
        locale="zh-CN",
    )

    assert viewport["viewport"]["locale"] == "zh-CN"
    assert viewport["overview"]["title"] == "窗口概览"
    assert viewport["overview"]["key_takeaways"][0] == "主要来源：Chrome 历史"
    assert viewport["overview"]["key_takeaways"][-1] == "捕获 1 条事件"
    assert viewport["state_summary"]["mood_label"] == "低落"
    assert viewport["state_summary"]["stress_label"] == "中等压力"
    assert viewport["source_mix"][0]["label"] == "Chrome 历史"


async def test_timeline_service_localizes_source_generated_cluster_labels() -> None:
    class _SourceOnlyL1Store(_FakeL1Store):
        async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_query = kwargs
            return [
                {
                    "event_id": "evt-source-only",
                    "timestamp": 100.0,
                    "source": "chrome_history",
                    "content": "Opened a browser page.",
                    "metadata": {},
                }
            ]

    service = TimelineService(
        SimpleNamespace(
            l1=_SourceOnlyL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(
        scale="day",
        start=90.0,
        end=120.0,
        focus="self",
        locale="zh-CN",
    )

    assert viewport["clusters"][0]["label"] == "Chrome 历史"


async def test_timeline_service_localizes_state_marker_fallback() -> None:
    service = TimelineService(
        SimpleNamespace(
            l1=_FakeL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
        )
    )

    viewport = await service.get_viewport(
        scale="day",
        start=0.0,
        end=1_100_000.0,
        focus="self",
        locale="zh-CN",
    )

    assert viewport["state_markers"][0]["label"] == "状态变化"
    assert viewport["state_markers"][0]["summary"] == "压力变化为 0.55。"
    assert viewport["state_summary"]["notable_changes"][0]["label"] == "状态变化"


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
                        "activity_snapshot": {
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
                        "activity_snapshot": {
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


async def test_timeline_service_returns_cover_candidates_and_auto_asset(tmp_path) -> None:
    class _PhotoL1Store(_FakeL1Store):
        async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_query = kwargs
            return [
                {
                    "event_id": "photo-a",
                    "timestamp": 100.0,
                    "source": "photo_library",
                    "content": "Took a photo.",
                    "asset_ref": "photo-library://asset-a",
                    "metadata": {
                        "activity_snapshot": {
                            "title": "Photo walk",
                            "summary": "A bright photo from the walk.",
                            "tags": ["photo"],
                        }
                    },
                },
                {
                    "event_id": "photo-b",
                    "timestamp": 200.0,
                    "source": "photo_library",
                    "content": "Took another photo.",
                    "asset_ref": "photo-library://asset-b",
                    "metadata": {
                        "activity_snapshot": {
                            "title": "Desk photo",
                            "summary": "A later photo at the desk.",
                            "tags": ["desk"],
                        }
                    },
                },
            ]

    service = TimelineService(
        SimpleNamespace(
            l1=_PhotoL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
            memory_db_path=str(tmp_path / "memory.db"),
        )
    )

    viewport = await service.get_viewport(scale="day", start=0.0, end=300.0, focus="self")

    assert viewport["cover"]["mode"] == "auto"
    assert viewport["cover"]["asset_ref"] == "photo-library://asset-a"
    assert [item["asset_ref"] for item in viewport["cover"]["candidates"]] == [
        "photo-library://asset-a",
        "photo-library://asset-b",
    ]


async def test_timeline_service_persists_selected_and_hidden_cover(tmp_path) -> None:
    class _PhotoL1Store(_FakeL1Store):
        async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
            self.last_query = kwargs
            return [
                {
                    "event_id": "photo-a",
                    "timestamp": 100.0,
                    "source": "photo_library",
                    "content": "Took a photo.",
                    "asset_ref": "photo-library://asset-a",
                    "metadata": {
                        "activity_snapshot": {"summary": "A bright photo.", "tags": ["photo"]}
                    },
                },
                {
                    "event_id": "photo-b",
                    "timestamp": 200.0,
                    "source": "photo_library",
                    "content": "Took another photo.",
                    "asset_ref": "photo-library://asset-b",
                    "metadata": {
                        "activity_snapshot": {"summary": "A later photo.", "tags": ["desk"]}
                    },
                },
            ]

    service = TimelineService(
        SimpleNamespace(
            l1=_PhotoL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
            memory_db_path=str(tmp_path / "memory.db"),
        )
    )

    selected = await service.set_cover_preference(
        scale="day",
        start=0.0,
        end=300.0,
        mode="asset",
        asset_ref="photo-library://asset-b",
    )
    assert selected["mode"] == "asset"
    assert selected["asset_ref"] == "photo-library://asset-b"

    viewport = await service.get_viewport(scale="day", start=0.0, end=300.0, focus="self")
    assert viewport["cover"]["asset_ref"] == "photo-library://asset-b"

    hidden = await service.set_cover_preference(
        scale="day",
        start=0.0,
        end=300.0,
        mode="hidden",
    )
    assert hidden["mode"] == "hidden"
    assert hidden["asset_ref"] is None

    restored = await service.set_cover_preference(
        scale="day",
        start=0.0,
        end=300.0,
        mode="auto",
    )
    assert restored["mode"] == "auto"
    assert restored["asset_ref"] == "photo-library://asset-a"


async def test_timeline_service_keeps_custom_uploaded_cover_available(tmp_path) -> None:
    from magi.memory.manual_entries.asset_store import ManualEntryAssetStore

    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = asset_store.store_bytes(b"custom cover", content_type="image/jpeg")
    service = TimelineService(
        SimpleNamespace(
            l1=_FakeL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
            memory_db_path=str(tmp_path / "memory.db"),
        ),
        manual_entry_asset_store=asset_store,
    )

    cover = await service.set_cover_preference(
        scale="day",
        start=0.0,
        end=300.0,
        mode="asset",
        asset_ref=asset_ref,
        source="custom_upload",
    )

    assert cover["asset_ref"] == asset_ref
    assert cover["candidates"][0]["asset_ref"] == asset_ref
    assert cover["candidates"][0]["source"] == "custom_upload"

    viewport = await service.get_viewport(scale="day", start=0.0, end=300.0, focus="self")
    assert viewport["cover"]["asset_ref"] == asset_ref
    assert viewport["cover"]["candidates"][0]["asset_ref"] == asset_ref


async def test_timeline_service_rejects_forged_custom_cover_refs(tmp_path) -> None:
    from magi.memory.manual_entries.asset_store import ManualEntryAssetStore

    asset_store = ManualEntryAssetStore(media_root=tmp_path / "media")
    service = TimelineService(
        SimpleNamespace(
            l1=_FakeL1Store(),
            l2=_FakeL2Store(),
            l3=_FakeL3Store(),
            l4=_FakeL4Store(),
            memory_db_path=str(tmp_path / "memory.db"),
        ),
        manual_entry_asset_store=asset_store,
    )

    for asset_ref in (
        "manual-entry-asset:///tmp/private.jpg",
        f"manual-entry-asset://{'a' * 64}.jpg",
    ):
        with pytest.raises(ValueError, match="available custom upload"):
            await service.set_cover_preference(
                scale="day",
                start=0.0,
                end=300.0,
                mode="asset",
                asset_ref=asset_ref,
                source="custom_upload",
            )


# ─────────────────────────────────────────────────────────────────────
# Theme card construction
# ─────────────────────────────────────────────────────────────────────


class _FakeEntityCatalog:
    """Resolves entity_id → canonical_name from an in-memory dict."""

    def __init__(self, names: dict[str, str]) -> None:
        self._names = names
        self.calls: list[list[str]] = []

    async def list_entities(
        self,
        *,
        entity_ids: list[str],
        limit: int = 100,
    ) -> list[dict]:
        self.calls.append(list(entity_ids))
        return [
            {"entity_id": eid, "canonical_name": self._names[eid], "entity_type": "concept"}
            for eid in entity_ids
            if eid in self._names
        ][:limit]


def _episode_cluster(*, block_id: str, entity_ids: list[str], event_count: int = 5) -> dict:
    """Build a minimal cluster dict matching what TimelineClusterBuilder emits."""
    return {
        "block_id": block_id,
        "time_start": 100.0,
        "time_end": 200.0,
        "label": "screen_time",
        "summary": "",
        "dominant_mode": "screen_time",
        "source_types": ["chrome_history"],
        "event_count": event_count,
        "representative_event_ids": [],
        # Episode clusters carry entity_ids here (see _episode_to_cluster).
        "keywords": entity_ids,
        "media_refs": [],
        "state_snapshot": {},
        "episode_id": block_id.removeprefix("episode:"),
    }


async def test_theme_cards_prefer_entity_canonical_names_over_reflections() -> None:
    """When entities are available, themes should be entity canonical_names —
    not the L3 reflection insight_keys that tend to leak ("Day反思").

    Each entity must appear in ≥2 clusters to pass the recurring-mention
    threshold (single-mention names are usually incidental, not "what you
    cared about").
    """
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    catalog = _FakeEntityCatalog(
        {
            "ent:anthropic": "Anthropic",
            "ent:sleep_agency": "sleep agency",
            "ent:cursor": "Cursor",
        }
    )
    builder = TimelineViewportBuilder(l1_store=None, entity_catalog=catalog)
    clusters = [
        _episode_cluster(
            block_id="episode:a", entity_ids=["ent:anthropic", "ent:sleep_agency"], event_count=10
        ),
        _episode_cluster(
            block_id="episode:b", entity_ids=["ent:anthropic", "ent:cursor"], event_count=5
        ),
        _episode_cluster(
            block_id="episode:c",
            entity_ids=["ent:anthropic", "ent:sleep_agency", "ent:cursor"],
            event_count=3,
        ),
    ]
    reflections = [
        {"reflection_id": "r1", "title": "Day反思", "summary": "...", "source_event_ids": []},
    ]

    cards = await builder._theme_card_builder.build(
        reflections=reflections, clusters=clusters, locale="zh"
    )

    titles = [c["title"] for c in cards]
    # Entity names appear, sorted by aggregated frequency (anthropic has highest weight)
    assert titles[0] == "Anthropic"
    assert "sleep agency" in titles
    assert "Cursor" in titles
    # Internal insight_key is filtered out
    assert "Day反思" not in titles


async def test_theme_cards_drop_single_mention_entities() -> None:
    """Entities mentioned in just one cluster don't qualify as 'themes'."""
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    catalog = _FakeEntityCatalog(
        {
            "ent:one_off": "One-off Mention",
            "ent:recurring": "Recurring Project",
        }
    )
    builder = TimelineViewportBuilder(l1_store=None, entity_catalog=catalog)
    clusters = [
        _episode_cluster(block_id="episode:a", entity_ids=["ent:one_off", "ent:recurring"]),
        _episode_cluster(block_id="episode:b", entity_ids=["ent:recurring"]),
    ]
    cards = await builder._theme_card_builder.build(reflections=[], clusters=clusters, locale="en")
    titles = [c["title"] for c in cards]
    assert "Recurring Project" in titles
    assert "One-off Mention" not in titles


async def test_theme_cards_blacklist_sensor_bucket_names() -> None:
    """Sensor-created bucket entities like "Chrome 历史" / "应用使用情况"
    must not surface as themes even if they pass the count threshold."""
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    catalog = _FakeEntityCatalog(
        {
            "ent:chrome_bucket": "Chrome 历史",
            "ent:app_usage": "应用使用情况",
            "ent:project": "Magi",
        }
    )
    builder = TimelineViewportBuilder(l1_store=None, entity_catalog=catalog)
    clusters = [
        _episode_cluster(
            block_id="episode:a",
            entity_ids=["ent:chrome_bucket", "ent:app_usage", "ent:project"],
        ),
        _episode_cluster(
            block_id="episode:b",
            entity_ids=["ent:chrome_bucket", "ent:app_usage", "ent:project"],
        ),
    ]
    cards = await builder._theme_card_builder.build(reflections=[], clusters=clusters, locale="zh")
    titles = [c["title"] for c in cards]
    assert "Chrome 历史" not in titles
    assert "应用使用情况" not in titles
    assert "Magi" in titles


async def test_theme_cards_filter_rejects_long_titles_and_internal_keys() -> None:
    """Sentence-shaped strings and *反思 suffixes are dropped from fallbacks."""
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    builder = TimelineViewportBuilder(l1_store=None)  # no entity catalog
    reflections = [
        {"reflection_id": "r1", "title": "Day反思", "summary": "", "source_event_ids": []},
        {
            "reflection_id": "r2",
            "title": "这一小时的记忆主要围绕浏览记录展开。浏览活动主要集中在 zhihu",
            "summary": "",
            "source_event_ids": [],
        },
        {"reflection_id": "r3", "title": "Magi", "summary": "", "source_event_ids": []},
        # Duplicate of r3 — should be deduped
        {"reflection_id": "r4", "title": "magi", "summary": "", "source_event_ids": []},
    ]

    cards = await builder._theme_card_builder.build(
        reflections=reflections, clusters=[], locale="zh"
    )

    titles = [c["title"] for c in cards]
    assert titles == ["Magi"]


async def test_theme_cards_fall_back_to_reflections_when_no_entity_catalog() -> None:
    """Backward compat: no catalog wired → existing reflection fallback still works."""
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    builder = TimelineViewportBuilder(l1_store=None)  # no catalog
    reflections = [
        {
            "reflection_id": "r1",
            "title": "morning planning",
            "summary": "x",
            "source_event_ids": ["evt-1"],
        },
    ]
    cards = await builder._theme_card_builder.build(
        reflections=reflections, clusters=[], locale="en"
    )
    assert len(cards) == 1
    assert cards[0]["title"] == "morning planning"


async def test_theme_cards_entity_themes_skip_transient_clusters() -> None:
    """Only episode:* clusters carry entity_ids in keywords; transient cluster:* ones
    carry plain text tags and must be skipped during entity aggregation."""
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    catalog = _FakeEntityCatalog({"ent:magi": "Magi"})
    builder = TimelineViewportBuilder(l1_store=None, entity_catalog=catalog)
    clusters = [
        # Two episode clusters with the same entity so it passes the
        # min-episode-count threshold.
        _episode_cluster(block_id="episode:e1", entity_ids=["ent:magi"], event_count=3),
        _episode_cluster(block_id="episode:e2", entity_ids=["ent:magi"], event_count=2),
        # Transient cluster — its "keywords" are tag strings, not entity_ids.
        {
            **_episode_cluster(block_id="cluster:0", entity_ids=["coding", "thinking"]),
            "episode_id": "",
        },
    ]
    cards = await builder._theme_card_builder.build(reflections=[], clusters=clusters, locale="en")
    titles = [c["title"] for c in cards]
    assert "Magi" in titles
    # Tag strings ("coding", "thinking") must NOT show up — they didn't go to the catalog.
    assert "coding" not in titles
    assert "thinking" not in titles


async def test_theme_cards_skip_non_themeable_cluster_labels() -> None:
    """Cluster labels synthesized from a source id ("Chat Projector") or a
    placeholder must not leak into the "你那时关心的" row; tag-derived
    labels still surface."""
    from magi.timeline.viewport_builder import TimelineViewportBuilder

    builder = TimelineViewportBuilder(l1_store=None)  # no catalog → cluster-label fallback
    clusters = [
        {
            **_episode_cluster(block_id="cluster:0", entity_ids=[]),
            "label": "Chat Projector",
            "label_is_themeable": False,
            "episode_id": "",
        },
        {
            **_episode_cluster(block_id="cluster:1", entity_ids=[]),
            "label": "Zhihu",
            "label_is_themeable": True,
            "episode_id": "",
        },
    ]
    cards = await builder._theme_card_builder.build(reflections=[], clusters=clusters, locale="zh")
    titles = [c["title"] for c in cards]
    assert "Chat Projector" not in titles
    assert "Zhihu" in titles
