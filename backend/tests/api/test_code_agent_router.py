"""Integration tests for /api/code_agent endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.code_agent import code_agent_router


@pytest.fixture
def isolated_magi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "magi_home"
    home.mkdir()
    monkeypatch.setenv("MAGI_HOME", str(home))
    return home


@pytest.fixture
def client(isolated_magi_home: Path) -> TestClient:
    app = FastAPI()
    app.include_router(code_agent_router, prefix="/api/code_agent")
    return TestClient(app)


def test_probe_endpoint_returns_both_adapters(client: TestClient) -> None:
    res = client.get("/api/code_agent/probe", params={"force": True})
    assert res.status_code == 200
    body = res.json()
    assert set(body["results"].keys()) == {"claude_code", "codex"}


def test_rescan_endpoint(client: TestClient) -> None:
    res = client.post("/api/code_agent/rescan")
    assert res.status_code == 200
    body = res.json()
    assert "results" in body


def test_get_settings_returns_defaults(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.get("/api/code_agent/settings", params={"workspace": str(workspace)})
    assert res.status_code == 200
    settings = res.json()["settings"]
    assert settings["default_adapter"] == "claude_code"
    assert settings["enabled"] is True


def test_patch_user_settings(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.patch(
        "/api/code_agent/settings",
        json={
            "level": "user",
            "patch": {"default_adapter": "codex"},
            "workspace": str(workspace),
        },
    )
    assert res.status_code == 200
    assert res.json()["settings"]["default_adapter"] == "codex"

    res2 = client.get("/api/code_agent/settings", params={"workspace": str(workspace)})
    assert res2.json()["settings"]["default_adapter"] == "codex"


def test_patch_project_settings_requires_workspace(client: TestClient) -> None:
    res = client.patch(
        "/api/code_agent/settings",
        json={"level": "project", "patch": {"default_adapter": "codex"}, "workspace": None},
    )
    assert res.status_code == 400


def test_patch_project_settings_creates_project_toml(
    client: TestClient, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.patch(
        "/api/code_agent/settings",
        json={
            "level": "project",
            "patch": {"default_adapter": "codex"},
            "workspace": str(workspace),
        },
    )
    assert res.status_code == 200
    project_toml = workspace / ".magi" / "code_agent.toml"
    assert project_toml.is_file()


def test_reset_project_settings_endpoint(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    client.patch(
        "/api/code_agent/settings",
        json={
            "level": "project",
            "patch": {"default_adapter": "codex"},
            "workspace": str(workspace),
        },
    )
    res = client.post(
        "/api/code_agent/settings/reset",
        json={"level": "project", "workspace": str(workspace)},
    )
    assert res.status_code == 200
    assert not (workspace / ".magi" / "code_agent.toml").is_file()


def test_reset_user_level_is_rejected(client: TestClient) -> None:
    res = client.post(
        "/api/code_agent/settings/reset",
        json={"level": "user", "workspace": None},
    )
    # pydantic Literal rejects this -> 422
    assert res.status_code in {400, 422}


def test_patch_invalid_level_rejected(client: TestClient) -> None:
    res = client.patch(
        "/api/code_agent/settings",
        json={"level": "elsewhere", "patch": {}, "workspace": None},
    )
    assert res.status_code in {400, 422}


def test_patch_invalid_payload_rejected(client: TestClient) -> None:
    res = client.patch(
        "/api/code_agent/settings",
        json={"level": "user", "patch": "not-a-dict", "workspace": None},
    )
    assert res.status_code in {400, 422}
