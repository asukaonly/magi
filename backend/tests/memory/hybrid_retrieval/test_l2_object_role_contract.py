"""Catalog identity must not invent a query's exact object role."""
from __future__ import annotations

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.models import L2Conditions, L2SemanticFrame
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.store import L2CognitionStore
from memory.hybrid_retrieval.test_assertion_relevance import _seed


@pytest.fixture
async def stored_preferences(tmp_path):
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    catalog = L2EntityCatalog(db_path=db_path)
    await catalog.initialize()
    for entity_id, name in (("other:category", "音乐"), ("other:a7d3", "爵士乐"), ("other:b8d4", "茶")):
        await catalog.upsert_entity(entity_id=entity_id, canonical_name=name, entity_type="other")
    jazz = await _seed(store, "affinity", "用户喜欢爵士音乐", trait_value="like", target_entity_id="other:a7d3", target_entity_type="other")
    await _seed(store, "affinity", "用户喜欢茶", trait_value="like", target_entity_id="other:b8d4", target_entity_type="other")
    return L2Handler(store, entity_catalog=catalog), jazz


@pytest.mark.asyncio
async def test_catalog_category_does_not_filter_specific_preference_before_ranking(stored_preferences):
    handler, jazz = stored_preferences
    result = await handler.execute(L2Conditions(
        content_query="我喜欢什么音乐", subject_hint="self", predicate_family="preference",
        semantic_frame=L2SemanticFrame(query_family="affinity", answer_kind="topic", subject_scope="self", entity_mentions=["音乐"]),
        include_relationships=False, include_tom_snapshot=False,
    ), user_id="local_user")
    assert result["trace"]["grounding_plan"]["object_entity_ids"] == []
    # Both governed facts reach ranking; category membership is not exact identity.
    # With no semantic model, music -> jazz is intentionally not a lexical match.
    assert result["trace"]["assertion_retrieval"]["candidate_count"] == 2
    assert result["assertions"] == []


@pytest.mark.asyncio
async def test_explicit_object_role_uses_catalog_name_for_opaque_id(stored_preferences):
    handler, jazz = stored_preferences
    result = await handler.execute(L2Conditions(
        content_query="我喜欢爵士乐吗", subject_hint="self", predicate_family="preference",
        semantic_frame=L2SemanticFrame(query_family="affinity", answer_kind="topic", subject_scope="self", object_mentions=["爵士乐"]),
        include_relationships=False, include_tom_snapshot=False,
    ), user_id="local_user")
    assert result["trace"]["grounding_plan"]["object_entity_ids"] == ["other:a7d3"]
    assert [row["assertion_id"] for row in result["assertions"]] == [jazz]
