"""HTTP API contract tests for /api/system-suggestions."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.system_suggestions_routes import (
    build_default_system_suggestions_router,
)


@pytest.fixture
def app_with_suggestions(make_manifest_fixture):
    chrome = make_manifest_fixture(
        "chrome-history",
        category="browser_history",
        keywords={"zh": ["浏览"], "en": ["browsing"]},
    )
    manifests = {"chrome-history": chrome}

    dismissals: dict = {}

    def list_manifests():
        return list(manifests.values())

    def is_available(plugin_id: str) -> bool:
        return plugin_id in manifests

    def is_dismissed(dedupe_key: str) -> bool:
        return dedupe_key in dismissals

    def record_dismissal(dedupe_key: str, kind: str) -> None:
        dismissals[dedupe_key] = kind

    async def fake_classify(recent_text, candidates, locale):
        # High confidence for every gated candidate so build_proposals keeps it.
        return {c["category"]: 0.9 for c in candidates}

    app = FastAPI()
    app.include_router(
        build_default_system_suggestions_router(
            list_manifests_dep=lambda: list_manifests,
            is_available_dep=lambda: is_available,
            is_dismissed_dep=lambda: is_dismissed,
            record_dismissal_dep=lambda: record_dismissal,
            classify_dep=lambda: fake_classify,
        ),
    )
    return app, dismissals


def test_post_check_returns_suggestion_for_matching_text(app_with_suggestions) -> None:
    app, _ = app_with_suggestions
    client = TestClient(app)
    response = client.post(
        "/system-suggestions/check",
        json={"text": "我看了什么浏览", "locale": "zh", "session_id": "s-match"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["category"] == "browser_history"
    # Confidence now comes from the (fake) LLM classifier, not keyword hits.
    assert data["suggestions"][0]["confidence"] == 0.9


def test_post_check_returns_empty_for_no_match(app_with_suggestions) -> None:
    app, _ = app_with_suggestions
    client = TestClient(app)
    response = client.post(
        "/system-suggestions/check",
        json={"text": "random unrelated", "locale": "zh", "session_id": "s-nomatch"},
    )
    assert response.status_code == 200
    assert response.json() == {"suggestions": []}


def test_post_check_rejects_empty_text(app_with_suggestions) -> None:
    app, _ = app_with_suggestions
    client = TestClient(app)
    response = client.post(
        "/system-suggestions/check",
        json={"text": "", "locale": "zh"},
    )
    assert response.status_code == 422


def test_post_dismiss_records_and_persists(app_with_suggestions) -> None:
    app, dismissals = app_with_suggestions
    client = TestClient(app)
    response = client.post(
        "/system-suggestions/dismiss",
        json={"dedupe_key": "browser_history", "kind": "explicit"},
    )
    assert response.status_code == 200
    assert response.json() == {"dedupe_key": "browser_history", "dismissed": True}
    assert "browser_history" in dismissals


def test_post_dismiss_rejects_unknown_kind(app_with_suggestions) -> None:
    app, _ = app_with_suggestions
    client = TestClient(app)
    response = client.post(
        "/system-suggestions/dismiss",
        json={"dedupe_key": "browser_history", "kind": "weird"},
    )
    assert response.status_code == 422


def test_post_check_filters_dismissed_after_dismiss(app_with_suggestions) -> None:
    app, _ = app_with_suggestions
    client = TestClient(app)
    response = client.post(
        "/system-suggestions/check",
        json={"text": "我看了什么浏览", "locale": "zh", "session_id": "s-dismiss"},
    )
    assert len(response.json()["suggestions"]) == 1
    client.post(
        "/system-suggestions/dismiss",
        json={"dedupe_key": "browser_history", "kind": "explicit"},
    )
    # After dismissal the keyword gate yields no candidates, so the engine
    # short-circuits before the throttle cache is consulted.
    response = client.post(
        "/system-suggestions/check",
        json={"text": "我看了什么浏览", "locale": "zh", "session_id": "s-dismiss"},
    )
    assert response.json() == {"suggestions": []}
