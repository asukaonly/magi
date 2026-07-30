from __future__ import annotations

import hashlib
import io
from pathlib import Path
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import plugins_install_routes
from magi.api.routers.plugins import plugins_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.config.models import AppConfig
from magi.plugins.install_candidates import PluginInstallCandidateStore
from magi.plugins.manager import PluginManager


def _archive_bytes(
    *,
    plugin_id: str = "demo-plugin",
    kind: str = "plugin",
    with_icon: bool = False,
) -> bytes:
    icon_line = 'icon = "asset:assets/icon.png"\n' if with_icon else ""
    manifest = (
        "[plugin]\n"
        f'id = "{plugin_id}"\n'
        'name = "Demo Plugin"\n'
        'version = "1.0.0"\n'
        'entry_module = "plugin"\n'
        'entry_class = "DemoPlugin"\n'
        f'kind = "{kind}"\n'
        f"{icon_line}"
        "\n"
        "[[plugin.permissions.capabilities]]\n"
        'capability = "network"\n'
        'scope = ["example.com"]\n'
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("demo/plugin.toml", manifest)
        bundle.writestr("demo/plugin.py", "class DemoPlugin:\n    pass\n")
        if with_icon:
            bundle.writestr("demo/assets/icon.png", b"\x89PNG\r\n\x1a\n")
    return archive.getvalue()


def _client(
    monkeypatch,
    tmp_path: Path,
    *,
    installed_plugin_id: str | None = None,
) -> tuple[TestClient, PluginInstallCandidateStore]:
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    manager = PluginManager.__new__(PluginManager)
    manager._package_states = (
        {installed_plugin_id: object()} if installed_plugin_id is not None else {}
    )
    monkeypatch.setattr(
        plugins_install_routes,
        "get_plugin_install_candidate_store",
        lambda: store,
    )
    monkeypatch.setattr(plugins_install_routes, "get_config", lambda: AppConfig())
    monkeypatch.setattr(plugins_install_routes, "_require_plugin_manager", lambda: manager)
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    return TestClient(app), store


def test_candidate_upload_uses_server_owned_path_and_returns_digest(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"keep")
    archive = _archive_bytes()

    response = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("../../outside.zip", archive, "application/zip")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["archive_sha256"] == hashlib.sha256(archive).hexdigest()
    assert payload["manifest"]["plugin_id"] == "demo-plugin"
    assert payload["manifest"]["capabilities"][0]["capability"] == "network"
    candidate = store.get(payload["candidate_id"])
    assert candidate.original_filename == "outside.zip"
    assert candidate.archive_path.name == "archive.zip"
    assert candidate.archive_path.parent.parent == store.root_dir
    assert outside.read_bytes() == b"keep"


def test_candidate_upload_rejects_oversized_content_and_cleans_files(
    monkeypatch,
    tmp_path,
):
    client, store = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(plugins_install_routes, "MAX_PLUGIN_ARCHIVE_UPLOAD_BYTES", 4)

    response = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("demo.zip", b"12345", "application/zip")},
    )

    assert response.status_code == 413
    assert list(store.root_dir.iterdir()) == []


def test_candidate_upload_rejects_direct_library_package(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("library.zip", _archive_bytes(kind="library"), "application/zip")},
    )

    assert response.status_code == 400
    assert list(store.root_dir.iterdir()) == []


def test_candidate_upload_embeds_a_validated_package_icon(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("demo.zip", _archive_bytes(with_icon=True), "application/zip")},
    )

    assert response.status_code == 200
    assert response.json()["manifest"]["icon"].startswith("data:image/png;base64,")


def test_candidate_upload_cannot_replace_an_installed_plugin(monkeypatch, tmp_path):
    client, store = _client(
        monkeypatch,
        tmp_path,
        installed_plugin_id="demo-plugin",
    )

    response = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("demo.zip", _archive_bytes(), "application/zip")},
    )

    assert response.status_code == 409
    assert list(store.root_dir.iterdir()) == []


def test_candidate_upload_cannot_claim_a_host_reserved_plugin_id(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/plugins/install/candidates",
        files={
            "file": (
                "calendar.zip",
                _archive_bytes(plugin_id="calendar"),
                "application/zip",
            )
        },
    )

    assert response.status_code == 409
    assert list(store.root_dir.iterdir()) == []


def test_candidate_upload_returns_busy_when_candidate_limit_is_full(
    monkeypatch,
    tmp_path,
):
    client, store = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "_max_candidates", 1)
    store.reserve_archive(".zip")

    response = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("demo.zip", _archive_bytes(), "application/zip")},
    )

    assert response.status_code == 429


def test_candidate_can_be_discarded_once(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/plugins/install/candidates",
        files={"file": ("demo.zip", _archive_bytes(), "application/zip")},
    ).json()

    first = client.delete(f"/api/plugins/install/candidates/{created['candidate_id']}")
    second = client.delete(f"/api/plugins/install/candidates/{created['candidate_id']}")

    assert first.status_code == 200
    assert second.status_code == 404


def test_candidate_approval_binds_id_and_digest(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)
    captured: dict[str, str] = {}

    class _FakeJobs:
        def start_candidate_install(self, candidate_id: str, *, expected_sha256: str):
            captured.update(
                candidate_id=candidate_id,
                expected_sha256=expected_sha256,
            )
            return {
                "job_id": "job-1",
                "operation": "upload",
                "plugin_id": "demo-plugin",
                "filename": "demo.zip",
                "status": "queued",
                "stage": "queued",
                "progress_pct": 0,
                "message": "Queued plugin installation",
                "logs": [],
                "created_at_ms": 1,
                "updated_at_ms": 1,
            }

    monkeypatch.setattr(plugins_install_routes, "plugin_install_jobs", _FakeJobs())
    digest = "a" * 64

    response = client.post(
        "/api/plugins/install/candidates/candidate-1/jobs",
        json={"expected_sha256": digest},
    )

    assert response.status_code == 200
    assert captured == {
        "candidate_id": "candidate-1",
        "expected_sha256": digest,
    }


def test_public_router_only_exposes_candidate_upload_flow():
    public = _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"])
    paths = {route.path for route in public.routes}

    assert "/install/candidates" in paths
    assert "/install/candidates/{candidate_id}" in paths
    assert "/install/candidates/{candidate_id}/jobs" in paths
    assert "/install/upload" not in paths
    assert "/install/upload/inspect" not in paths
    assert "/install/upload/jobs" not in paths
