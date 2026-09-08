"""Exercise filesystem selection through the product route allowlist."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.files import files_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(_build_public_router(files_router, _PUBLIC_ROUTE_METHODS["files"]), prefix="/api/files")
    return TestClient(app)


def test_public_browse_paginates_center_paths_and_filters_directories(client, tmp_path):
    for name in ("b", "a", "c"):
        (tmp_path / name).mkdir()
    (tmp_path / "notes.md").write_text("private content must not be returned")
    (tmp_path / ".hidden").mkdir()
    first = client.get("/api/files/browse", params={"path": str(tmp_path), "limit": 2})
    assert first.status_code == 200
    assert [entry["name"] for entry in first.json()["entries"]] == ["a", "b"]
    second = client.get("/api/files/browse", params={"path": str(tmp_path), "after": first.json()["next_after"], "limit": 2})
    assert [entry["name"] for entry in second.json()["entries"]] == ["c", "notes.md"]
    assert "private content" not in second.text
    directories = client.get("/api/files/browse", params={"path": str(tmp_path), "directories_only": True, "show_hidden": True})
    assert all(entry["kind"] == "directory" for entry in directories.json()["entries"])
    assert directories.json()["entries"][0]["name"] == ".hidden"


def test_directory_creation_is_idempotent_and_cannot_escape_parent(client, tmp_path):
    payload = {"parent": str(tmp_path), "name": "My folder"}
    for _ in range(2):
        response = client.post("/api/files/directories", json=payload)
        assert response.status_code == 200
        assert response.json()["path"] == str(tmp_path / "My folder")
    for name in ("..", "../escape", "a/b", "a\\b"):
        assert client.post("/api/files/directories", json={**payload, "name": name}).status_code == 400


def test_invalid_or_missing_paths_are_not_silently_replaced_with_client_paths(client, tmp_path):
    assert client.get("/api/files/browse", params={"path": "relative"}).status_code == 400
    assert client.get("/api/files/browse", params={"path": str(tmp_path / "missing")}).status_code == 404
    assert client.get("/api/files/browse", params={"path": str(tmp_path), "limit": 1000}).status_code == 422


def test_file_selection_resolves_on_center_and_creation_rejects_symlinks(client, tmp_path):
    target = tmp_path / "model.bin"
    target.write_bytes(b"model")
    response = client.get("/api/files/browse", params={"path": str(target), "resolve_file": True})
    assert response.status_code == 200
    assert response.json()["selected_file"] == str(target)
    assert response.json()["path"] == str(tmp_path)
    (tmp_path / "linked").symlink_to(tmp_path, target_is_directory=True)
    assert client.post("/api/files/directories", json={"parent": str(tmp_path), "name": "linked"}).status_code == 400
