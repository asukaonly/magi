from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import timeline as timeline_module
from magi.api.routers.timeline import timeline_router


class _FakeTimelineService:
    def __init__(self):
        self.viewport_calls = []
        self.context_calls = []
        self.cover_calls = []

    async def get_viewport(
        self, *, scale, start, end, query=None, timezone=None, focus="self", locale="en"
    ):
        self.viewport_calls.append(
            {
                "scale": scale,
                "start": start,
                "end": end,
                "query": query,
                "timezone": timezone,
                "focus": focus,
                "locale": locale,
            }
        )
        payload = {
            "viewport": {
                "scale": scale,
                "start": start,
                "end": end,
                "focus": focus,
                "query": query,
                "timezone": timezone,
                "locale": locale,
            },
            "summary": {
                "cluster_count": 1 if scale in {"week", "day"} else 0,
                "event_count": 3,
                "dominant_modes": ["deep_work"],
            },
            "state_bands": [
                {
                    "band_id": "band-1",
                    "time_start": start,
                    "time_end": end,
                    "valence": 0.35,
                    "stress_level": 0.62,
                    "engagement": 0.78,
                    "confidence": 0.71,
                    "label": "Focused with mild stress",
                    "source_summary_ids": ["summary-1"],
                    "source_assertion_ids": ["assertion-1"],
                }
            ],
            "state_markers": [
                {
                    "marker_id": "marker-1",
                    "timestamp": start + 3600,
                    "kind": "shift",
                    "label": "Stress rose",
                    "summary": "Pressure increased around midday.",
                    "source_band_ids": ["band-1"],
                    "source_summary_ids": ["summary-1"],
                }
            ],
            "clusters": [],
            "reflections": [],
            "raw_events": [],
        }
        if scale == "month":
            payload["reflections"] = [
                {
                    "reflection_id": "reflection-1",
                    "time_start": start,
                    "time_end": end,
                    "title": "Month reflection",
                    "summary": "A sustained month of focused work and recovery.",
                    "key_topics": ["work", "recovery"],
                    "key_entities": ["project:magi"],
                    "sentiment_summary": {"tone": "steady"},
                    "change_and_pattern": {"patterns": ["late-night work"]},
                    "source_summary_ids": ["summary-1"],
                    "source_event_ids": ["event-1", "event-2"],
                }
            ]
        elif scale in {"week", "day"}:
            payload["clusters"] = [
                {
                    "block_id": "cluster-1",
                    "time_start": start,
                    "time_end": min(end, start + 7200),
                    "duration_seconds": min(end - start, 7200),
                    "label": "Deep work",
                    "summary": "A long focused stretch across coding and note-taking.",
                    "dominant_mode": "deep_work",
                    "source_types": ["chat", "manual_journal"],
                    "event_count": 3,
                    "representative_event_ids": ["event-1", "event-2"],
                    "keywords": ["coding", "notes"],
                    "media_refs": [],
                    "state_snapshot": {
                        "valence": 0.32,
                        "stress_level": 0.61,
                        "engagement": 0.83,
                    },
                }
            ]
        elif scale == "hour":
            payload["raw_events"] = [
                {
                    "event_id": "event-1",
                    "timestamp": start + 300,
                    "title": "Opened design note",
                    "summary": "Reviewing implementation notes.",
                    "source_type": "manual_journal",
                }
            ]
        return payload

    async def get_context_bundle(self, anchor_id):
        self.context_calls.append(anchor_id)
        return {
            "anchor": {
                "anchor_id": anchor_id,
                "anchor_type": "cluster",
                "title": "Deep work",
                "summary": "A long focused stretch across coding and note-taking.",
            },
            "l1_events": [
                {
                    "event_id": "event-1",
                    "title": "Opened design note",
                    "summary": "Reviewing implementation notes.",
                    "source_type": "manual_journal",
                }
            ],
            "l2_state_evidence": [
                {
                    "assertion_id": "assertion-1",
                    "trait_name": "mood",
                    "trait_value": "focused",
                    "confidence_score": 0.74,
                }
            ],
            "l3_reflections": [
                {
                    "summary_id": "summary-1",
                    "summary_category": "day",
                    "content": "Focus remained high despite rising stress.",
                }
            ],
            "l4_related_procedures": [
                {
                    "skill_id": "skill-1",
                    "skill_name": "Deep work loop",
                    "success_rate": 0.81,
                }
            ],
            "chat_excerpts": [
                {
                    "event_id": "event-2",
                    "content": "Let's restructure the timeline around semantic zoom.",
                }
            ],
            "runtime_trace": [],
        }

    async def set_cover_preference(
        self, *, scale, start, end, mode, asset_ref=None, source="current_period", locale="en"
    ):
        self.cover_calls.append(
            {
                "scale": scale,
                "start": start,
                "end": end,
                "mode": mode,
                "asset_ref": asset_ref,
                "source": source,
                "locale": locale,
            }
        )
        return {
            "mode": mode,
            "asset_ref": asset_ref if mode == "asset" else None,
            "source": source if mode == "asset" else mode,
            "candidates": [
                {
                    "asset_ref": "photo-library://asset-a",
                    "source": "current_period",
                    "label": "Photo walk",
                }
            ],
        }


