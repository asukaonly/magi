import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import timeline as timeline_module
from magi.api.routers.timeline import timeline_router


class _FakeTimelineService:
    def __init__(self):
        self.viewport_calls = []
        self.context_calls = []
        self.cover_calls = []

    async def get_viewport(self, **kwargs):
        self.viewport_calls.append(kwargs)
        return {
            "viewport": kwargs,
            "raw_events": [{"event_id": "event-canary"}],
            "clusters": [],
            "reflections": [],
            "state_bands": [],
        }

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
    app.include_router(_build_public_router(timeline_router, _PUBLIC_ROUTE_METHODS["timeline"]), prefix="/api/timeline")
    service = _FakeTimelineService()
    monkeypatch.setattr(timeline_module, "get_timeline_service", lambda: service)
    return TestClient(app), service


@pytest.mark.parametrize("scale", ["month", "week", "day", "hour"])
@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "query": "focused coding",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
            "focus": "self",
        },
    ],
)
def test_viewport_http_forwards_parameters_and_preserves_service_payload(
    monkeypatch, scale, overrides
):
    client, service = _build_client(monkeypatch)
    params = {"scale": scale, "start": 1710000000, "end": 1712592000, **overrides}
    response = client.get("/api/timeline/viewport", params=params)
    expected = {
        "scale": scale,
        "start": 1710000000.0,
        "end": 1712592000.0,
        "query": None,
        "timezone": None,
        "locale": "en",
        "focus": "self",
        **overrides,
    }
    assert response.status_code == 200
    assert service.viewport_calls == [expected]
    assert response.json() == {
        "viewport": expected,
        "raw_events": [{"event_id": "event-canary"}],
        "clusters": [],
        "reflections": [],
        "state_bands": [],
    }


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
