"""Transfer recovery, bounded storage and public API reachability."""
from hashlib import sha256
from uuid import uuid4
from types import SimpleNamespace
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.files import files_router
from magi.api.services import file_transfers as transfers

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(transfers, "get_runtime_paths", lambda: SimpleNamespace(runtime_dir=tmp_path))
    app = FastAPI()
    app.include_router(_build_public_router(files_router, _PUBLIC_ROUTE_METHODS["files"]), prefix="/api/files")
    return TestClient(app)


def spec(**values):
    return {"resource_id": str(uuid4()), "name": "notes.md", "source_name": "diary/notes.md", "last_modified_ms": 1600000000000,
            "size": 6, "purpose": "history", **values}


def chunk(client, resource_id, offset, body):
    return client.put(f"/api/files/uploads/{resource_id}", params={"offset": offset, "sha256": sha256(body).hexdigest()}, content=body)


def test_resumes_identical_chunks_but_rejects_conflicting_content(client, tmp_path):
    payload = spec()
    first = client.post("/api/files/uploads", json=payload)
    assert first.status_code == 200
    resource_id = first.json()["resource_id"]
    assert chunk(client, resource_id, 0, b"abc").json()["received"] == 3
    # An unacknowledged tail is discarded on the next valid chunk.
    staged = tmp_path / "file-transfers" / resource_id / "content" / "notes.md"
    with staged.open("ab") as output: output.write(b"crash tail")
    assert client.post("/api/files/uploads", json=payload).json()["received"] == 3
    assert chunk(client, resource_id, 0, b"abc").json()["received"] == 3
    assert chunk(client, resource_id, 0, b"xyz").status_code == 409
    assert chunk(client, resource_id, 4, b"ef").status_code == 409
    assert chunk(client, resource_id, 3, b"def").json()["received"] == 6
    assert staged.read_bytes() == b"abcdef"
    assert staged.stat().st_mtime == 1600000000
    if os.name != "nt": assert staged.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_resolves_only_complete_resources_of_the_expected_purpose(client):
    payload = spec()
    client.post("/api/files/uploads", json=payload)
    with pytest.raises(transfers.TransferError, match="resource_not_ready"):
        await transfers.resolve_uploaded_files([payload["resource_id"]], "history")
    chunk(client, payload["resource_id"], 0, b"abcdef")
    with pytest.raises(transfers.TransferError, match="resource_not_ready"):
        await transfers.resolve_uploaded_files([payload["resource_id"]], "restore")
    paths = await transfers.resolve_uploaded_files([payload["resource_id"]], "history")
    assert paths[0].read_bytes() == b"abcdef"
    assert await transfers.uploaded_source_names([payload["resource_id"]]) == {str(paths[0]): "diary/notes.md"}


def test_rejects_client_paths_oversized_chunks_and_reservation_overflow(client, monkeypatch):
    assert client.post("/api/files/uploads", json=spec(resource_id="/tmp/client-file")).status_code == 400
    assert client.post("/api/files/uploads", json=spec(name="../escape")).status_code == 400
    assert client.post("/api/files/uploads", json=spec(source_name="../escape")).status_code == 400
    payload = spec(size=2 * transfers.CHUNK_BYTES)
    assert client.post("/api/files/uploads", json=payload).status_code == 200
    assert chunk(client, payload["resource_id"], 0, b"x" * (transfers.CHUNK_BYTES + 1)).status_code == 413
    monkeypatch.setattr(transfers, "_MAX_TOTAL_BYTES", 2 * transfers.CHUNK_BYTES)
    assert client.post("/api/files/uploads", json=spec()).status_code == 413


@pytest.mark.asyncio
async def test_uploaded_markdown_retains_relative_names_and_stable_fingerprints(client):
    from magi.memory.history_imports.service import _parse_markdown_selection
    ids = []
    raw = b"Today I finished an important project."
    for source_name in ("diary/notes.md", "work/notes.md"):
        payload = spec(size=len(raw), source_name=source_name)
        client.post("/api/files/uploads", json=payload)
        chunk(client, payload["resource_id"], 0, raw)
        ids.append(payload["resource_id"])
    paths = [str(path) for path in await transfers.resolve_uploaded_files(ids, "history")]
    names = await transfers.uploaded_source_names(ids)
    parsed, fingerprints, _, _ = _parse_markdown_selection(paths, names)
    assert set(fingerprints) == {"diary/notes.md", "work/notes.md"}
    assert len({source.source_id for source in parsed}) == 2


@pytest.mark.asyncio
async def test_expired_reservations_are_reclaimed_and_clear_removes_staged_content(client, monkeypatch, tmp_path):
    payload = spec()
    client.post("/api/files/uploads", json=payload)
    state_path = tmp_path / "file-transfers" / payload["resource_id"] / "state.json"
    state = transfers.UploadState.model_validate_json(state_path.read_bytes())
    state.expires_at = 1
    state_path.write_text(state.model_dump_json())
    monkeypatch.setattr(transfers, "_MAX_RESOURCES", 1)
    replacement = spec()
    assert client.post("/api/files/uploads", json=replacement).status_code == 200
    assert not state_path.exists()
    assert await transfers.clear_uploaded_files() == {"uploaded_file_resources": 1}
    with pytest.raises(transfers.TransferError, match="resource_not_found"):
        await transfers.resolve_uploaded_files([replacement["resource_id"]], "history")
