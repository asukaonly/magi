from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.api.routers.memory import portability_routes
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.operations import MemoryPortabilityOperation


def _operation(kind: str = "backup") -> MemoryPortabilityOperation:
    return MemoryPortabilityOperation(
        operation_id="4a884338-cfad-4530-819c-590b9ad5c663",
        kind=kind,
        created_at="2026-08-18T00:00:00Z",
    )


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.operation = _operation()

    async def start_backup(self, **kwargs):
        self.calls.append(("backup", kwargs))
        return self.operation

    async def start_export(self, **kwargs):
        self.calls.append(("export", kwargs))
        return self.operation.model_copy(update={"kind": "export"})

    async def start_inspection(self, **kwargs):
        self.calls.append(("inspect", kwargs))
        return self.operation.model_copy(update={"kind": "inspect"})

    async def start_restore(self, **kwargs):
        self.calls.append(("restore", kwargs))
        return self.operation.model_copy(update={"kind": "restore"})

    async def delete_candidate(self, **kwargs):
        self.calls.append(("delete", kwargs))

    def get_active_operation(self):
        return self.operation

    def get_latest_operation(self):
        return self.operation

    def get_operation(self, operation_id: str):
        if operation_id == self.operation.operation_id:
            return self.operation
        return None


def _client(monkeypatch: pytest.MonkeyPatch, service: _FakeService) -> TestClient:
    monkeypatch.setattr(
        portability_routes,
        "get_memory_portability_service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
    )
    return TestClient(app)


@pytest.mark.parametrize("selection", [None, False, True])
def test_readable_export_requires_explicit_l0_selection(
    monkeypatch: pytest.MonkeyPatch, selection: bool | None,
) -> None:
    service = _FakeService()
    body = {"destination_directory": "/tmp"}
    if selection is not None:
        body["include_l0"] = selection
    response = _client(monkeypatch, service).post("/api/memory/portability/exports", json=body)
    assert response.status_code == 202
    assert service.calls[0][1]["include_l0"] is (selection is True)


def test_memory_portability_routes_are_publicly_reachable() -> None:
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in public.routes
        if hasattr(route, "methods")
    }
    expected = {
        "/portability/backups": {"POST"},
        "/portability/exports": {"POST"},
        "/portability/restores/inspect": {"POST"},
        "/portability/restores/{candidate_id}/confirm": {"POST"},
        "/portability/restores/{candidate_id}": {"DELETE"},
        "/portability/operations/active": {"GET"},
        "/portability/operations/latest": {"GET"},
        "/portability/operations/{operation_id}": {"GET"},
    }
    for path, methods in expected.items():
        assert methods.issubset(methods_by_path[path])


def test_backup_route_keeps_password_out_of_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "unique-portability-secret-91d914"
    client = _client(monkeypatch, _FakeService())

    response = client.post(
        "/api/memory/portability/backups",
        json={
            "destination_directory": "/tmp",
            "encryption": "password",
            "password": secret * 100,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "password_too_long"
    assert secret not in response.text


def test_backup_route_redacts_structurally_invalid_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "unique-invalid-password-2dc2f1"
    client = _client(monkeypatch, _FakeService())

    response = client.post(
        "/api/memory/portability/backups",
        json={
            "destination_directory": "/tmp",
            "encryption": "password",
            "password": [secret],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "password_invalid"
    assert secret not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        [{"password": "unique-wrong-shape-secret-84fd34"}],
        {
            "destination_directory": "/tmp",
            "encryption": "password",
            "password_typo": "unique-extra-field-secret-c12dbe",
        },
    ],
)
def test_backup_route_never_echoes_invalid_request_input(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    response = _client(monkeypatch, _FakeService()).post(
        "/api/memory/portability/backups",
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "request_invalid"
    assert "unique-" not in response.text


def test_plaintext_backup_rejects_password_without_starting_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeService()
    client = _client(monkeypatch, service)

    response = client.post(
        "/api/memory/portability/backups",
        json={
            "destination_directory": "/tmp",
            "encryption": "none",
            "password": "must-not-be-used",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "password_not_allowed"
    assert service.calls == []


def test_routes_return_pollable_operations_and_password_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeService()
    client = _client(monkeypatch, service)

    backup = client.post(
        "/api/memory/portability/backups",
        json={
            "destination_directory": "/tmp",
            "encryption": "password",
            "password": "strong password",
        },
    )
    inspect = client.post(
        "/api/memory/portability/restores/inspect",
        json={"source_path": "/tmp/source.magibackup"},
    )
    active = client.get("/api/memory/portability/operations/active")
    latest = client.get("/api/memory/portability/operations/latest")
    operation = client.get(f"/api/memory/portability/operations/{service.operation.operation_id}")

    assert backup.status_code == 202
    assert backup.json()["operation_id"] == service.operation.operation_id
    assert inspect.status_code == 202
    assert inspect.json()["kind"] == "inspect"
    assert active.status_code == 200
    assert latest.status_code == 200
    assert operation.status_code == 200


def test_portability_routes_do_not_enter_shared_memory_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeService()
    entered = 0

    class _Memory:
        @asynccontextmanager
        async def memory_operation_guard(self):
            nonlocal entered
            entered += 1
            yield

    import magi.api.routers.memory as memory_package

    monkeypatch.setattr(memory_package, "_resolve_unified_memory", lambda: _Memory())
    client = _client(monkeypatch, service)

    response = client.get("/api/memory/portability/operations/active")

    assert response.status_code == 200
    assert entered == 0


def test_portability_error_uses_stable_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingService(_FakeService):
        async def start_export(self, **kwargs):
            raise MemoryPortabilityError(
                "insufficient_space",
                "The selected directory does not have enough free space.",
            )

    response = _client(monkeypatch, _FailingService()).post(
        "/api/memory/portability/exports",
        json={"destination_directory": "/tmp", "include_l0": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "error_code": "insufficient_space",
        "message": "The selected directory does not have enough free space.",
    }


def test_operation_read_error_uses_stable_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingService(_FakeService):
        def get_latest_operation(self):
            raise MemoryPortabilityError(
                "operation_state_write_failed",
                "The memory data operation state is unavailable.",
                status_code=500,
            )

    response = _client(monkeypatch, _FailingService()).get(
        "/api/memory/portability/operations/latest"
    )

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "error_code": "operation_state_write_failed",
        "message": "The memory data operation state is unavailable.",
    }
