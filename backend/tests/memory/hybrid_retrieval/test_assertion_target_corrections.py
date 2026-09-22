"""Correction authority retains an unchanged text target across source lifecycle."""

from __future__ import annotations

import time

import pytest

from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.models import L2Conditions
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.retrieval.assertion_targets import hydrate_assertion_targets
from memory.l2.test_preference_exclusions import _open, _read
from memory.l2.test_preference_lifecycle import _claim_response, _ingest_response

_TARGET = "安静的地方"
_SOURCE = "text-preference-source"
_SCOPE = {"all_of": [{"dimension": "project", "context_id": "ctx_project_" + "a" * 64}]}


@pytest.fixture
async def text_preference(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        text = f"我喜欢{_TARGET}"
        await _ingest_response(
            store, adapter, _SOURCE, text,
            _claim_response(_SOURCE, text, target=_TARGET, text_target=True),
        )
        yield store
    finally:
        await store.shutdown()


async def _recall(store, *, context_scope=None):
    result = await L2Handler(store.l2).execute(
        L2Conditions(
            content_query=_TARGET,
            subject_hint="self",
            predicate_family="preference",
            include_relationships=False,
            include_tom_snapshot=False,
            context_scope=context_scope or {},
        ),
        user_id="u1",
    )
    return result["assertions"]


async def _correct(store, *, request_id="first-correction", value="dislike", **kwargs):
    current = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
    result = await store.l2.apply_assertion_correction(
        assertion_id=current["assertion_id"],
        request_id=request_id,
        actor_id="user:u1",
        correction_kind=kwargs.pop("correction_kind", CorrectionKind.RECORD_ERROR),
        replacement_value=value,
        **kwargs,
    )
    assert result is not None
    return result


@pytest.mark.asyncio
async def test_manual_correction_target_survives_original_source_forget_and_second_correction(text_preference):
    store = text_preference
    assert len(await _recall(store)) == 1
    first = await _correct(store)
    assert first["correction"]["before"]["target"] == _TARGET
    corrected_id = first["current_assertion"]["assertion_id"]
    rows = await _recall(store)
    assert [(row["assertion_id"], row["trait_value"], row["target"]) for row in rows] == [
        (corrected_id, "dislike", _TARGET)
    ]
    assert not await _read(
        store,
        "SELECT 1 FROM l2_claim_projection_outcomes WHERE target_id = ? AND target_kind = 'assertion'",
        (corrected_id,),
    )

    await store.forget_source_events([_SOURCE])
    assert not await store.l2.list_grounded_claims()
    rows = await _recall(store)
    assert [(row["assertion_id"], row["trait_value"]) for row in rows] == [(corrected_id, "dislike")]

    second = await _correct(store, request_id="second-correction", value="like")
    assert second["correction"]["before"]["target"] == _TARGET
    rows = await _recall(store)
    assert [(row["assertion_id"], row["trait_value"], row["target"]) for row in rows] == [
        (second["current_assertion"]["assertion_id"], "like", _TARGET)
    ]


@pytest.mark.asyncio
async def test_forgetting_correction_source_uses_existing_authority_revert(text_preference):
    store = text_preference
    first = await _correct(store, source_event_id="feedback-source")
    corrected_id = first["current_assertion"]["assertion_id"]
    assert (await _recall(store))[0]["assertion_id"] == corrected_id

    await store.forget_source_events(["feedback-source"])
    rows = await _recall(store)
    assert len(rows) == 1
    assert rows[0]["trait_value"] == "like"
    assert rows[0]["assertion_id"] != corrected_id
    assert rows[0]["target"] == _TARGET
    await store.forget_source_events([_SOURCE])
    assert not await _recall(store)


@pytest.mark.asyncio
async def test_reverting_second_correction_preserves_first_authority_target(text_preference):
    store = text_preference
    first = await _correct(store)
    second = await _correct(store, request_id="second-correction", value="like")
    await store.l2.revert_assertion_correction(
        correction_id=second["correction"]["correction_id"],
        request_id="revert-second",
        actor_id="user:u1",
    )
    rows = await _recall(store)
    assert [(row["assertion_id"], row["trait_value"], row["target"]) for row in rows] == [
        (first["current_assertion"]["assertion_id"], "dislike", _TARGET)
    ]


@pytest.mark.asyncio
async def test_scope_refinement_retains_target_but_requires_matching_scope(text_preference):
    store = text_preference
    result = await _correct(
        store,
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        value="like",
        scope=_SCOPE,
    )
    assert not await _recall(store)
    rows = await _recall(store, context_scope=_SCOPE)
    assert [(row["assertion_id"], row["target"]) for row in rows] == [
        (result["current_assertion"]["assertion_id"], _TARGET)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("entity_id", "user:other"),
    ("slot_key", "slot-other"),
    ("target_entity_id", "concept:other"),
    ("target_entity_type", "other"),
    ("target_scope", "entity_bound"),
    ("trait_name", "preference.other"),
    ("previous_version_id", "assertion-other"),
    ("authority_ref", "correction:other"),
])
async def test_target_snapshot_does_not_cross_changed_assertion_identity(text_preference, field, value):
    store = text_preference
    first = await _correct(store)
    assertion = dict(first["current_assertion"])
    assertion.pop("target", None)
    assertion[field] = value
    await hydrate_assertion_targets(
        store.l2.db_path, [assertion], effective_at=time.time(), effective_range=None,
    )
    assert "target" not in assertion
