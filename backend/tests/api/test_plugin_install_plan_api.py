"""Public installation routes accept only explicit plan approvals."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routers.plugins import plugins_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
    )
    return TestClient(app)


@pytest.mark.parametrize("endpoint", [
    "/install/registry", "/install/registry/jobs", "/demo/update", "/demo/update/jobs",
])
@pytest.mark.parametrize("old_field", ["expected_fingerprint", "registry_fingerprint"])
def test_old_approval_fields_are_rejected(client, endpoint, old_field):
    payload = {old_field: "a" * 64}
    if endpoint.startswith("/install"):
        payload["plugin_id"] = "demo"
    response = client.post(f"/api/plugins{endpoint}", json=payload)
    assert response.status_code == 422
    assert any(error["type"] == "extra_forbidden" for error in response.json()["detail"])
    payload["plan_fingerprint"] = "b" * 64
    assert client.post(f"/api/plugins{endpoint}", json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"plugin_id": "demo"},
    {"plugin_id": "../escape", "update": False},
    {"plugin_id": "demo", "update": False, "registry_fingerprint": "a" * 64},
])
def test_public_plan_route_rejects_invalid_requests(client, payload):
    response = client.post("/api/plugins/install/registry/plan", json=payload)
    assert response.status_code == 422
