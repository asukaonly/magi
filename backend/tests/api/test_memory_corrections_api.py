from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from _shared.memory_schema import apply_memory_shared_schema
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore


def _memory(tmp_path: Path) -> UnifiedMemoryStore:
    memory_db = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(memory_db)))
    return UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            enable_l2_conflict_arbitration=False,
            async_embeddings=False,
        ),
    )


def _client(monkeypatch, memory: UnifiedMemoryStore) -> TestClient:
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]),
        prefix="/api/memory",
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.correction_routes._resolve_unified_memory",
        lambda: memory,
    )
    return TestClient(app)


def _seed_assertion(memory: UnifiedMemoryStore, *, value: str = "Hangzhou") -> str:
    assert memory.l2 is not None
    now = time.time() - 3600
    return asyncio.run(
        memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": value,
                "confidence_score": 0.8,
                "evidence_events": ["evt-original"],
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


def _seed_relationship(memory: UnifiedMemoryStore) -> str:
    assert memory.l2 is not None
    return asyncio.run(
        memory.l2.upsert_knowledge_edge(
            subject_id="user:local_user",
            subject_type="user",
            predicate="CURRENT_LIVES_IN",
            object_id="place:hangzhou",
            object_type="place",
            evidence_event_ids=["evt-edge-original"],
            confidence=0.9,
            observed_at=time.time() - 3600,
            source_type="conversation",
            extraction_method="explicit",
        )
    )


def test_assertion_correction_api_audits_blocks_replay_and_reverts(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)

    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "assertion-correction-1",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
            "reason": "The old city was incorrect",
        },
    )

    assert corrected.status_code == 200
    body = corrected.json()
    assert body["current_claim"]["trait_value"] == "Shanghai"
    assert body["current_claim"]["evidence_events"] == []
    assert body["derivation_state"] == "pending"
    assert body["correction"]["audit_event_id"].startswith("correction_audit_")

    assert memory.l2 is not None
    asyncio.run(memory.l2.process_memory_correction_jobs(limit=20))
    assert (
        asyncio.run(
            memory.l2.get_memory_correction_derivation_state(
                body["correction"]["correction_id"]
            )
        )
        == "completed"
    )

    assert memory.l1 is not None
    audit_events = asyncio.run(memory.l1.query_events(event_type="MEMORY_CORRECTION", limit=10))
    assert [event["event_id"] for event in audit_events] == [body["correction"]["audit_event_id"]]
    assert audit_events[0]["cognition_eligible"] is False
    assert audit_events[0]["l1_retrieval_scope"] == "audit_only"

    _seed_assertion(memory, value="Hangzhou")
    current = asyncio.run(memory.l2.list_current_assertions(entity_id="user:local_user", limit=20))
    assert [item["trait_value"] for item in current] == ["Shanghai"]

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    assert history.status_code == 200
    assert len(history.json()["versions"]) == 2
    assert len(history.json()["corrections"]) == 1

    reverted = client.post(
        f"/api/memory/l2/corrections/{body['correction']['correction_id']}/revert",
        json={"request_id": "assertion-revert-1"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["current_claim"]["trait_value"] == "Hangzhou"
    assert reverted.json()["correction"]["state"] == "reverted"


def test_relationship_correction_api_preserves_history_and_blocks_replay(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    triple_id = _seed_relationship(memory)
    client = _client(monkeypatch, memory)

    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "edge-correction-1",
            "target": {"kind": "edge", "id": triple_id},
            "correction_kind": "record_error",
            "replacement": {
                "object_id": "place:shanghai",
                "object_type": "place",
            },
            "reason": "The old relationship was incorrect",
        },
    )

    assert corrected.status_code == 200
    body = corrected.json()
    assert body["current_claim"]["object_id"] == "place:shanghai"
    assert body["current_claim"]["evidence_event_ids"] == []
    assert body["derivation_state"] == "pending"

    assert memory.l2 is not None
    asyncio.run(memory.l2.process_memory_correction_jobs(limit=20))
    assert (
        asyncio.run(
            memory.l2.get_memory_correction_derivation_state(
                body["correction"]["correction_id"]
            )
        )
        == "completed"
    )

    replayed_id = _seed_relationship(memory)
    assert replayed_id == triple_id
    replayed = asyncio.run(memory.l2.get_relationship(triple_id=triple_id))
    assert replayed["status"] == "user_rejected"
    current = asyncio.run(
        memory.l2.list_current_relationships(subject_id="user:local_user", limit=20)
    )
    assert [item["object_id"] for item in current] == ["place:shanghai"]

    history = client.get(
        "/api/memory/l2/corrections",
        params={
            "target_kind": "edge",
            "target_id": body["current_claim"]["triple_id"],
        },
    )
    assert history.status_code == 200
    assert len(history.json()["versions"]) == 3
    assert len(history.json()["corrections"]) == 1

    reverted = client.post(
        f"/api/memory/l2/corrections/{body['correction']['correction_id']}/revert",
        json={"request_id": "edge-revert-1"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["current_claim"]["object_id"] == "place:hangzhou"


def test_memory_correction_routes_are_publicly_reachable() -> None:
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if hasattr(route, "methods"):
            route_methods.setdefault(route.path, set()).update(route.methods)

    assert route_methods["/l2/corrections"] == {"GET", "POST"}
    assert route_methods["/l2/corrections/{correction_id}/revert"] == {"POST"}
