"""Bounded portability downloads reject changed, unfinished and unrelated files."""
from types import SimpleNamespace
import base64
import pytest
from magi.api.services import portability_downloads as downloads
from magi.api.services.file_transfers import CHUNK_BYTES, TransferError
from magi.memory.portability.operations import MemoryPortabilityOperation

@pytest.fixture
def output(tmp_path, monkeypatch):
    path = tmp_path / "memory.magibackup"
    path.write_bytes(b"x" * (CHUNK_BYTES + 3))
    operation = MemoryPortabilityOperation(operation_id="test", kind="backup", status="succeeded", created_at="2026-09-08T00:00:00Z", output_path=str(path), file_size_bytes=path.stat().st_size)
    monkeypatch.setattr(downloads, "get_memory_portability_service", lambda: SimpleNamespace(get_operation=lambda operation_id: operation if operation_id == "test" else None))
    return operation, path

@pytest.mark.asyncio
async def test_downloads_only_the_artifact_owned_by_a_completed_operation(output):
    metadata = await downloads.describe_output("test")
    chunk = await downloads.read_output_chunk("test", 0, metadata.version)
    assert len(base64.b64decode(chunk.data)) == CHUNK_BYTES
    last = await downloads.read_output_chunk("test", CHUNK_BYTES, metadata.version)
    assert base64.b64decode(last.data) == b"xxx"
    with pytest.raises(TransferError, match="output_not_available"):
        await downloads.describe_output("/etc/passwd")
    operation, _ = output
    operation.status = "running"
    with pytest.raises(TransferError, match="output_not_available"):
        await downloads.describe_output("test")

@pytest.mark.asyncio
async def test_refuses_a_file_replaced_between_chunks(output):
    metadata = await downloads.describe_output("test")
    operation, path = output
    path.unlink()
    path.write_bytes(b"y" * operation.file_size_bytes)
    with pytest.raises(TransferError, match="output_changed"):
        await downloads.read_output_chunk("test", 0, metadata.version)
    path.unlink()
    path.symlink_to(path.parent / "other")
    with pytest.raises(TransferError):
        await downloads.describe_output("test")


def test_download_routes_are_reachable_through_public_allowlist(output):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
    from magi.api.routers.files import files_router
    app = FastAPI()
    app.include_router(_build_public_router(files_router, _PUBLIC_ROUTE_METHODS["files"]), prefix="/api/files")
    client = TestClient(app)
    metadata = client.get("/api/files/outputs/test")
    assert metadata.status_code == 200
    content = client.get("/api/files/outputs/test/chunks", params={"offset": 0, "version": metadata.json()["version"]})
    assert content.status_code == 200
    assert content.json()["operation_id"] == "test"
    assert client.get("/api/files/outputs/test/chunks", params={"offset": 0, "version": "wrong"}).status_code == 422
