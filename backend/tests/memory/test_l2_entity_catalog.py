from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_exact_alias_mapping_resolves_shanghai_and_modu_to_same_entity():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        entity_id = await catalog.upsert_entity(
            canonical_name="Shanghai",
            entity_type="place",
            entity_id="place:shanghai",
        )
        await catalog.add_alias(entity_id=entity_id, alias_text="上海", confidence=1.0)
        await catalog.add_alias(entity_id=entity_id, alias_text="魔都", confidence=0.95)

        resolved_shanghai = await catalog.resolve_alias("上海", entity_type="place")
        resolved_modu = await catalog.resolve_alias("魔都", entity_type="place")

        assert resolved_shanghai["decision"] == "match"
        assert resolved_shanghai["entity_id"] == "place:shanghai"
        assert resolved_modu["decision"] == "match"
        assert resolved_modu["entity_id"] == "place:shanghai"


@pytest.mark.asyncio
async def test_ambiguous_alias_returns_unresolved():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        organization_id = await catalog.upsert_entity(
            canonical_name="Apple Inc.",
            entity_type="organization",
            entity_id="org:apple",
        )
        food_id = await catalog.upsert_entity(
            canonical_name="Apple Fruit",
            entity_type="food",
            entity_id="food:apple",
        )
        await catalog.add_alias(entity_id=organization_id, alias_text="apple", confidence=0.92)
        await catalog.add_alias(entity_id=food_id, alias_text="apple", confidence=0.91)

        resolved = await catalog.resolve_alias("apple")

        assert resolved["decision"] == "unresolved"
        assert resolved["entity_id"] is None
        assert resolved["candidate_count"] == 2


@pytest.mark.asyncio
async def test_low_confidence_alias_does_not_auto_merge():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai")
        await catalog.add_alias(entity_id="place:shanghai", alias_text="沪上", confidence=0.6)

        resolved = await catalog.resolve_alias("沪上", entity_type="place")

        assert resolved["decision"] == "unresolved"
        assert resolved["entity_id"] is None
        assert resolved["matched_confidence"] == 0.6


@pytest.mark.asyncio
async def test_record_mention_preserves_surface_form_and_evidence_event_ids():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        mention_id = await catalog.record_mention(
            mention_text="魔都",
            normalized_surface="魔都",
            entity_type="place",
            evidence_event_ids=["evt-1", "evt-2"],
            evidence_text="我很喜欢魔都",
            resolved_entity_id="place:shanghai",
            confidence=0.95,
        )

        mention = await catalog.get_mention(mention_id)

        assert mention["mention_text"] == "魔都"
        assert mention["normalized_surface"] == "魔都"
        assert mention["evidence_event_ids"] == ["evt-1", "evt-2"]
        assert mention["resolved_entity_id"] == "place:shanghai"


@pytest.mark.asyncio
async def test_list_entities_returns_canonical_names_and_aliases():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        await catalog.upsert_entity(canonical_name="Shanghai", entity_type="place", entity_id="place:shanghai")
        await catalog.add_alias(entity_id="place:shanghai", alias_text="上海", confidence=1.0)
        await catalog.add_alias(entity_id="place:shanghai", alias_text="魔都", confidence=0.95)

        entities = await catalog.list_entities(limit=10)

        assert entities == [
            {
                "entity_id": "place:shanghai",
                "canonical_name": "Shanghai",
                "entity_type": "place",
                "aliases": ["上海", "魔都"],
            }
        ]


@pytest.mark.asyncio
async def test_upsert_entity_normalizes_alias_entity_type_before_persistence():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        entity_id = await catalog.upsert_entity(
            canonical_name="West Lake Vinegar Fish",
            entity_type="dish",
            entity_id="dish:west-lake-vinegar-fish",
        )
        entities = await catalog.list_entities(limit=10)

        assert entity_id == "food:west-lake-vinegar-fish"
        assert entities == [
            {
                "entity_id": "food:west-lake-vinegar-fish",
                "canonical_name": "West Lake Vinegar Fish",
                "entity_type": "food",
                "aliases": [],
            }
        ]


@pytest.mark.asyncio
async def test_record_mention_normalizes_unknown_entity_type_to_other():
    from magi.memory.l2_entity_catalog import L2EntityCatalog

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "memory.db")
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()

        mention_id = await catalog.record_mention(
            mention_text="MysteryThing",
            normalized_surface="mysterything",
            entity_type="unknown_type",
            evidence_event_ids=["evt-1"],
            evidence_text="I saw MysteryThing",
            resolved_entity_id=None,
            confidence=0.4,
        )

        mention = await catalog.get_mention(mention_id)

        assert mention["entity_type"] == "other"
