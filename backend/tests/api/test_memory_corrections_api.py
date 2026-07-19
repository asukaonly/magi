from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from _shared.memory_schema import apply_memory_shared_schema
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.api.routers.memory.schemas import MemoryCorrectionRecord
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore
from magi.user_profile.correction_derivation import (
    register_user_profile_correction_derivation_handlers,
)

_INTERNAL_CORRECTION_FIELDS = {
    "request_id",
    "actor_id",
    "target_id",
    "target_kind",
    "slot_key",
    "claim_fingerprint",
    "source_event_id",
    "audit_event_id",
    "replacement_target_id",
    "reverted_by",
}
_INTERNAL_VERSION_FIELDS = {
    "version_id",
    "assertion_id",
    "triple_id",
    "claim_fingerprint",
    "evidence_events",
    "evidence_event_ids",
    "evidence_text",
    "natural_summary",
    "authority_ref",
}


def _memory(tmp_path: Path) -> UnifiedMemoryStore:
    memory_db = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(memory_db)))
    memory = UnifiedMemoryStore(
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
    register_user_profile_correction_derivation_handlers(memory)
    return memory


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


def _seed_assertion(
    memory: UnifiedMemoryStore,
    *,
    value: str = "Hangzhou",
    event_id: str = "evt-original",
    observed_at: float | None = None,
) -> str:
    assert memory.l2 is not None
    now = float(observed_at if observed_at is not None else time.time() - 3600)
    return asyncio.run(
        memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:local_user",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": value,
                "confidence_score": 0.8,
                "evidence_events": [event_id],
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


def _seed_relationship(
    memory: UnifiedMemoryStore,
    *,
    object_id: str = "place:hangzhou",
    event_id: str = "evt-edge-original",
    predicate: str = "CURRENT_LIVES_IN",
) -> str:
    assert memory.l2 is not None
    return asyncio.run(
        memory.l2.upsert_knowledge_edge(
            subject_id="user:local_user",
            subject_type="user",
            predicate=predicate,
            object_id=object_id,
            object_type="place",
            evidence_event_ids=[event_id],
            confidence=0.9,
            observed_at=time.time() - 3600,
            source_type="conversation",
            extraction_method="explicit",
        )
    )


def _replacement_target_id(memory: UnifiedMemoryStore, correction_id: str) -> str:
    assert memory.l2 is not None
    with sqlite3.connect(memory.l2.db_path) as db:
        row = db.execute(
            "SELECT replacement_target_id FROM memory_corrections WHERE correction_id = ?",
            (correction_id,),
        ).fetchone()
    assert row is not None and row[0]
    return str(row[0])


def test_public_correction_schema_fails_closed_when_revert_decision_is_missing():
    record = MemoryCorrectionRecord.model_validate(
        {
            "correction_id": "correction-1",
            "correction_kind": "record_error",
            "created_at": 1.0,
            "state": "active",
        }
    )

    assert record.can_revert is False


def test_history_explains_when_identity_merge_makes_correction_unnecessary(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)

    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "identity-merge-noop-history",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
        },
    )
    assert corrected.status_code == 200
    correction_id = corrected.json()["correction"]["correction_id"]

    assert memory.l2 is not None
    with sqlite3.connect(memory.l2.db_path) as db:
        db.execute(
            """
            UPDATE memory_corrections
            SET state = 'reverted', reverted_at = ?, reverted_by = ?
            WHERE correction_id = ?
            """,
            (time.time(), "system:identity_merge_noop", correction_id),
        )

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    assert history.status_code == 200
    public_record = history.json()["corrections"][0]
    assert public_record["state"] == "reverted"
    assert public_record["resolution_reason"] == "identity_merge_noop"
    assert public_record["can_revert"] is False
    assert "reverted_by" not in public_record

    with sqlite3.connect(memory.l2.db_path) as db:
        db.execute(
            """
            UPDATE memory_corrections
            SET reverted_by = ?
            WHERE correction_id = ?
            """,
            ("user:local_user", correction_id),
        )

    ordinary_revert_history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    assert ordinary_revert_history.status_code == 200
    assert ordinary_revert_history.json()["corrections"][0]["resolution_reason"] is None


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
    assert "evidence_events" not in body["current_claim"]
    assert body["derivation_state"] == "pending"
    assert body["correction"]["can_revert"] is True
    assert body["correction"]["target_forgotten"] is False
    assert "transition_applied_at" in body["correction"]
    assert not (_INTERNAL_CORRECTION_FIELDS & set(body["correction"]))

    assert memory.l2 is not None
    asyncio.run(memory.l2.process_memory_correction_jobs(limit=20))
    assert (
        asyncio.run(
            memory.l2.get_memory_correction_derivation_state(body["correction"]["correction_id"])
        )
        == "completed"
    )

    assert memory.l1 is not None
    audit_events = asyncio.run(memory.l1.query_events(event_type="MEMORY_CORRECTION", limit=10))
    assert len(audit_events) == 1
    assert audit_events[0]["event_id"].startswith("correction_audit_")
    assert audit_events[0]["cognition_eligible"] is False
    assert audit_events[0]["l1_retrieval_scope"] == "audit_only"
    assert audit_events[0]["content"] == "Memory correction recorded"
    assert "Shanghai" not in str(audit_events[0])
    assert "The old city was incorrect" not in str(audit_events[0])

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
    assert not (_INTERNAL_CORRECTION_FIELDS & set(history.json()["corrections"][0]))
    assert all(
        not (_INTERNAL_VERSION_FIELDS & set(version)) for version in history.json()["versions"]
    )

    reverted = client.post(
        f"/api/memory/l2/corrections/{body['correction']['correction_id']}/revert",
        json={"request_id": "assertion-revert-1"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["current_claim"]["trait_value"] == "Hangzhou"
    assert reverted.json()["correction"]["state"] == "reverted"
    assert reverted.json()["correction"]["can_revert"] is False


def test_correction_api_returns_the_store_commit_snapshot(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    assert memory.l2 is not None
    original_apply = memory.l2.apply_assertion_correction
    captured: dict[str, object] = {}

    async def apply_then_simulate_concurrent_write(**kwargs):
        result = await original_apply(**kwargs)
        assert result is not None
        committed = dict(result["current_assertion"])
        captured["committed"] = committed
        with sqlite3.connect(memory.l2.db_path) as db:
            db.execute(
                """
                UPDATE tom_trait_assertions
                SET trait_value = 'Concurrent later value'
                WHERE assertion_id = ?
                """,
                (committed["assertion_id"],),
            )
            db.commit()
        return result

    monkeypatch.setattr(
        memory.l2,
        "apply_assertion_correction",
        apply_then_simulate_concurrent_write,
    )
    client = _client(monkeypatch, memory)

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "store-snapshot-response",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
        },
    )

    assert response.status_code == 200
    committed = captured["committed"]
    assert isinstance(committed, dict)
    assert committed["trait_value"] == "Shanghai"
    assert response.json()["current_claim"]["trait_value"] == committed["trait_value"]
    changed = asyncio.run(
        memory.l2.get_tom_assertion(assertion_id=str(committed["assertion_id"]))
    )
    assert changed is not None
    assert changed["trait_value"] == "Concurrent later value"


def test_forgetting_claim_evidence_hides_its_l1_correction_audit(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory, event_id="evt-private-correction-source")
    client = _client(monkeypatch, memory)

    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "forget-correction-audit",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Private replacement"},
            "reason": "Private correction explanation",
        },
    )
    assert corrected.status_code == 200
    assert memory.l2 is not None
    asyncio.run(memory.l2.process_memory_correction_jobs(limit=20))

    assert memory.l1 is not None
    audit_events = asyncio.run(memory.l1.query_events(event_type="MEMORY_CORRECTION", limit=10))
    assert len(audit_events) == 1
    audit_event_id = audit_events[0]["event_id"]

    asyncio.run(
        memory.forget_source_events(
            ["evt-private-correction-source"],
            reason="user_delete_event",
        )
    )

    forgotten_audit = asyncio.run(memory.l1.get_event(audit_event_id))
    assert forgotten_audit is not None
    assert forgotten_audit["deleted_at"] is not None


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
    assert "evidence_event_ids" not in body["current_claim"]
    assert body["derivation_state"] == "pending"

    assert memory.l2 is not None
    asyncio.run(memory.l2.process_memory_correction_jobs(limit=20))
    assert (
        asyncio.run(
            memory.l2.get_memory_correction_derivation_state(body["correction"]["correction_id"])
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
            "target_id": _replacement_target_id(
                memory,
                body["correction"]["correction_id"],
            ),
        },
    )
    assert history.status_code == 200
    assert len(history.json()["versions"]) == 3
    assert len(history.json()["corrections"]) == 1
    assert not (_INTERNAL_CORRECTION_FIELDS & set(history.json()["corrections"][0]))
    assert all(
        not (_INTERNAL_VERSION_FIELDS & set(version)) for version in history.json()["versions"]
    )

    reverted = client.post(
        f"/api/memory/l2/corrections/{body['correction']['correction_id']}/revert",
        json={"request_id": "edge-revert-1"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["current_claim"]["object_id"] == "place:hangzhou"


def test_correction_history_marks_forgotten_target_non_revertible(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)
    correction_request = {
        "request_id": "assertion-correction-before-forget",
        "target": {"kind": "assertion", "id": assertion_id},
        "correction_kind": "record_error",
        "replacement": {"value": "Shanghai"},
        "reason": "The old city should be removed",
    }
    corrected = client.post(
        "/api/memory/l2/corrections",
        json=correction_request,
    )
    assert corrected.status_code == 200
    assert memory.l2 is not None
    asyncio.run(memory.l2.forget_entity(entity_id="user:local_user"))

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )

    assert history.status_code == 200
    correction = history.json()["corrections"][0]
    assert correction["target_forgotten"] is True
    assert correction["forget_affected"] is True
    assert correction["content_redacted"] is True
    assert correction["can_revert"] is False
    assert correction["before"] is None
    assert correction["replacement"] is None
    assert correction["reason"] is None
    assert "source_event_id" not in correction
    assert "audit_event_id" not in correction
    assert history.json()["versions"] == []

    with sqlite3.connect(memory.l2.db_path) as db:
        db.execute("DELETE FROM tom_trait_assertions")
    after_cleanup = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    assert after_cleanup.status_code == 200
    cleaned_correction = after_cleanup.json()["corrections"][0]
    assert cleaned_correction["content_redacted"] is True
    assert cleaned_correction["before"] is None
    assert cleaned_correction["replacement"] is None

    retried = client.post("/api/memory/l2/corrections", json=correction_request)
    assert retried.status_code == 200
    assert retried.json()["current_claim"] is None
    assert retried.json()["correction"]["content_redacted"] is True
    assert retried.json()["correction"]["before"] is None
    assert retried.json()["correction"]["replacement"] is None


def test_history_hides_forgotten_correction_sources_without_replacements(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    edge_id = _seed_relationship(memory)
    client = _client(monkeypatch, memory)

    for target_kind, target_id, source_event_id in (
        ("assertion", assertion_id, "evt-assertion-feedback-private"),
        ("edge", edge_id, "evt-edge-feedback-private"),
    ):
        corrected = client.post(
            "/api/memory/l2/corrections",
            json={
                "request_id": f"{target_kind}-private-source-no-replacement",
                "target": {"kind": target_kind, "id": target_id},
                "correction_kind": "record_error",
                "reason": "private feedback explanation",
                "source_event_id": source_event_id,
            },
        )
        assert corrected.status_code == 200

    assert memory.l2 is not None
    asyncio.run(
        memory.l2.forget_source_events(
            ["evt-assertion-feedback-private", "evt-edge-feedback-private"],
            reason="user_delete_event",
        )
    )

    for target_kind, target_id in (("assertion", assertion_id), ("edge", edge_id)):
        history = client.get(
            "/api/memory/l2/corrections",
            params={"target_kind": target_kind, "target_id": target_id},
        )
        assert history.status_code == 200
        correction = history.json()["corrections"][0]
        assert correction["forget_affected"] is True
        assert correction["reason"] is None
        assert correction["can_revert"] is False
        assert "source_event_id" not in correction


def test_public_inactive_lists_never_return_forgotten_claims(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    _seed_assertion(
        memory,
        value="Private Forgotten Trait",
        event_id="evt-forgotten-assertion",
    )
    _seed_relationship(
        memory,
        object_id="place:private-forgotten",
        event_id="evt-forgotten-edge",
    )
    monkeypatch.setattr(
        "magi.api.routers.memory.l2.knowledge_routes._resolve_unified_memory",
        lambda: memory,
    )
    client = _client(monkeypatch, memory)

    assertion_before = client.get(
        "/api/memory/l2/assertions",
        params={"include_inactive": "true", "query": "Private Forgotten Trait"},
    )
    relation_before = client.get(
        "/api/memory/l2/relations",
        params={"include_inactive": "true", "query": "place:private-forgotten"},
    )
    assert assertion_before.status_code == 200 and assertion_before.json()["total"] == 1
    assert relation_before.status_code == 200 and relation_before.json()["total"] == 1

    assert memory.l2 is not None
    asyncio.run(
        memory.l2.forget_source_events(
            ["evt-forgotten-assertion", "evt-forgotten-edge"],
            reason="user_delete_event",
        )
    )

    for path, private_query in (
        ("/api/memory/l2/assertions", "Private Forgotten Trait"),
        ("/api/memory/l2/relations", "place:private-forgotten"),
    ):
        all_inactive = client.get(path, params={"include_inactive": "true"})
        searched = client.get(
            path,
            params={"include_inactive": "true", "query": private_query},
        )
        assert all_inactive.status_code == 200
        assert all_inactive.json()["items"] == []
        assert all_inactive.json()["total"] == 0
        assert searched.status_code == 200
        assert searched.json()["items"] == []
        assert searched.json()["total"] == 0


def test_relationship_history_redacts_both_sides_after_entity_forget(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    triple_id = _seed_relationship(memory)
    client = _client(monkeypatch, memory)
    correction_request = {
        "request_id": "edge-correction-before-forget",
        "target": {"kind": "edge", "id": triple_id},
        "correction_kind": "record_error",
        "replacement": {
            "object_id": "place:shanghai",
            "object_type": "place",
        },
        "reason": "The old relationship should be removed",
    }
    corrected = client.post("/api/memory/l2/corrections", json=correction_request)
    assert corrected.status_code == 200
    current_triple_id = _replacement_target_id(
        memory,
        corrected.json()["correction"]["correction_id"],
    )
    assert memory.l2 is not None
    asyncio.run(memory.l2.forget_entity(entity_id="user:local_user"))

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "edge", "target_id": current_triple_id},
    )

    assert history.status_code == 200
    assert history.json()["versions"] == []
    correction = history.json()["corrections"][0]
    assert correction["target_forgotten"] is True
    assert correction["forget_affected"] is True
    assert correction["content_redacted"] is True
    assert correction["can_revert"] is False
    assert correction["before"] is None
    assert correction["replacement"] is None
    assert correction["reason"] is None
    assert "source_event_id" not in correction
    assert "audit_event_id" not in correction

    with sqlite3.connect(memory.l2.db_path) as db:
        db.execute("DELETE FROM knowledge_graph")
    after_cleanup = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "edge", "target_id": current_triple_id},
    )
    assert after_cleanup.status_code == 200
    cleaned_correction = after_cleanup.json()["corrections"][0]
    assert cleaned_correction["content_redacted"] is True
    assert cleaned_correction["before"] is None
    assert cleaned_correction["replacement"] is None
    assert after_cleanup.json()["versions"] == []

    retried = client.post("/api/memory/l2/corrections", json=correction_request)
    assert retried.status_code == 200
    assert retried.json()["current_claim"] is None
    assert retried.json()["correction"]["content_redacted"] is True


