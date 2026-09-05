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
