"""Public API coverage for selectable stable memory contexts."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.core.workspace import WorkspacePaths, WorkspaceStateStore
from magi.memory.context_scope import ContextCatalog, ContextScopeError


class _ChatReadService:
    def __init__(self, workspace_paths: list[str]) -> None:
        self.workspace_paths = workspace_paths
        self.calls: list[str] = []

    async def alist_workspace_paths(self, user_id: str) -> list[str]:
        self.calls.append(user_id)
        return list(self.workspace_paths)


def _client(monkeypatch, memory, chat_read_service: _ChatReadService) -> TestClient:
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.context_routes._resolve_unified_memory",
        lambda: memory,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.context_routes.get_chat_read_service",
        lambda: chat_read_service,
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.correction_routes._resolve_unified_memory",
        lambda: memory,
    )
    return TestClient(app)


def test_context_options_route_is_public_and_hides_local_paths(
    tmp_path,
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    first = tmp_path / "magi"
    second = tmp_path / "notes"
    first.mkdir()
    second.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(first)).claim_identity()
    WorkspaceStateStore(WorkspacePaths.from_root(second)).claim_identity()
    chat = _ChatReadService([str(first), "\u0000invalid-workspace", str(second), str(first)])
    client = _client(monkeypatch, unified_memory_for_tests, chat)

    response = client.get("/api/memory/l2/context-options")

    assert response.status_code == 200
    body = response.json()
    assert [item["label"] for item in body["items"]] == ["magi", "notes"]
    assert all(item["dimension"] == "project" for item in body["items"])
    assert all(set(item) == {"context_id", "dimension", "label"} for item in body["items"])
    assert all(item["context_id"].startswith("ctx_project_") for item in body["items"])
    assert str(tmp_path) not in response.text
    assert chat.calls == ["local_user"]

    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    assert "/l2/context-options" in {route.path for route in public.routes}


def test_context_options_disambiguate_same_names_without_internal_ids(
    tmp_path,
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    first = tmp_path / "first" / "magi"
    second = tmp_path / "second" / "magi"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    WorkspaceStateStore(WorkspacePaths.from_root(first)).claim_identity()
    WorkspaceStateStore(WorkspacePaths.from_root(second)).claim_identity()
    client = _client(
        monkeypatch,
        unified_memory_for_tests,
        _ChatReadService([str(first), str(second)]),
    )

    response = client.get("/api/memory/l2/context-options")

    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["label"] for item in items} == {"first/magi", "second/magi"}
    for item in items:
        assert item["context_id"][-6:] not in item["label"]
        assert "workspace_" not in item["label"]

    selected = items[0]
    now = time.time() - 60
    assert unified_memory_for_tests.l2 is not None
    assertion_id = asyncio.run(
        unified_memory_for_tests.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": "Hangzhou",
                "confidence_score": 0.9,
                "evidence_events": ["event-same-name"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": now,
                "last_validated_at": now,
                "temporal_scope": "persistent",
            }
        )
    )
    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "same-name-scope",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "scope_refinement",
            "replacement": {"value": "Hangzhou"},
            "scope": {
                "all_of": [
                    {
                        "dimension": "project",
                        "context_id": selected["context_id"],
                    }
                ]
            },
        },
    )
    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )

    assert corrected.status_code == 200, corrected.text
    assert history.status_code == 200
    assert history.json()["context_labels"] == {selected["context_id"]: selected["label"]}


def test_context_options_hide_deleted_session_projects_and_restore_them(
    tmp_path,
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    workspace = tmp_path / "magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    chat = _ChatReadService([str(workspace)])
    client = _client(monkeypatch, unified_memory_for_tests, chat)
    first = client.get("/api/memory/l2/context-options").json()["items"]
    context_id = first[0]["context_id"]

    chat.workspace_paths = []
    hidden = client.get("/api/memory/l2/context-options")
    chat.workspace_paths = [str(workspace)]
    restored = client.get("/api/memory/l2/context-options")

    assert hidden.status_code == 200
    assert hidden.json()["items"] == []
    assert restored.status_code == 200
    assert restored.json()["items"][0]["context_id"] == context_id


def test_context_options_use_existing_path_and_new_name_after_move(
    tmp_path,
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    old_path = tmp_path / "OldName"
    old_path.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(old_path)).claim_identity()
    chat = _ChatReadService([str(old_path)])
    client = _client(monkeypatch, unified_memory_for_tests, chat)
    original = client.get("/api/memory/l2/context-options").json()["items"][0]
    new_path = tmp_path / "NewName"
    shutil.move(str(old_path), str(new_path))
    WorkspaceStateStore(WorkspacePaths.from_root(new_path)).rebind_identity(old_path)
    chat.workspace_paths = [str(old_path), str(new_path)]

    moved = client.get("/api/memory/l2/context-options")

    assert moved.status_code == 200
    assert moved.json()["items"] == [
        {
            "context_id": original["context_id"],
            "dimension": "project",
            "label": "NewName",
        }
    ]
    assert str(old_path) not in moved.text
    assert str(new_path) not in moved.text


def test_correction_api_rejects_legacy_free_text_scope(
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    client = _client(
        monkeypatch,
        unified_memory_for_tests,
        _ChatReadService([]),
    )

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "legacy-scope",
            "target": {"kind": "assertion", "id": "assertion-1"},
            "correction_kind": "scope_refinement",
            "replacement": {"value": "Shanghai"},
            "scope": {"project": "magi"},
        },
    )

    assert response.status_code == 422


def test_correction_api_returns_a_stable_error_for_unknown_context(
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    client = _client(
        monkeypatch,
        unified_memory_for_tests,
        _ChatReadService([]),
    )

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "unknown-scope",
            "target": {"kind": "assertion", "id": "assertion-1"},
            "correction_kind": "scope_refinement",
            "replacement": {"value": "Shanghai"},
            "scope": {
                "all_of": [
                    {
                        "dimension": "project",
                        "context_id": f"ctx_project_{'a' * 64}",
                    }
                ]
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "context_scope_unknown"


def test_bound_project_scope_can_be_applied_to_an_assertion(
    tmp_path,
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    workspace = tmp_path / "magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    assert unified_memory_for_tests.l2 is not None
    option = asyncio.run(
        ContextCatalog(unified_memory_for_tests.l2.db_path).register_workspace(str(workspace))
    )
    assert option is not None
    now = time.time() - 60
    assertion_id = asyncio.run(
        unified_memory_for_tests.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": "Hangzhou",
                "confidence_score": 0.9,
                "evidence_events": ["event-1"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": now,
                "last_validated_at": now,
                "temporal_scope": "persistent",
            }
        )
    )
    chat = _ChatReadService([str(workspace)])
    client = _client(
        monkeypatch,
        unified_memory_for_tests,
        chat,
    )

    request = {
        "request_id": "bound-scope",
        "target": {"kind": "assertion", "id": assertion_id},
        "correction_kind": "scope_refinement",
        "replacement": {"value": "Hangzhou"},
        "scope": {
            "all_of": [
                {
                    "dimension": "project",
                    "context_id": option.context_id,
                }
            ]
        },
    }
    response = client.post("/api/memory/l2/corrections", json=request)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_claim"]["scope"] == {
        "all_of": [{"dimension": "project", "context_id": option.context_id}]
    }
    assert body["correction"]["scope"] == body["current_claim"]["scope"]

    active_history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    chat.workspace_paths = []
    assert client.get("/api/memory/l2/context-options").json()["items"] == []
    inactive_history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    retried = client.post("/api/memory/l2/corrections", json=request)
    changed_intent = client.post(
        "/api/memory/l2/corrections",
        json={**request, "replacement": {}},
    )

    assert active_history.status_code == 200
    assert active_history.json()["context_labels"] == {option.context_id: "magi"}
    assert inactive_history.status_code == 200
    assert inactive_history.json()["context_labels"] == {option.context_id: "magi"}
    assert retried.status_code == 200
    assert retried.json()["created"] is False
    assert changed_intent.status_code == 409


def test_retry_survives_context_deactivation_during_route_validation(
    tmp_path,
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    workspace = tmp_path / "magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    assert unified_memory_for_tests.l2 is not None
    option = asyncio.run(
        ContextCatalog(unified_memory_for_tests.l2.db_path).register_workspace(str(workspace))
    )
    assert option is not None
    now = time.time() - 60
    assertion_id = asyncio.run(
        unified_memory_for_tests.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": "Hangzhou",
                "confidence_score": 0.9,
                "evidence_events": ["event-race"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": now,
                "last_validated_at": now,
                "temporal_scope": "persistent",
            }
        )
    )
    scope = {"all_of": [{"dimension": "project", "context_id": option.context_id}]}

    async def _complete_first_request_then_fail_validation(self, requested_scope):
        await unified_memory_for_tests.l2.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="validation-race",
            actor_id="user:local_user",
            correction_kind="scope_refinement",
            replacement_value="Hangzhou",
            scope=requested_scope,
        )
        raise ContextScopeError(
            "The selected context is not available",
            code="context_scope_unknown",
        )

    monkeypatch.setattr(
        ContextCatalog,
        "validate_correction_scope",
        _complete_first_request_then_fail_validation,
    )
    client = _client(
        monkeypatch,
        unified_memory_for_tests,
        _ChatReadService([str(workspace)]),
    )

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "validation-race",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "scope_refinement",
            "replacement": {"value": "Hangzhou"},
            "scope": scope,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["created"] is False


def test_history_does_not_expose_an_internal_context_id_as_a_label(
    monkeypatch,
    unified_memory_for_tests,
) -> None:
    assert unified_memory_for_tests.l2 is not None
    context_id = f"ctx_project_{'e' * 64}"
    with sqlite3.connect(unified_memory_for_tests.l2.db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_context_catalog(
                context_id, dimension, label, source_kind, is_active,
                created_at, updated_at
            ) VALUES (?, 'project', ?, 'legacy_custom', 1, 0, 0)
            """,
            (context_id, context_id),
        )
        connection.commit()
    now = time.time() - 60
    assertion_id = asyncio.run(
        unified_memory_for_tests.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": "Hangzhou",
                "confidence_score": 0.9,
                "evidence_events": ["event-orphan-label"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": now,
                "last_validated_at": now,
                "temporal_scope": "persistent",
                "scope": {"all_of": [{"dimension": "project", "context_id": context_id}]},
            }
        )
    )
    client = _client(
        monkeypatch,
        unified_memory_for_tests,
        _ChatReadService([]),
    )

    response = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )

    assert response.status_code == 200
    assert response.json()["context_labels"] == {}
