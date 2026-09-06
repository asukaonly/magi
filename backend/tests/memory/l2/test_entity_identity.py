"""Entity identity must survive replay without merging unrelated names."""

import pytest

from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.identity import canonical_entity_id
from magi.memory.l2.pipeline.utils import L2PipelineUtilityMixin


@pytest.mark.asyncio
async def test_unicode_names_with_the_same_ascii_suffix_remain_separate(tmp_path):
    catalog = L2EntityCatalog(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    pipeline = L2PipelineUtilityMixin()
    names = ["动态 (2)", "垃圾邮件 (2)", "星际争霸2", "流浪地球2"]
    ids = [pipeline._build_canonical_entity_id(entity_type="media", canonical_name=n) for n in names]
    assert len(set(ids)) == len(names)
    for _ in range(2):
        for name, entity_id in zip(names, ids):
            await catalog.upsert_entity(
                entity_id=entity_id, entity_type="media", canonical_name=name
            )
    rows = await catalog.list_entities(limit=10)
    assert {r["canonical_name"] for r in rows} == set(names)
    assert len(rows) == 4


def test_identity_normalization_preserves_type_and_name_distinctions():
    assert canonical_entity_id("media", "  ＡＢＣ  ２ ") == canonical_entity_id("media", "abc 2")
    assert canonical_entity_id("media", "星际2") != canonical_entity_id("media", "星际3")
    assert canonical_entity_id("media", "a-b") != canonical_entity_id("media", "a b")
    assert canonical_entity_id("media", "Apple") != canonical_entity_id("organization", "Apple")


@pytest.mark.asyncio
async def test_name_change_requires_explicit_identity_authority(tmp_path):
    catalog = L2EntityCatalog(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    entity_id = canonical_entity_id("media", "星际争霸2")
    await catalog.upsert_entity(entity_id=entity_id, entity_type="media", canonical_name="星际争霸2")
    with pytest.raises(ValueError, match="different canonical name"):
        await catalog.upsert_entity(entity_id=entity_id, entity_type="media", canonical_name="流浪地球2")
    await catalog.upsert_entity(
        entity_id=entity_id, entity_type="media", canonical_name="StarCraft II", allow_rename=True
    )
    rows = await catalog.list_entities(limit=10)
    assert [(r["entity_id"], r["canonical_name"]) for r in rows] == [(entity_id, "StarCraft II")]


@pytest.mark.asyncio
async def test_namespaced_source_keys_and_homonyms_are_distinct(tmp_path):
    from magi.memory.l2.entities.identity import entity_hint_id
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    hint = {"mention_text": "张伟", "entity_type": "person", "source_entity_key": "42"}
    a = entity_hint_id(hint, source="contacts", event_id="one")
    assert a == entity_hint_id(hint, source="contacts", event_id="two")
    b = entity_hint_id(hint, source="calendar", event_id="one")
    c = entity_hint_id({**hint, "source_entity_key": "43"}, source="contacts", event_id="one")
    assert len({a, b, c}) == 3
    catalog = L2EntityCatalog(db_path=str(tmp_path / "entities.db"))
    for identity in (a, b, c):
        await catalog.upsert_entity(entity_id=identity, canonical_name="张伟", entity_type="person")
    pipeline = L2Pipeline.__new__(L2Pipeline)
    pipeline._entity_catalog = catalog
    index = await pipeline._build_catalog_name_index()
    assert "张伟" not in index
    assert index[a] == a
    assert await pipeline._try_alias_resolution("张伟", "person") is None


@pytest.mark.asyncio
async def test_unresolved_homonyms_do_not_share_identity_or_replay_count(tmp_path):
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    pipeline = L2Pipeline.__new__(L2Pipeline)
    pipeline._entity_catalog = L2EntityCatalog(db_path=str(tmp_path / "entities.db"))
    args = dict(mention={}, entity_type="person", mention_text="王伟", mention_confidence=0.95)
    first = await pipeline._finalize_unresolved_entity(**args, source_event_ids=["event1"])
    second = await pipeline._finalize_unresolved_entity(**args, source_event_ids=["event2"])
    replay = await pipeline._finalize_unresolved_entity(**args, source_event_ids=["event1"])
    assert first == replay
    assert first[0] != second[0]
