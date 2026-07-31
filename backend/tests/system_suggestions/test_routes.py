"""HTTP API contract tests for /api/system-suggestions."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.system_suggestions_routes import (
    _default_availability,
    _default_candidates,
    build_default_system_suggestions_router,
)
from magi.system_suggestions.candidates import (
    CandidateResolution,
    build_suggestion_candidates,
)


def _resolution(candidates, *, catalog_mode="full"):
    return CandidateResolution(
        candidates=list(candidates),
        catalog_mode=catalog_mode,
    )


def _availability_factory(available_ids: set[str]):
    """Build an availability_dep whose adapter is True for ``available_ids``.

    Mirrors the production shape: ``() -> (candidates) -> (plugin_id) -> bool``.
    """

    def _dep():
        def _factory(candidates):
            def _is_available(plugin_id: str) -> bool:
                return plugin_id in available_ids

            return _is_available

        return _factory

    return _dep


@pytest.fixture
def app_with_suggestions(make_manifest_fixture):
    chrome = make_manifest_fixture(
        "chrome-history",
        category="browser_history",
        keywords={"zh": ["浏览"], "en": ["browsing"]},
    )
    candidates = build_suggestion_candidates([chrome], [])

    dismissals: dict = {}

    def is_dismissed(dedupe_key: str) -> bool:
        return dedupe_key in dismissals

    def record_dismissal(dedupe_key: str, kind: str, title: str | None = None) -> None:
        dismissals[dedupe_key] = (kind, title)

    async def fake_classify(recent_text, candidates, locale):
        # High confidence for every gated candidate so build_proposals keeps it.
        return {c["category"]: 0.9 for c in candidates}

    app = FastAPI()
    app.include_router(
        build_default_system_suggestions_router(
            candidates_dep=lambda: (lambda: _resolution(candidates)),
            availability_dep=_availability_factory({"chrome-history"}),
            is_dismissed_dep=lambda: is_dismissed,
            record_dismissal_dep=lambda: record_dismissal,
            list_dismissals_dep=lambda: (lambda: []),
            clear_dismissal_dep=lambda: (lambda _k: True),
            classify_dep=lambda: fake_classify,
        ),
    )
    return app, dismissals


@pytest.fixture
def app_with_dismissals():
    """App fixture with canned dismissal listing + a clear recorder."""
    from datetime import datetime, timezone

    from magi.api.routers.system_suggestions_schemas import DismissalItem

    canned = [
        DismissalItem(
            dedupe_key="browser_history",
            dismissed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            kind="explicit",
        ),
    ]
    cleared_keys: list[str] = []

    def list_dismissals():
        return list(canned)

    def clear_dismissal(dedupe_key: str) -> bool:
        cleared_keys.append(dedupe_key)
        return dedupe_key == "browser_history"

    async def fake_classify(recent_text, candidates, locale):
        return {c["category"]: 0.9 for c in candidates}

    app = FastAPI()
    app.include_router(
        build_default_system_suggestions_router(
            candidates_dep=lambda: (lambda: _resolution([])),
            availability_dep=lambda: (lambda _candidates: (lambda _p: True)),
            is_dismissed_dep=lambda: (lambda _k: False),
            record_dismissal_dep=lambda: (lambda _k, _kind, _title=None: None),
            list_dismissals_dep=lambda: list_dismissals,
            clear_dismissal_dep=lambda: clear_dismissal,
            classify_dep=lambda: fake_classify,
        ),
    )
    return app, cleared_keys


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
        json={
            "dedupe_key": "browser_history",
            "kind": "explicit",
            "title": "看看你的浏览器历史",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"dedupe_key": "browser_history", "dismissed": True}
    # The route forwards the localized title to the recorder as the 3rd arg.
    assert dismissals["browser_history"] == ("explicit", "看看你的浏览器历史")


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


@pytest.fixture
def app_with_installable():
    """App whose only candidate is a not-installed (registry) plugin.

    The candidate carries ``installed=False`` so the engine must preserve its
    display metadata and install state on the returned proposal.
    """
    from magi_plugin_sdk.contracts import (
        LocalizedText,
        PluginRegistryEntry,
        SuggestionDescriptor,
        Triggers,
    )

    entry = PluginRegistryEntry(
        plugin_id="spotify-history",
        name="spotify-history",
        version="0.1.0",
        package_sha256="a" * 64,
        suggestion_descriptor=SuggestionDescriptor(
            category="music_history",
            triggers=Triggers(intents=[], entities=[], keywords={"zh": ["音乐"], "en": ["music"]}),
            platform_support=["darwin", "win32", "linux"],
            local_requirements=[],
            rationale=LocalizedText(zh="连接 Spotify", en="connect Spotify"),
        ),
    )
    # installed=[], registry=[entry] -> single candidate with installed=False.
    candidates = build_suggestion_candidates([], [entry])

    async def fake_classify(recent_text, cands, locale):
        return {c["category"]: 0.9 for c in cands}

    app = FastAPI()
    app.include_router(
        build_default_system_suggestions_router(
            candidates_dep=lambda: (lambda: _resolution(candidates)),
            # Registry-only candidate is available on this device.
            availability_dep=_availability_factory({"spotify-history"}),
            is_dismissed_dep=lambda: (lambda _k: False),
            record_dismissal_dep=lambda: (lambda _k, _kind, _title=None: None),
            list_dismissals_dep=lambda: (lambda: []),
            clear_dismissal_dep=lambda: (lambda _k: True),
            classify_dep=lambda: fake_classify,
        ),
    )
    return app


def test_post_check_surfaces_installable_for_not_installed_candidate(
    app_with_installable,
) -> None:
    client = TestClient(app_with_installable)
    response = client.post(
        "/system-suggestions/check",
        json={"text": "我想听音乐", "locale": "zh", "session_id": "s-installable"},
    )
    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert len(suggestions) == 1
    proposal = suggestions[0]
    assert proposal["category"] == "music_history"
    assert proposal["confidence"] == 0.9
    assert proposal["plugins"] == [
        {
            "plugin_id": "spotify-history",
            "name": "spotify-history",
            "name_i18n": {},
            "icon": "",
            "installed": False,
        }
    ]


@pytest.fixture
def app_with_installable_endpoint():
    """App for GET /system-suggestions/installable.

    Two candidates — one installed, one registry-only (not installed). The
    injected ``availability_dep`` marks the installed one available and the
    not-installed one unavailable, so the endpoint must return ONLY the
    available candidate with its ``installed`` flag + ``category``.
    """
    from types import SimpleNamespace
    from magi_plugin_sdk.contracts import SuggestionSurfaceSpec, SuggestionSurfacesSpec

    surfaces = SuggestionSurfacesSpec(
        empty_state=SuggestionSurfaceSpec(order=10),
    )

    installed_cand = SimpleNamespace(
        plugin_id="chrome-history",
        name="Chrome History",
        name_i18n={"zh-CN": "Chrome 浏览器历史"},
        description="Local Chrome history",
        description_i18n={"zh-CN": "本地 Chrome 历史"},
        icon="brand:googlechrome",
        descriptor=SimpleNamespace(
            category="browser_history",
            rationale=SimpleNamespace(zh="浏览器历史", en="browsing history"),
            setup_time_estimate_seconds=10,
            data_locality="local_only",
            surfaces=surfaces,
        ),
        installed=True,
    )
    registry_cand = SimpleNamespace(
        plugin_id="spotify-history",
        name="Spotify History",
        name_i18n={},
        description="Spotify history",
        description_i18n={},
        icon="brand:spotify",
        descriptor=SimpleNamespace(
            category="music_history",
            rationale=SimpleNamespace(zh="音乐历史", en="music history"),
            setup_time_estimate_seconds=20,
            data_locality="uploads",
            surfaces=surfaces,
        ),
        installed=False,
    )
    candidates = [installed_cand, registry_cand]

    async def fake_classify(recent_text, cands, locale):
        return {c["category"]: 0.9 for c in cands}

    app = FastAPI()
    app.include_router(
        build_default_system_suggestions_router(
            candidates_dep=lambda: (lambda: _resolution(candidates)),
            # Only the installed candidate is available on this device.
            availability_dep=_availability_factory({"chrome-history"}),
            is_dismissed_dep=lambda: (lambda _k: False),
            record_dismissal_dep=lambda: (lambda _k, _kind, _title=None: None),
            list_dismissals_dep=lambda: (lambda: []),
            clear_dismissal_dep=lambda: (lambda _k: True),
            classify_dep=lambda: fake_classify,
        ),
    )
    return app


def test_list_installable_returns_only_available(
    app_with_installable_endpoint,
) -> None:
    client = TestClient(app_with_installable_endpoint)
    response = client.get("/system-suggestions/installable")
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_mode"] == "full"
    items = payload["items"]
    # Only the available (installed) candidate is surfaced.
    assert len(items) == 1
    item = items[0]
    assert item["plugin_id"] == "chrome-history"
    assert item["name_i18n"] == {"zh-CN": "Chrome 浏览器历史"}
    assert item["icon"] == "brand:googlechrome"
    assert item["category"] == "browser_history"
    assert item["installed"] is True
    assert item["rationale"] == {"zh": "浏览器历史", "en": "browsing history"}
    assert item["setup_time_estimate_seconds"] == 10
    assert item["data_locality"] == "local_only"
    assert item["surfaces"]["empty_state"]["order"] == 10


def test_list_installable_reports_installed_only_catalog() -> None:
    async def fake_classify(recent_text, cands, locale):
        return {}

    app = FastAPI()
    app.include_router(
        build_default_system_suggestions_router(
            candidates_dep=lambda: lambda: _resolution([], catalog_mode="installed_only"),
            availability_dep=lambda: lambda _candidates: lambda _p: True,
            is_dismissed_dep=lambda: lambda _k: False,
            record_dismissal_dep=lambda: lambda _k, _kind, _title=None: None,
            list_dismissals_dep=lambda: lambda: [],
            clear_dismissal_dep=lambda: lambda _k: True,
            classify_dep=lambda: fake_classify,
        ),
    )

    response = TestClient(app).get("/system-suggestions/installable")

    assert response.status_code == 200
    assert response.json() == {"items": [], "catalog_mode": "installed_only"}


@pytest.mark.asyncio
async def test_default_candidates_degrades_when_registry_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.api.routers import plugins_common, system_suggestions_routes

    class UnreachableRegistry:
        async def fetch_snapshot(self):
            raise OSError("offline")

    async def no_active_sources() -> set[str]:
        return set()

    monkeypatch.setattr(plugins_common, "_try_plugin_manager", lambda: None)
    monkeypatch.setattr(
        plugins_common,
        "_get_registry_client",
        lambda: UnreachableRegistry(),
    )
    monkeypatch.setattr(
        system_suggestions_routes,
        "_active_sensor_plugin_ids",
        no_active_sources,
    )

    resolution = await _default_candidates()()

    assert resolution.catalog_mode == "installed_only"
    assert resolution.candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("official_source", [True, False])
async def test_default_candidates_carries_registry_source_authority(
    monkeypatch: pytest.MonkeyPatch,
    official_source: bool,
) -> None:
    from types import SimpleNamespace

    from magi.api.routers import plugins_common, system_suggestions_routes
    from magi_plugin_sdk.contracts import (
        LocalizedText,
        PluginRegistryEntry,
        SuggestionDescriptor,
        Triggers,
    )

    entry = PluginRegistryEntry(
        plugin_id="registry-candidate",
        name="Registry Candidate",
        version="1.0.0",
        package_sha256="a" * 64,
        suggestion_descriptor=SuggestionDescriptor(
            category="test",
            triggers=Triggers(),
            platform_support=["darwin", "win32", "linux"],
            rationale=LocalizedText(zh="测试", en="Test"),
        ),
    )

    class Registry:
        async def fetch_snapshot(self):
            return SimpleNamespace(
                index=SimpleNamespace(plugins=[entry]),
                official_source=official_source,
            )

    async def no_active_sources() -> set[str]:
        return set()

    monkeypatch.setattr(plugins_common, "_try_plugin_manager", lambda: None)
    monkeypatch.setattr(plugins_common, "_get_registry_client", lambda: Registry())
    monkeypatch.setattr(
        system_suggestions_routes,
        "_active_sensor_plugin_ids",
        no_active_sources,
    )

    resolution = await _default_candidates()()

    assert len(resolution.candidates) == 1
    assert resolution.candidates[0].official_source is official_source


def test_custom_registry_candidate_never_executes_local_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.api.routers import availability_routes
    from magi_plugin_sdk.contracts import (
        LocalRequirementFileExists,
        LocalizedText,
        PluginRegistryEntry,
        SuggestionDescriptor,
        Triggers,
    )

    entry = PluginRegistryEntry(
        plugin_id="custom-registry-candidate",
        name="Custom Candidate",
        version="1.0.0",
        package_sha256="a" * 64,
        suggestion_descriptor=SuggestionDescriptor(
            category="test",
            triggers=Triggers(),
            platform_support=["darwin", "win32", "linux"],
            local_requirements=[
                LocalRequirementFileExists(
                    paths_per_platform={
                        "darwin": "/private/secret",
                        "win32": r"\\attacker.example\share",
                        "linux": "/private/secret",
                    }
                )
            ],
            rationale=LocalizedText(zh="测试", en="Test"),
        ),
    )
    [candidate] = build_suggestion_candidates(
        [],
        [entry],
        registry_official_source=False,
    )

    monkeypatch.setattr(
        availability_routes,
        "_get_or_create_resolver",
        lambda: pytest.fail("custom registry candidate initialized availability resolver"),
    )

    is_available = _default_availability()([candidate])

    assert is_available(candidate.plugin_id) is False


def test_official_registry_candidate_may_execute_local_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from magi.api.routers import availability_routes

    candidate = SimpleNamespace(
        plugin_id="official-candidate",
        installed=False,
        official_source=True,
        descriptor=object(),
    )
    evaluated: list[str] = []

    class Resolver:
        def evaluate_descriptor(self, _descriptor, *, plugin_id):
            evaluated.append(plugin_id)
            return SimpleNamespace(available=True)

    monkeypatch.setattr(
        availability_routes,
        "_get_or_create_resolver",
        lambda: Resolver(),
    )

    is_available = _default_availability()([candidate])

    assert is_available(candidate.plugin_id) is True
    assert evaluated == ["official-candidate"]


def test_list_dismissals_returns_active(app_with_dismissals) -> None:
    app, _ = app_with_dismissals
    client = TestClient(app)
    response = client.get("/system-suggestions/dismissals")
    assert response.status_code == 200
    data = response.json()
    keys = [item["dedupe_key"] for item in data["dismissals"]]
    assert "browser_history" in keys
    item = data["dismissals"][0]
    assert item["kind"] == "explicit"
    assert item["dismissed_at"].startswith("2026-01-01")


def test_clear_dismissal_removes_one(app_with_dismissals) -> None:
    app, cleared_keys = app_with_dismissals
    client = TestClient(app)
    response = client.delete("/system-suggestions/dismissals/browser_history")
    assert response.status_code == 200
    assert response.json() == {"dedupe_key": "browser_history", "cleared": True}
    assert cleared_keys == ["browser_history"]


# ---------------------------------------------------------------------------
# _active_sensor_plugin_ids: maps get_sensor_source_status() -> in-use ids.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_sensor_plugin_ids_parses_status(monkeypatch) -> None:
    """enabled + not activation_required -> included (in use);
    enabled + activation_required -> excluded (not yet configured);
    disabled -> excluded.
    """
    import magi.api.routers.sensors as sensors_mod
    from magi.api.routers.system_suggestions_routes import _active_sensor_plugin_ids

    async def _fake_status():
        return {
            "sources": [
                # enabled + configured (no/cleared activation) -> in use
                {"plugin_id": "chrome-history", "enabled": True, "activation_required": False},
                # enabled but activation still required -> not yet configured
                {"plugin_id": "screen-time", "enabled": True, "activation_required": True},
                # disabled -> not in use
                {"plugin_id": "git-activity", "enabled": False, "activation_required": False},
                # malformed / missing plugin_id -> skipped
                {"enabled": True, "activation_required": False},
            ]
        }

    monkeypatch.setattr(sensors_mod, "get_sensor_source_status", _fake_status)

    active = await _active_sensor_plugin_ids()
    assert active == {"chrome-history"}


@pytest.mark.asyncio
async def test_active_sensor_plugin_ids_handles_list_and_errors(monkeypatch) -> None:
    """get_sensor_source_status may return ``[]`` (no plugin manager) or raise;
    both degrade to an empty set rather than crashing the suggestion path.
    """
    import magi.api.routers.sensors as sensors_mod
    from magi.api.routers.system_suggestions_routes import _active_sensor_plugin_ids

    async def _list_status():
        return []

    monkeypatch.setattr(sensors_mod, "get_sensor_source_status", _list_status)
    assert await _active_sensor_plugin_ids() == set()

    async def _boom():
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(sensors_mod, "get_sensor_source_status", _boom)
    assert await _active_sensor_plugin_ids() == set()