def _build_client(monkeypatch):
    app = FastAPI()
    app.include_router(timeline_router, prefix="/api/timeline")
    service = _FakeTimelineService()
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: service)
    return TestClient(app), service


def test_get_timeline_viewport_returns_month_reflections(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.get(
        "/api/timeline/viewport",
        params={
            "scale": "month",
            "start": 1710000000,
            "end": 1712592000,
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["viewport"]["scale"] == "month"
    assert body["reflections"][0]["reflection_id"] == "reflection-1"
    assert body["state_bands"][0]["band_id"] == "band-1"
    assert service.viewport_calls[0]["scale"] == "month"
    assert service.viewport_calls[0]["timezone"] == "Asia/Shanghai"
    assert service.viewport_calls[0]["locale"] == "zh-CN"


def test_get_timeline_viewport_returns_day_clusters(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.get(
        "/api/timeline/viewport",
        params={"scale": "day", "start": 1710000000, "end": 1710086400, "query": "focused coding"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["viewport"]["scale"] == "day"
    assert body["clusters"][0]["block_id"] == "cluster-1"
    assert body["clusters"][0]["dominant_mode"] == "deep_work"
    assert service.viewport_calls[0]["query"] == "focused coding"


def test_get_timeline_viewport_returns_hour_raw_events(monkeypatch):
    client, _ = _build_client(monkeypatch)

    response = client.get(
        "/api/timeline/viewport",
        params={"scale": "hour", "start": 1710000000, "end": 1710003600},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["viewport"]["scale"] == "hour"
    assert body["raw_events"][0]["event_id"] == "event-1"
    assert body["clusters"] == []


def test_get_timeline_context_bundle_returns_cross_layer_sections(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.get("/api/timeline/context/cluster-1")

    assert response.status_code == 200
    body = response.json()
    assert body["anchor"]["anchor_id"] == "cluster-1"
    assert body["l1_events"][0]["event_id"] == "event-1"
    assert body["l2_state_evidence"][0]["assertion_id"] == "assertion-1"
    assert body["l3_reflections"][0]["summary_id"] == "summary-1"
    assert body["l4_related_procedures"][0]["skill_id"] == "skill-1"
    assert service.context_calls == ["cluster-1"]


def test_set_timeline_cover_preference(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.post(
        "/api/timeline/cover",
        json={
            "scale": "day",
            "start": 1710000000,
            "end": 1710086400,
            "mode": "asset",
            "asset_ref": "photo-library://asset-a",
            "source": "current_period",
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "asset"
    assert body["asset_ref"] == "photo-library://asset-a"
    assert service.cover_calls == [
        {
            "scale": "day",
            "start": 1710000000.0,
            "end": 1710086400.0,
            "mode": "asset",
            "asset_ref": "photo-library://asset-a",
            "source": "current_period",
            "locale": "zh-CN",
        }
    ]


def test_set_timeline_cover_rejects_unknown_source(monkeypatch):
    client, service = _build_client(monkeypatch)

    response = client.post(
        "/api/timeline/cover",
        json={
            "scale": "day",
            "start": 1710000000,
            "end": 1710086400,
            "mode": "asset",
            "asset_ref": "manual-entry-asset:///tmp/private.jpg",
            "source": "untrusted",
        },
    )

    assert response.status_code == 422
    assert service.cover_calls == []