def test_partial_evidence_forget_blocks_revert_without_marking_target_deleted(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    first_at = time.time() - 3600
    second_at = time.time() - 1800
    assertion_id = _seed_assertion(
        memory,
        event_id="evt-forgotten-source",
        observed_at=first_at,
    )
    assert (
        _seed_assertion(
            memory,
            event_id="evt-retained-source",
            observed_at=second_at,
        )
        == assertion_id
    )
    client = _client(monkeypatch, memory)
    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "partial-evidence-correction",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
            "reason": "The city changed",
        },
    )
    assert corrected.status_code == 200
    assert memory.l2 is not None
    asyncio.run(memory.l2.forget_time_range(start=first_at - 1, end=first_at + 1))

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )

    assert history.status_code == 200
    body = history.json()
    correction = body["corrections"][0]
    assert correction["target_forgotten"] is False
    assert correction["forget_affected"] is True
    assert correction["content_redacted"] is False
    assert correction["can_revert"] is False
    assert correction["before"]["trait_value"] == "Hangzhou"
    assert correction["replacement"]["value"] == "Shanghai"
    assert "evidence_events" not in correction["before"]
    assert "evidence_event_ids" not in correction["replacement"]
    assert correction["reason"] is None
    assert len(body["versions"]) == 2
    assert all(not (_INTERNAL_VERSION_FIELDS & set(version)) for version in body["versions"])


