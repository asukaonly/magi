"""Query prose cannot change the direction of governed relationship reads."""
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
from magi.memory.hybrid_retrieval.l2_intent import _parse_semantic_frame, enrich_l2_conditions
from magi.memory.hybrid_retrieval.l2_query_execution import _build_query_plan
from magi.memory.hybrid_retrieval.models import L2Conditions


@pytest.mark.parametrize("query", ["谁认识我", "不要查谁认识我", "他引用了 who knows me", "a relationship example"])
def test_unknown_direction_keeps_both_endpoints(query):
    plan = build_grounding_plan(L2Conditions(content_query=query), resolved_entities=[], user_id="u1")
    assert plan.relation_direction == "both"


@pytest.mark.parametrize("direction", ["outgoing", "incoming", "both", "invalid", None])
def test_only_valid_typed_direction_restricts_endpoints(direction):
    frame = _parse_semantic_frame({
        "query_family": "relationship", "subject_scope": "self", "answer_kind": "person",
        "relation_direction": direction,
    })
    conditions = L2Conditions(content_query="不要按关键词猜方向", semantic_frame=frame)
    enrich_l2_conditions(conditions)
    expected = direction if direction in {"outgoing", "incoming", "both"} else "both"
    assert build_grounding_plan(conditions, resolved_entities=[], user_id="u1").relation_direction == expected
    conditions.relation_direction = "outgoing"
    assert build_grounding_plan(conditions, resolved_entities=[], user_id="u1").relation_direction == "outgoing"


@pytest.mark.asyncio
async def test_direct_handler_derives_roles_before_entity_resolution():
    from types import SimpleNamespace
    frame = _parse_semantic_frame({
        "query_family": "relationship", "subject_scope": "self", "answer_kind": "person",
        "object_mentions": ["Morgan"], "relation_direction": "incoming",
    })
    async def resolve(conditions, **kwargs):
        assert conditions.entities == ["Morgan"]
        assert conditions.subject_hint == "self"
        return [{"entity_id": "person:morgan", "entity_type": "person", "surface": "Morgan", "match_source": "alias"}]
    host = SimpleNamespace(_resolve_entities=AsyncMock(side_effect=resolve), _embedding_service=None)
    plan = await _build_query_plan(host, L2Conditions(content_query="Morgan", semantic_frame=frame), time_range=None, user_id="u1")
    assert plan.subject_entity_ids == ["user:u1"]
    assert plan.relation_direction == "incoming"
    assert plan.predicate_family == "relationship"


@pytest.mark.parametrize("query", ["they both said hi", "别把他们共同当主体", "我引用过她的话"])
def test_word_fragments_do_not_assign_people_to_subject_roles(query):
    entities = [
        {"entity_id": "person:ann", "entity_type": "person", "canonical_name": "Ann"},
        {"entity_id": "person:joanna", "entity_type": "person", "canonical_name": "Joanna"},
    ]
    conditions = L2Conditions(content_query=query, predicate_family="relationship")
    assert build_grounding_plan(conditions, resolved_entities=entities, user_id="u1").subject_entity_ids == []


def test_explicit_subject_must_resolve_its_own_mention():
    conditions = L2Conditions(content_query="Ann", semantic_frame=_parse_semantic_frame({
        "query_family": "relationship", "subject_scope": "explicit", "subject_mentions": ["Ann"],
        "object_mentions": ["Joanna"], "answer_kind": "person",
    }))
    entities = [{"entity_id": "person:joanna", "entity_type": "person", "canonical_name": "Joanna"}]
    plan = build_grounding_plan(conditions, resolved_entities=entities, user_id="u1")
    assert plan.subject_entity_ids == []
    assert plan.object_entity_ids == ["person:joanna"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope, mentions, objects", [
    ("explicit", ["Unknown"], []),
    ("multi", ["Ann", "Unknown"], []),
    ("self", [], ["Unknown"]),
])
async def test_unresolved_roles_never_query_all_fact_subjects(scope, mentions, objects):
    from unittest.mock import MagicMock
    from magi.memory.hybrid_retrieval.l2_handler import L2Handler
    store = AsyncMock()
    catalog = MagicMock()
    catalog.resolve_query_entities = AsyncMock(return_value=[{
        "entity_id": "person:ann", "entity_type": "person", "canonical_name": "Ann", "match_source": "exact",
    }])
    # Unknown mentions resolve to no entity; a different participant still resolves.
    async def resolve(query, **kwargs):
        return [{"entity_id": "person:ann", "entity_type": "person", "canonical_name": "Ann", "match_source": "exact"}] if query == "Ann" else []
    catalog.resolve_query_entities.side_effect = resolve
    frame = _parse_semantic_frame({
        "query_family": "affinity", "subject_scope": scope, "subject_mentions": mentions,
        "object_mentions": objects, "answer_kind": "topic",
    })
    result = await L2Handler(store, entity_catalog=catalog).execute(
        L2Conditions(content_query="喜欢咖啡", semantic_frame=frame), user_id="u1",
    )
    assert result["relationships"] == result["assertions"] == result["entity_cards"] == []
    assert result["trace"]["grounding_plan"]["fact_abstention_reason"].startswith("unresolved_")
    store.iter_current_assertions.assert_not_called()
    store.list_current_relationships.assert_not_called()
    store.batch_list_current_relationships.assert_not_called()
    store.batch_get_tom_snapshots.assert_not_called()
