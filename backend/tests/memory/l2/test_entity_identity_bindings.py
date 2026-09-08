"""Source identity and classification evidence survive replay without silent retagging."""

import json

import aiosqlite
import pytest

from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.identity import scoped_entity_id


@pytest.fixture
async def catalog(tmp_path):
    return L2EntityCatalog(db_path=str(tmp_path / "memory.db"), vector_enabled=False)


@pytest.mark.asyncio
async def test_source_key_keeps_id_and_classification_when_model_changes_type(catalog):
    original = await catalog.upsert_entity(
        entity_id="old:opaque",
        canonical_name="Apple",
        entity_type="organization",
        source_namespace="music",
        source_key="42",
        source_event_ids=["e1"],
    )
    repeated = await catalog.upsert_entity(
        entity_id="group:new",
        canonical_name="Apple",
        entity_type="group",
        source_namespace="music",
        source_key="42",
        source_event_ids=["e2"],
    )
    assert repeated == original
    assert (await catalog.list_entities())[0]["entity_type"] == "organization"
    async with aiosqlite.connect(catalog.db_path) as db:
        review = await (
            await db.execute(
                "SELECT proposed_type, evidence_event_ids FROM entity_identity_reviews"
            )
        ).fetchone()
    assert review[0] == "group"
    assert json.loads(review[1]) == ["e2"]
    assert scoped_entity_id("group", "music", "42") == scoped_entity_id(
        "organization", "music", "42"
    )
    assert scoped_entity_id("group", "music", "42") != scoped_entity_id("group", "contacts", "42")


@pytest.mark.asyncio
async def test_redirect_is_resolved_and_forgotten_binding_cannot_recreate(catalog):
    await catalog.upsert_entity(
        entity_id="old",
        canonical_name="Apple",
        entity_type="brand",
        source_namespace="store",
        source_key="apple",
    )
    await catalog.upsert_entity(
        entity_id="winner", canonical_name="Apple Inc.", entity_type="organization"
    )
    async with aiosqlite.connect(catalog.db_path) as db:
        await db.execute(
            "INSERT INTO entity_identity_redirects VALUES ('old','winner','operation')"
        )
        await db.execute("DELETE FROM entity_catalog WHERE entity_id='old'")
        await db.commit()
    actual = await catalog.upsert_entity(
        entity_id="old", canonical_name="Apple", entity_type="brand", source_event_ids=["e2"]
    )
    assert actual == "winner"
    assert (await catalog.list_entities(entity_ids=["old"]))[0]["entity_id"] == "winner"
    await catalog.forget_entity_catalog("winner")
    with pytest.raises(ValueError, match="no longer available"):
        await catalog.upsert_entity(
            entity_id="new",
            canonical_name="Apple",
            entity_type="brand",
            source_namespace="store",
            source_key="apple",
            source_event_ids=["e3"],
        )


@pytest.mark.asyncio
async def test_type_proposal_replay_deduplicates_and_keeps_user_rejection(catalog):
    await catalog.upsert_entity(
        entity_id="opaque", canonical_name="Apple", entity_type="organization"
    )
    for event_id in ["e1", "e1", "e2"]:
        await catalog.record_mention(
            mention_text="Apple",
            normalized_surface="apple",
            entity_type="brand",
            evidence_event_ids=[event_id],
            evidence_text="Apple",
            resolved_entity_id="opaque",
            confidence=0.95,
        )
    async with aiosqlite.connect(catalog.db_path) as db:
        review = await (
            await db.execute("SELECT evidence_event_ids, version FROM entity_identity_reviews")
        ).fetchone()
        assert json.loads(review[0]) == ["e1", "e2"]
        assert review[1] == 2
        await db.execute("UPDATE entity_identity_reviews SET status='rejected'")
        await db.commit()
    await catalog.record_mention(
        mention_text="Apple",
        normalized_surface="apple",
        entity_type="brand",
        evidence_event_ids=["e3"],
        evidence_text="Apple",
        resolved_entity_id="opaque",
        confidence=0.95,
    )
    async with aiosqlite.connect(catalog.db_path) as db:
        assert (await (await db.execute("SELECT status FROM entity_identity_reviews")).fetchone())[
            0
        ] == "rejected"


def test_v52_migration_recovers_exact_source_binding_without_renaming(tmp_path):
    import sqlite3
    import uuid
    from alembic import command
    from magi.db.runner import MIGRATION_TARGETS, _build_config

    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    path = tmp_path / "memory.db"
    config = _build_config(target, path)
    command.upgrade(config, "v51_portrait_prompt_contract")
    source_key = "contact-42"
    old_id = (
        "person:source:"
        + uuid.uuid5(
            uuid.NAMESPACE_URL, json.dumps(["person", "contacts", source_key], ensure_ascii=False)
        ).hex
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO entity_catalog(entity_id, canonical_name, entity_type, created_at, updated_at) VALUES (?, 'Alice', 'person', 1, 1)",
            (old_id,),
        )
    with sqlite3.connect(tmp_path / "l1_events.db") as db:
        db.execute(
            "CREATE TABLE fact_events(id INTEGER PRIMARY KEY, event_id TEXT, source TEXT, metadata_json TEXT, deleted_at REAL, timestamp REAL)"
        )
        db.execute(
            "INSERT INTO fact_events VALUES (1,'e1','contacts',?,NULL,1)",
            (
                json.dumps(
                    {
                        "structured_entity_hints": [
                            {
                                "mention_text": "Alice",
                                "entity_type": "person",
                                "source_entity_key": source_key,
                            }
                        ]
                    }
                ),
            ),
        )
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT entity_id FROM entity_source_bindings").fetchone()[0] == old_id
        assert db.execute("SELECT entity_id, canonical_name FROM entity_catalog").fetchone() == (
            old_id,
            "Alice",
        )
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    command.downgrade(config, "v51_portrait_prompt_contract")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM entity_source_bindings").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_unkeyed_source_homonyms_use_distinct_ordinals_and_stable_replay(catalog):
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.events.events import Event, EventTypes

    pipeline = L2Pipeline.__new__(L2Pipeline)
    pipeline._entity_catalog = catalog
    event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            source="calendar",
            event_id="e-source",
            timestamp=1,
            data={"content": "Apple", "author_type": "user"},
        )
    )
    event.metadata_json = {
        "structured_entity_hints": [
            {"mention_text": "Apple", "entity_type": "organization"},
            {"mention_text": "Apple", "entity_type": "group"},
        ]
    }
    await pipeline._upsert_structured_hint_entities(event)
    rows = await catalog.list_entities()
    assert len(rows) == 2
    ids = {row["entity_id"] for row in rows}
    # Re-extraction can change classification but not the occurrence's durable identity.
    event.metadata_json["structured_entity_hints"][0] = {
        "mention_text": "Apple",
        "entity_type": "brand",
    }
    await pipeline._upsert_structured_hint_entities(event)
    assert {row["entity_id"] for row in await catalog.list_entities()} == ids
