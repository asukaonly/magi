from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertions.assertion_rekey_coordinator import (
    AssertionEntityRekeyCoordinator,
)
from magi.memory.l2.corrections.fingerprints import relationship_triple_id
from magi.memory.l2.graph.relationship_rekey_coordinator import (
    RelationshipIdentityRekeyCoordinator,
)
from magi.memory.l2.store import L2CognitionStore


def _migrate_memory_schema(db_path: str) -> None:
    from alembic import command

    from magi.db.runner import MIGRATION_TARGETS, _build_config

    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    command.upgrade(_build_config(target, Path(db_path)), "head")


async def _store(tmp_path: Path) -> L2CognitionStore:
    db_path = str(tmp_path / "memory.db")
    _migrate_memory_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store


async def _relationship(store: L2CognitionStore) -> str:
    return await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="LIKES",
        object_id="food:temporary",
        object_type="food",
        evidence_event_ids=["event-1"],
        confidence=0.9,
        observed_at=time.time(),
        source_type="chat",
    )


async def _assertion(store: L2CognitionStore) -> str:
    now = time.time()
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "person:temporary",
            "entity_type": "person",
            "trait_family": "preference_profile",
            "trait_name": "food.preference",
            "trait_value": "ramen",
            "confidence_score": 0.9,
            "evidence_events": ["event-1"],
            "volatility_index": 0.2,
            "source_domain": "chat",
            "inference_depth": "direct",
            "validation_state": "corroborated",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )


@pytest.mark.asyncio
async def test_identity_rekey_coordinators_require_caller_owned_transactions(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)

    async with sqlite_connection_async(store.db_path) as db:
        with pytest.raises(RuntimeError, match="Relationship identity rekey"):
            await RelationshipIdentityRekeyCoordinator(db).rekey(
                source_triple_id="missing",
                subject_id="user:self",
                predicate="LIKES",
                object_id="food:canonical",
                now=time.time(),
            )
        with pytest.raises(RuntimeError, match="Assertion identity rekey"):
            await AssertionEntityRekeyCoordinator(db).rekey(
                source_entity_id="person:temporary",
                target_entity_id="person:canonical",
                now=time.time(),
            )


@pytest.mark.asyncio
async def test_relationship_rekey_rolls_back_and_retries_idempotently(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    source_id = await _relationship(store)
    target_id = relationship_triple_id(
        subject_id="user:self",
        predicate="LIKES",
        object_id="food:canonical",
        scope_key_value="global",
    )

    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        await RelationshipIdentityRekeyCoordinator(db).rekey(
            source_triple_id=source_id,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:canonical",
            now=time.time(),
        )
        await db.rollback()

    assert await store.get_relationship(triple_id=source_id) is not None
    assert await store.get_relationship(triple_id=target_id) is None

    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        first = await RelationshipIdentityRekeyCoordinator(db).rekey(
            source_triple_id=source_id,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:canonical",
            now=time.time(),
        )
        await db.commit()
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        repeated = await RelationshipIdentityRekeyCoordinator(db).rekey(
            source_triple_id=target_id,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:canonical",
            now=time.time(),
        )
        await db.commit()
        async with db.execute(
            "SELECT triple_id, evidence_event_ids FROM knowledge_graph WHERE triple_id = ?",
            (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        async with db.execute(
            "SELECT COUNT(*) FROM knowledge_graph WHERE subject_id = ? AND predicate = ?",
            ("user:self", "LIKES"),
        ) as cursor:
            count = int((await cursor.fetchone())[0])

    assert first.triple_id == target_id
    assert repeated.triple_id == target_id
    assert row is not None
    assert json.loads(str(row[1])) == ["event-1"]
    assert count == 1


@pytest.mark.asyncio
async def test_assertion_rekey_rolls_back_and_retries_idempotently(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    assertion_id = await _assertion(store)

    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        await AssertionEntityRekeyCoordinator(db).rekey(
            source_entity_id="person:temporary",
            target_entity_id="person:canonical",
            now=time.time(),
        )
        await db.rollback()

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original is not None
    assert original["entity_id"] == "person:temporary"

    for _ in range(2):
        async with sqlite_connection_async(store.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await AssertionEntityRekeyCoordinator(db).rekey(
                source_entity_id="person:temporary",
                target_entity_id="person:canonical",
                now=time.time(),
            )
            await db.commit()

    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            """
            SELECT entity_id, evidence_events
            FROM tom_trait_assertions
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        ) as cursor:
            row = await cursor.fetchone()
        async with db.execute(
            "SELECT COUNT(*) FROM tom_trait_assertions WHERE entity_id = ?",
            ("person:canonical",),
        ) as cursor:
            count = int((await cursor.fetchone())[0])

    assert row is not None
    assert row[0] == "person:canonical"
    assert json.loads(str(row[1])) == ["event-1"]
    assert count == 1


@pytest.mark.asyncio
async def test_competing_relationship_rekeys_converge_after_write_lock(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    source_id = await _relationship(store)
    target_id = relationship_triple_id(
        subject_id="user:self",
        predicate="LIKES",
        object_id="food:canonical",
        scope_key_value="global",
    )
    contender_started = asyncio.Event()

    async with sqlite_connection_async(store.db_path) as owner:
        await owner.execute("BEGIN IMMEDIATE")
        owner_result = await RelationshipIdentityRekeyCoordinator(owner).rekey(
            source_triple_id=source_id,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:canonical",
            now=time.time(),
        )

        async def contend() -> object:
            async with sqlite_connection_async(store.db_path) as contender:
                contender_started.set()
                await contender.execute("BEGIN IMMEDIATE")
                try:
                    return await RelationshipIdentityRekeyCoordinator(contender).rekey(
                        source_triple_id=source_id,
                        subject_id="user:self",
                        predicate="LIKES",
                        object_id="food:canonical",
                        now=time.time(),
                    )
                finally:
                    await contender.commit()

        contender_task = asyncio.create_task(contend())
        await contender_started.wait()
        await owner.commit()
        contender_result = await contender_task

    assert owner_result.triple_id == target_id
    assert getattr(contender_result, "triple_id") is None
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM knowledge_graph WHERE triple_id = ?",
            (target_id,),
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 1