def test_history_marks_only_latest_dependent_correction_revertible(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)
    first = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "dependent-correction-first",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
        },
    )
    assert first.status_code == 200
    replacement_id = _replacement_target_id(
        memory,
        first.json()["correction"]["correction_id"],
    )
    second = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "dependent-correction-second",
            "target": {"kind": "assertion", "id": replacement_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Beijing"},
        },
    )
    assert second.status_code == 200

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )

    assert history.status_code == 200
    corrections = {
        correction["correction_id"]: correction for correction in history.json()["corrections"]
    }
    assert corrections[first.json()["correction"]["correction_id"]]["can_revert"] is False
    assert corrections[second.json()["correction"]["correction_id"]]["can_revert"] is True


def test_history_exposes_durable_lineage_collision_without_offering_revert(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)
    corrected = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "lineage-collision-correction",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
        },
    )
    assert corrected.status_code == 200
    correction_id = corrected.json()["correction"]["correction_id"]
    assert memory.l2 is not None
    with sqlite3.connect(memory.l2.db_path) as db:
        db.execute(
            """
            INSERT INTO memory_correction_revert_blocks(
                correction_id, block_reason, created_at
            ) VALUES (?, 'lineage_collision', ?)
            """,
            (correction_id, time.time()),
        )
        db.commit()

    history = client.get(
        "/api/memory/l2/corrections",
        params={"target_kind": "assertion", "target_id": assertion_id},
    )
    reverted = client.post(
        f"/api/memory/l2/corrections/{correction_id}/revert",
        json={"request_id": "blocked-lineage-revert"},
    )

    assert history.status_code == 200
    record = history.json()["corrections"][0]
    assert record["revert_blocked_reason"] == "lineage_collision"
    assert record["can_revert"] is False
    assert reverted.status_code == 409
    assert reverted.json()["detail"]["code"] == "correction_lineage_revert_blocked"


