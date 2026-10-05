"""HTTP API contract tests for /availability endpoints."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.availability import AvailabilityResolver
from magi.api.routers.availability_routes import (
    create_availability_router,
)
from magi_plugin_sdk.contracts import (
    LocalRequirementFileExists,
)


@pytest.fixture
def app_with_resolver(tmp_path: Path, make_manifest):
    target = tmp_path / "x"
    target.write_text("")
    manifests = {
        "good": make_manifest(
            "good",
            requirements=[
                LocalRequirementFileExists(
                    check_kind="file_exists",
                    paths_per_platform={
                        "darwin": str(target),
                        "win32": str(target),
                        "linux": str(target),
                    },
                )
            ],
        ),
        "bad": make_manifest(
            "bad",
            requirements=[
                LocalRequirementFileExists(
                    check_kind="file_exists",
                    paths_per_platform={
                        platform: str(tmp_path / "y") for platform in ("darwin", "win32", "linux")
                    },
                )
            ],
        ),
    }
    resolver = AvailabilityResolver(
        manifest_provider=lambda pid: manifests.get(pid),
        ttl=timedelta(seconds=60),
    )
    app = FastAPI()
    app.include_router(create_availability_router(lambda: resolver, lambda: list(manifests.keys())))
    return app, resolver


@pytest.mark.parametrize(
    "params,ids",
    [
        ({}, {"good", "bad"}),
        ({"plugin_ids": "good,bad"}, {"good", "bad"}),
        ({"plugin_ids": "bad"}, {"bad"}),
    ],
)
def test_availability_request_selects_exact_plugins(app_with_resolver, params, ids) -> None:
    app, _ = app_with_resolver
    client = TestClient(app)
    response = client.get("/availability", params=params)
    assert response.status_code == 200
    data = response.json()
    by_id = {entry["plugin_id"]: entry for entry in data["entries"]}
    assert set(by_id) == ids
    if "good" in ids:
        assert by_id["good"]["available"] is True
    assert by_id["bad"]["available"] is False
    assert by_id["bad"]["reason"] == "missing_file"


def test_refresh_all_reprobes_each_cached_plugin(app_with_resolver, tmp_path):
    app, _ = app_with_resolver
    client = TestClient(app)

    def states():
        response = client.get("/availability")
        assert response.status_code == 200
        return {row["plugin_id"]: row["available"] for row in response.json()["entries"]}

    assert states() == {"good": True, "bad": False}
    (tmp_path / "x").unlink()
    (tmp_path / "y").write_text("ready")
    assert states() == {"good": True, "bad": False}
    response = client.post("/availability/refresh", json={})
    assert response.status_code == 200
    assert response.json() == {"invalidated_plugin_ids": []}
    assert states() == {"good": False, "bad": True}


def test_full_path_manifest_to_http_response(tmp_path: Path) -> None:
    """End-to-end: a real plugin.toml parses, the resolver probes, the API serves."""
    import tomllib

    target = tmp_path / "history.db"
    target.write_text("")

    toml_text = f"""
[plugin]
id = "e2e-test"
name = "E2E Test"
version = "0.0.1"
entry_module = "plugin"
entry_class = "X"

[plugin.suggestion_descriptor]
category = "test"
platform_support = ["darwin", "win32", "linux"]
setup_time_estimate_seconds = 5

[plugin.suggestion_descriptor.triggers]
intents = ["test_intent"]

[plugin.suggestion_descriptor.rationale]
zh = "测试"
en = "test"

[[plugin.suggestion_descriptor.local_requirements]]
check_kind = "file_exists"

[plugin.suggestion_descriptor.local_requirements.paths_per_platform]
darwin = "{target}"
win32 = "{target}"
linux = "{target}"
"""
    from magi_plugin_sdk.contracts import PluginManifest

    raw = tomllib.loads(toml_text)
    manifest = PluginManifest.model_validate(raw["plugin"])
    manifests = {"e2e-test": manifest}

    resolver = AvailabilityResolver(manifest_provider=lambda pid: manifests.get(pid))
    app = FastAPI()
    app.include_router(
        create_availability_router(lambda: resolver, lambda: list(manifests.keys())),
    )
    client = TestClient(app)

    response = client.get("/availability", params={"plugin_ids": "e2e-test"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["entries"][0]["available"] is True
    assert payload["entries"][0]["reason"] == "available"

    # Delete the target file and refresh — should now be unavailable.
    target.unlink()
    assert client.get("/availability").json()["entries"][0]["available"] is True
    refreshed = client.post("/availability/refresh", json={"plugin_ids": ["e2e-test"]})
    assert refreshed.status_code == 200
    assert refreshed.json() == {"invalidated_plugin_ids": ["e2e-test"]}
    response = client.get("/availability", params={"plugin_ids": "e2e-test"})
    assert response.json()["entries"][0]["available"] is False
    assert response.json()["entries"][0]["reason"] == "missing_file"
