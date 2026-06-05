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
    assert settings["default_adapter"] == "auto"
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


# ---------------------------------------------------------------------------
# Delegation control endpoints
# ---------------------------------------------------------------------------

def _stage_delegation(workspace: Path, sid: str, did: str) -> Path:
    delegation_dir = workspace / ".magi" / "sessions" / sid / "delegations" / did
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "result.json").write_text(
        '{"delegation_id": "%s", "success": true}' % did
    )
    (delegation_dir / "events.jsonl").write_text(
        '{"kind": "status", "ts_ms": 1, "payload": {}}\n'
        '{"kind": "assistant_text", "ts_ms": 2, "payload": {"text": "hi"}}\n'
    )
    return delegation_dir


def test_get_delegation_returns_result_and_events_tail(
    client: TestClient, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    delegation_dir = _stage_delegation(workspace, "s1", "x" * 32)
    (delegation_dir / "changes.patch").write_text("--- a/x\n+++ b/x\n")
    res = client.get(
        f"/api/code_agent/delegations/s1/{'x' * 32}",
        params={"workspace": str(workspace)},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"]["delegation_id"] == "x" * 32
    assert len(body["events_tail"]) == 2
    assert "+++ b/x" in body["diff_text"]


def test_get_delegation_404_when_missing(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.get(
        f"/api/code_agent/delegations/s1/{'y' * 32}",
        params={"workspace": str(workspace)},
    )
    assert res.status_code == 404


def test_get_delegation_400_without_workspace(client: TestClient) -> None:
    res = client.get(f"/api/code_agent/delegations/s1/{'z' * 32}")
    assert res.status_code == 400


def test_post_cancel_unknown_delegation_returns_ok_false(
    client: TestClient, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.post(
        f"/api/code_agent/delegations/s1/{'a' * 32}/cancel",
        json={"workspace": str(workspace)},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": False}


def test_post_apply_missing_delegation_returns_outcome_with_error(
    client: TestClient, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.post(
        f"/api/code_agent/delegations/s1/{'b' * 32}/apply",
        json={"workspace": str(workspace)},
    )
    assert res.status_code == 200
    outcome = res.json()["outcome"]
    assert outcome["applied"] is False
    assert "not found" in (outcome["error"] or "").lower()


def test_post_discard_when_missing_is_ok(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    res = client.post(
        f"/api/code_agent/delegations/s1/{'c' * 32}/discard",
        json={"workspace": str(workspace)},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