def test_record_error_without_replacement_returns_no_current_claim(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "reject-without-replacement",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
        },
    )

    assert response.status_code == 200
    assert response.json()["current_claim"] is None


def test_relationship_correction_returns_replacement_from_its_new_slot(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    triple_id = _seed_relationship(memory, predicate="VISITED")
    client = _client(monkeypatch, memory)

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "move-nonexclusive-relationship",
            "target": {"kind": "edge", "id": triple_id},
            "correction_kind": "record_error",
            "replacement": {
                "object_id": "place:shanghai",
                "object_type": "place",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["current_claim"]["predicate"] == "VISITED"
    assert response.json()["current_claim"]["object_id"] == "place:shanghai"


def test_retried_relationship_correction_follows_later_cross_slot_changes(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    triple_id = _seed_relationship(memory, predicate="VISITED")
    client = _client(monkeypatch, memory)
    first_payload = {
        "request_id": "first-cross-slot-change",
        "target": {"kind": "edge", "id": triple_id},
        "correction_kind": "record_error",
        "replacement": {
            "object_id": "place:shanghai",
            "object_type": "place",
        },
    }
    first = client.post("/api/memory/l2/corrections", json=first_payload)
    assert first.status_code == 200
    first_replacement_id = _replacement_target_id(
        memory,
        first.json()["correction"]["correction_id"],
    )
    second = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "second-cross-slot-change",
            "target": {"kind": "edge", "id": first_replacement_id},
            "correction_kind": "record_error",
            "replacement": {
                "object_id": "place:beijing",
                "object_type": "place",
            },
        },
    )
    assert second.status_code == 200

    retried = client.post("/api/memory/l2/corrections", json=first_payload)

    assert retried.status_code == 200
    assert retried.json()["created"] is False
    assert retried.json()["current_claim"]["object_id"] == "place:beijing"


def test_retried_old_assertion_revert_returns_the_actual_current_claim(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)
    first = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "first-city-correction",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Shanghai"},
        },
    )
    assert first.status_code == 200
    correction_id = first.json()["correction"]["correction_id"]
    reverted = client.post(
        f"/api/memory/l2/corrections/{correction_id}/revert",
        json={"request_id": "revert-first-city"},
    )
    assert reverted.status_code == 200
    second = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "second-city-correction",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {"value": "Beijing"},
        },
    )
    assert second.status_code == 200

    retried_revert = client.post(
        f"/api/memory/l2/corrections/{correction_id}/revert",
        json={"request_id": "revert-first-city"},
    )

    assert retried_revert.status_code == 200
    assert retried_revert.json()["created"] is False
    assert retried_revert.json()["current_claim"]["trait_value"] == "Beijing"


