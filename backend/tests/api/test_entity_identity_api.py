"""Entity governance must be reachable through the product router allowlist."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.memory.l2.entities.catalog import L2EntityCatalog


@asynccontextmanager
async def operation_guard():
    yield


def test_public_identity_preview_apply_and_validation(tmp_path, monkeypatch):
    from _shared.memory_schema import apply_memory_shared_schema

    db_path = str(tmp_path / "memory.db")
    asyncio.run(apply_memory_shared_schema(db_path))
    catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
    asyncio.run(
        catalog.upsert_entity(entity_id="old:apple", canonical_name="苹果", entity_type="other")
    )
    memory = SimpleNamespace(l2_entity_catalog=catalog, memory_operation_guard=operation_guard)
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.entity_identity_routes._resolve_unified_memory", lambda: memory
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.entity_identity_routes.canonical_self_id", lambda _: "user:self"
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    with TestClient(app) as client:
        command = {"kind": "type_correction", "entity_id": "old:apple", "new_type": "food"}
        preview = client.post("/api/memory/l2/entities/changes/preview", json=command)
        assert preview.status_code == 200
        assert preview.json()["entity"]["canonical_name"] == "苹果"
        request = {
            "command": command,
            "expected_fingerprint": preview.json()["fingerprint"],
            "request_id": "request",
        }
        applied = client.post("/api/memory/l2/entities/changes/apply", json=request)
        assert applied.status_code == 200
        assert applied.json()["current_type"] == "food"
        assert (
            client.post("/api/memory/l2/entities/changes/apply", json=request).json()
            == applied.json()
        )
        assert client.get("/api/memory/l2/entities/reviews").status_code == 200
        assert client.get("/api/memory/l2/entities/identity-audit").status_code == 200
        invalid = client.post(
            "/api/memory/l2/entities/changes/preview", json={**command, "new_type": "invented"}
        )
        assert invalid.status_code == 422
        invalid_review = client.post(
            "/api/memory/l2/entities/reviews/missing/reject", json={"expected_version": 1}
        )
        assert invalid_review.status_code == 404
