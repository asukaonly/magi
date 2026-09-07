"""Entity semantics are model-owned; names and catalog identities are host-owned."""

import pytest

from magi.memory.l2.entity_names import valid_entity_name, MAX_ENTITY_NAME_CHARS
from magi.memory.l2.models import L2Phase1Entity, L2Phase1Result
from magi.memory.l2.pipeline.entity_grounding import normalize_phase1_entity_contract
from .test_phase1_entity_grounding import _entity, _window
from .test_pipeline import _build_pipeline, _make_memory_event


@pytest.mark.parametrize("name", ["X", "R", "1984", "Home", "!!!", "I Want to Hold Your Hand", "我想吃掉你的胰脏"])
def test_grounded_named_referents_are_not_rejected_by_their_wording(name):
    payload = {"entities": [_entity(name, name, "media")]}
    normalize_phase1_entity_contract(payload, _window(f"作品《{name}》"))
    assert payload["entities"][0]["normalized_name"] == name
    assert valid_entity_name(name)


@pytest.mark.parametrize("name", ["", "  ", "a\nb", "a\x00b", "a" * (MAX_ENTITY_NAME_CHARS + 1)])
def test_invalid_entity_name_shapes_are_rejected(name):
    assert not valid_entity_name(name)


def test_missing_referent_kind_does_not_default_to_catalog_authority():
    entity = _entity("Home", "Home", "media")
    entity.pop("referent_kind")
    payload = {"entities": [entity]}
    normalize_phase1_entity_contract(payload, _window("我看过 Home"))
    assert payload["entities"] == []
    assert payload["diagnostics"]["rejected_non_entity_count"] == 1


@pytest.mark.asyncio
async def test_short_grounded_alias_is_kept_and_catalog_collision_is_rejected(tmp_path):
    pipeline = await _build_pipeline(temp_dir=str(tmp_path))
    await pipeline._entity_catalog.upsert_entity(
        entity_id="software:youtube", canonical_name="YouTube", entity_type="software"
    )
    event = _make_memory_event(
        event_id="evt-alias", content="International Business Machines (IBM), seen on YouTube"
    )
    resolved = await pipeline._resolve_phase1_entities(
        event,
        L2Phase1Result(entities=[L2Phase1Entity(
            surface="International Business Machines", normalized_name="International Business Machines",
            entity_type="organization", alias_signals=["IBM", "YouTube"], confidence=0.95,
        )]),
        evidence_event_ids=[event.event_id], evidence_events=[event],
    )
    assert len(resolved) == 1
    entity_id = resolved[0].resolved_entity_id
    short_alias = await pipeline._entity_catalog.resolve_alias("IBM")
    assert short_alias["entity_id"] == entity_id
    platform = await pipeline._entity_catalog.resolve_alias("YouTube")
    assert platform["decision"] == "match"
    assert platform["entity_id"] == "software:youtube"