def test_retried_old_relationship_revert_returns_the_actual_current_claim(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    triple_id = _seed_relationship(memory)
    client = _client(monkeypatch, memory)
    first = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "first-home-correction",
            "target": {"kind": "edge", "id": triple_id},
            "correction_kind": "record_error",
            "replacement": {
                "object_id": "place:shanghai",
                "object_type": "place",
            },
        },
    )
    assert first.status_code == 200
    correction_id = first.json()["correction"]["correction_id"]
    reverted = client.post(
        f"/api/memory/l2/corrections/{correction_id}/revert",
        json={"request_id": "revert-first-home"},
    )
    assert reverted.status_code == 200
    second = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "second-home-correction",
            "target": {"kind": "edge", "id": triple_id},
            "correction_kind": "record_error",
            "replacement": {
                "object_id": "place:beijing",
                "object_type": "place",
            },
        },
    )
    assert second.status_code == 200

    retried_revert = client.post(
        f"/api/memory/l2/corrections/{correction_id}/revert",
        json={"request_id": "revert-first-home"},
    )

    assert retried_revert.status_code == 200
    assert retried_revert.json()["created"] is False
    assert retried_revert.json()["current_claim"]["object_id"] == "place:beijing"


def test_memory_correction_api_rejects_unbounded_user_input(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)
    base = {
        "request_id": "bounded-correction",
        "target": {"kind": "assertion", "id": assertion_id},
        "correction_kind": "scope_refinement",
    }

    oversized_value = client.post(
        "/api/memory/l2/corrections",
        json={**base, "replacement": {"value": "x" * 2001}, "scope": {"project": "Magi"}},
    )
    oversized_scope = client.post(
        "/api/memory/l2/corrections",
        json={**base, "replacement": {"value": "Shanghai"}, "scope": {"project": "x" * 201}},
    )
    invalid_timestamp = client.post(
        "/api/memory/l2/corrections",
        json={
            **base,
            "correction_kind": "situation_changed",
            "replacement": {"value": "Shanghai"},
            "effective_at": 0,
        },
    )

    assert oversized_value.status_code == 422
    assert oversized_scope.status_code == 422
    assert invalid_timestamp.status_code == 422


