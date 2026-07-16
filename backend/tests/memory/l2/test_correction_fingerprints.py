"""Tests for deterministic memory correction identities."""

from _shared.context_scope import context_scope
from magi.memory.l2.corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    canonical_claim_value,
    canonical_scope_json,
    relationship_claim_fingerprint,
    relationship_slot_key,
    relationship_triple_id,
    scope_key,
)


def test_assertion_fingerprint_normalizes_equivalent_values() -> None:
    slot = assertion_slot_key(
        entity_type="user",
        entity_id="user:local_user",
        trait_name="identity.location.home",
    )

    first = assertion_claim_fingerprint(
        slot_key_value=slot,
        trait_value="  ShangHai  ",
    )
    second = assertion_claim_fingerprint(
        slot_key_value=slot,
        trait_value="shanghai",
    )

    assert first == second
    assert slot.startswith("assertion_slot_")


def test_structured_values_and_scopes_are_order_independent() -> None:
    first_scope = context_scope(project="magi", activity="coding")
    second_scope = {"all_of": list(reversed(first_scope["all_of"]))}

    assert canonical_scope_json(first_scope) == canonical_scope_json(second_scope)
    assert scope_key(first_scope) == scope_key(second_scope)
    assert canonical_claim_value('{"b": 2, "a": 1}') == '{"a":1,"b":2}'


def test_relationship_row_identity_isolated_by_non_global_scope() -> None:
    global_id = relationship_triple_id(
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="topic:rust",
    )
    project_a_id = relationship_triple_id(
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="topic:rust",
        scope_key_value=scope_key(context_scope(project="project-a")),
    )
    project_b_id = relationship_triple_id(
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="topic:rust",
        scope_key_value=scope_key(context_scope(project="project-b")),
    )

    assert len({global_id, project_a_id, project_b_id}) == 3


def test_relationship_slots_keep_nonexclusive_objects_isolated() -> None:
    magi_slot = relationship_slot_key(
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="project:magi",
    )
    codex_slot = relationship_slot_key(
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="tool:codex",
    )

    assert magi_slot != codex_slot
    assert relationship_claim_fingerprint(
        slot_key_value=magi_slot,
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="project:magi",
    ) != relationship_claim_fingerprint(
        slot_key_value=codex_slot,
        subject_id="user:local_user",
        predicate="LIKES",
        object_id="tool:codex",
    )


def test_exclusive_relationships_can_share_one_slot() -> None:
    shanghai = relationship_slot_key(
        subject_id="user:local_user",
        predicate="LIVES_IN",
        object_id="place:shanghai",
        predicate_slot="home_location",
    )
    hangzhou = relationship_slot_key(
        subject_id="user:local_user",
        predicate="LIVES_IN",
        object_id="place:hangzhou",
        predicate_slot="home_location",
    )

    assert shanghai == hangzhou