def test_assertion_correction_api_rejects_unknown_replacement_fields(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "assertion-unknown-replacement-field",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "record_error",
            "replacement": {
                "value": "Shanghai",
                "object_id": "place:shanghai",
            },
        },
    )

    assert response.status_code == 422
    assert "Unsupported assertion replacement fields" in str(response.json()["detail"])


def test_memory_correction_api_returns_stable_time_boundary_code(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    assert memory.l2 is not None
    assertion = asyncio.run(memory.l2.get_tom_assertion(assertion_id=assertion_id))
    client = _client(monkeypatch, memory)

    response = client.post(
        "/api/memory/l2/corrections",
        json={
            "request_id": "correction-before-start",
            "target": {"kind": "assertion", "id": assertion_id},
            "correction_kind": "situation_changed",
            "replacement": {"value": "Shanghai"},
            "effective_at": float(assertion["first_inferred_at"]) - 1,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "effective_at_before_target"


def test_memory_correction_api_binds_request_id_to_original_intent(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    assertion_id = _seed_assertion(memory)
    client = _client(monkeypatch, memory)
    request = {
        "request_id": "bound-correction-request",
        "target": {"kind": "assertion", "id": assertion_id},
        "correction_kind": "record_error",
        "replacement": {"value": "Shanghai"},
        "reason": "The old city was incorrect",
    }

    created = client.post("/api/memory/l2/corrections", json=request)
    retried = client.post("/api/memory/l2/corrections", json=request)
    changed = client.post(
        "/api/memory/l2/corrections",
        json={**request, "replacement": {"value": "Beijing"}},
    )

    assert created.status_code == 200
    assert created.json()["created"] is True
    assert retried.status_code == 200
    assert retried.json()["created"] is False
    assert (
        retried.json()["correction"]["correction_id"]
        == created.json()["correction"]["correction_id"]
    )
    assert changed.status_code == 409
    assert changed.json()["detail"] == "request_id was already used for a different correction"


def test_memory_correction_routes_are_publicly_reachable() -> None:
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if hasattr(route, "methods"):
            route_methods.setdefault(route.path, set()).update(route.methods)

    assert route_methods["/l2/corrections"] == {"GET", "POST"}
    assert route_methods["/l2/corrections/{correction_id}/revert"] == {"POST"}
