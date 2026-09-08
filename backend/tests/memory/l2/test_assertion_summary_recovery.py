"""Scoped recovery preserves source semantics, lifecycle and governance fences."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertion_display import decorate_assertion_display
from magi.memory.l2.assertions.summary_recovery import (
    AssertionSummaryRecoveryRequest,
    recover_assertion_summaries,
)
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.corrections.repository import MemoryCorrectionRepository
from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route
from magi.memory.l2.store import L2CognitionStore
from magi.user_profile.correction_derivation import UserProfileCorrectionDerivationHandlers
from magi.user_profile.models import UserPortraitProjection
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository


def _slot(*, subject="user:u1", target=None, predicate="LIKES", value=None, cue="unspecified", kind="stable_preference"):
    return derive_semantic_route(SemanticRouteInput(
        claim_id="claim:apple", subject_id=subject,
        subject_type="user" if subject == "user:u1" else "person",
        canonical_predicate=predicate, fact_kind=kind,
        object_type="other" if target else "literal", object_value=value or target,
        object_entity_id=target, temporal_cue=cue, specificity="concrete",
        target_from=None, target_to=None, raw_time_expression="", time_resolution="unscheduled",
    )).slot_key


async def _seed(store, *, cue="unspecified", polarity="positive", subject="user:u1"):
    target = "other:source:opaque-identity"
    catalog = L2EntityCatalog(db_path=store.db_path)
    await catalog.upsert_entity(entity_id=target, entity_type="other", canonical_name="苹果")
    if subject != "user:u1":
        await catalog.upsert_entity(entity_id=subject, entity_type="person", canonical_name="小王")
    assertion_id = await store.upsert_assertion_candidate({
        "entity_id": subject, "entity_type": "user" if subject == "user:u1" else "person",
        "trait_family": "preference_profile", "trait_name": "preference.affinity",
        "trait_value": "like", "confidence_score": 0.83, "evidence_events": ["event:apple"],
        "volatility_index": 0.2, "source_domain": "user_authored", "inference_depth": "direct",
        "validation_state": "corroborated", "first_inferred_at": 1_700_000_000.0,
        "last_validated_at": 1_700_000_000.0, "target_entity_id": target,
        "target_entity_type": "other", "temporal_scope": "recent", "decay_policy": "evidence_only",
        "natural_summary": "用户喜欢other:source:opaque-identity。",
        "semantic_route_slot_key": _slot(subject=subject, target=target, cue=cue),
    })
    assert isinstance(assertion_id, str)
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """INSERT INTO l2_grounded_claims (
                claim_id, identity_key, extractor_contract_version, evidence_rule_version,
                origin_attempt_key, user_id, subject_ref, subject_type, canonical_predicate,
                fact_kind, object_type, polarity, specificity, confidence, object_value_json,
                object_surface, temporal_cue, availability, created_at, updated_at
            ) VALUES ('claim:apple', 'identity:apple', 6, 3, 'attempt:apple', 'u1', ?, ?,
                'LIKES', 'stable_preference', 'other', ?, 'concrete', 0.83, ?, ?, ?, 'active', 1, 1)""",
            (subject, "user" if subject == "user:u1" else "person", polarity,
             json.dumps(target), target, cue),
        )
        await db.execute(
            """INSERT INTO l2_claim_entity_refs
            (claim_id, ref_role, entity_id, resolution_version, created_at)
            VALUES ('claim:apple', 'object', ?, 1, 1)""", (target,),
        )
        await db.execute(
            """INSERT INTO l2_claim_evidence (
                claim_id, event_id, link_role, required_for_grounding, event_time,
                timestamp_confidence, timestamp_quality, evidence_rule_version,
                evidence_mode, source_type, source_domain, author_type, evidence_locator_json,
                evidence_class, created_at
            ) VALUES ('claim:apple', 'event:apple', 'supporting', 1, 1700000000,
                'exact', 'exact', 3, 'direct', 'chat', 'user_authored', 'user',
                '{"evidence_text":"我蛮喜欢苹果的"}', 'user_self_report', 1)""",
        )
        await db.execute(
            """INSERT INTO l2_claim_projection_outcomes (
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                outcome, created_at, target_slot_key
            ) VALUES ('receipt:apple', 'claim:apple', 'attempt:apple', 'assertion', ?, 'projected', 1, ?)""",
            (assertion_id, _slot(subject=subject, target=target, cue=cue)),
        )
        await db.commit()
    row = await _row(store.db_path, "tom_trait_assertions", "assertion_id", assertion_id)
    return AssertionSummaryRecoveryRequest(assertion_id, row["updated_at"], row["natural_summary"])


async def _row(db_path, table, key, value):
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"SELECT * FROM {table} WHERE {key} = ?", (value,)) as cursor:
            return dict(await cursor.fetchone())


@pytest.mark.asyncio
async def test_scoped_recovery_preserves_claim_and_lifecycle_reloads_and_rebuilds_portrait(l2_store_with_schema):
    store = l2_store_with_schema
    request = await _seed(store)
    claim_before = await _row(store.db_path, "l2_grounded_claims", "claim_id", "claim:apple")
    assertion_before = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    unrelated = {
        **assertion_before,
        "assertion_id": "assertion:unrelated",
        "entity_id": "user:unrelated",
        "slot_key": "slot:unrelated",
        "claim_fingerprint": "fingerprint:unrelated",
        "natural_summary": "An unrelated retained description.",
    }
    async with sqlite_connection_async(store.db_path) as db:
        columns = ", ".join(unrelated)
        placeholders = ", ".join("?" for _ in unrelated)
        await db.execute(
            f"INSERT INTO tom_trait_assertions ({columns}) VALUES ({placeholders})",
            tuple(unrelated.values()),
        )
        await db.commit()
    portrait_repo = UserPortraitProjectionRepository(store.db_path)
    await portrait_repo.upsert(UserPortraitProjection(
        user_id="u1", entity_id="user:u1", prompt_summary=[request.expected_summary],
        source_revision=(await _row(store.db_path, "memory_subject_revisions", "subject_key", "user:u1"))["revision"],
        recent={"items": [{"assertion_id": request.assertion_id, "label": request.expected_summary}]},
    ))
    preview = await recover_assertion_summaries(store.db_path, requests=[request], language="zh")
    assert preview.items[0].status == "would_rebuild"
    assert preview.items[0].rebuilt_summary == "用户喜欢苹果。"
    assert await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id) == assertion_before

    result = await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert result.items[0].status == "rebuilt"
    assert await _row(store.db_path, "l2_grounded_claims", "claim_id", "claim:apple") == claim_before
    assertion_after = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    assert assertion_after["natural_summary"] == "用户喜欢苹果。"
    assert {key: value for key, value in assertion_after.items() if key not in {"natural_summary", "updated_at"}} == {
        key: value for key, value in assertion_before.items() if key not in {"natural_summary", "updated_at"}
    }
    assert await _row(store.db_path, "tom_trait_assertions", "assertion_id", "assertion:unrelated") == unrelated
    assert await portrait_repo.get("u1") is None

    restarted = L2CognitionStore(db_path=store.db_path)
    await restarted.initialize()
    assertions = await restarted.list_current_assertions(entity_id="user:u1", context_scope=None)
    with patch("magi.memory.l2.assertion_display.effective_app_language_code", return_value="zh"):
        decorated = await decorate_assertion_display(store.db_path, assertions)
        assert decorated[0]["display_text"] == "用户喜欢苹果。"
        assert decorated[0]["display_status"] == "complete"
        handlers = UserProfileCorrectionDerivationHandlers(db_path=store.db_path, l2_store=restarted)
        job = {"target_key": "user:u1", "target_revision": result.subject_revisions["user:u1"]}
        await handlers.rebuild_profile(job)
        await handlers.rebuild_portrait(job)
    restored = await portrait_repo.get("u1")
    assert restored is not None
    assert "苹果" in json.dumps(restored.prompt_summary, ensure_ascii=False)
    assert "other:source:opaque-identity" not in json.dumps(restored.prompt_summary, ensure_ascii=False)
    assert "苹果" in json.dumps(restored.recent, ensure_ascii=False)
    assert (await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False)).items[0].status == "snapshot_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize(("cue", "subject", "expected"), [
    ("unspecified", "person:wang", "小王喜欢苹果。"),
    ("recent", "user:u1", "用户最近喜欢苹果。"),
    ("one_off", "user:u1", "用户曾在一次经历中喜欢苹果。"),
])
async def test_recovery_uses_claim_time_and_subject(l2_store_with_schema, cue, subject, expected):
    request = await _seed(l2_store_with_schema, cue=cue, subject=subject)
    result = await recover_assertion_summaries(l2_store_with_schema.db_path, requests=[request], language="zh")
    assert result.items[0].rebuilt_summary == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("mutation", "status"), [
    ("UPDATE tom_trait_assertions SET user_feedback = 'confirmed'", "user_governed"),
    ("UPDATE tom_trait_assertions SET status = 'archived'", "assertion_not_active"),
    ("UPDATE l2_claim_projection_outcomes SET invalidated_at = 2", "claim_support_unavailable"),
    ("UPDATE tom_trait_assertions SET trait_value = 'dislike'", "claim_semantics_changed"),
    ("UPDATE l2_claim_entity_refs SET entity_id = 'other:changed'", "claim_identity_changed"),
    ("DELETE FROM l2_claim_evidence", "claim_evidence_unavailable"),
    ("DELETE FROM entity_catalog WHERE entity_type = 'other'", "claim_text_incomplete_or_ambiguous"),
    ("INSERT INTO memory_source_event_tombstones(event_id, reason, created_at) VALUES ('event:apple', 'user_deleted', 2)", "source_governed"),
    ("INSERT INTO l2_projection_jobs(event_id, source, event_type, status, created_at, updated_at) VALUES ('event:apple', 'chat', 'UserMessage', 'running', 1, 1)", "source_projection_not_complete"),
    ("INSERT INTO l2_projection_jobs(event_id, source, event_type, status, created_at, updated_at) VALUES ('event:apple', 'chat', 'UserMessage', 'pending', 1, 1)", "source_projection_not_complete"),
])
async def test_recovery_respects_governance_and_unresolved_names(l2_store_with_schema, mutation, status):
    store = l2_store_with_schema
    request = await _seed(store)
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(mutation)
        await db.commit()
    result = await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert result.items[0].status == status
    assert result.subject_revisions == {}
    row = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    assert row["natural_summary"] == request.expected_summary


@pytest.mark.asyncio
async def test_recovery_never_turns_negative_claim_into_positive_summary(l2_store_with_schema):
    request = await _seed(l2_store_with_schema, polarity="negative")
    result = await recover_assertion_summaries(l2_store_with_schema.db_path, requests=[request], dry_run=False, language="zh")
    assert result.items[0].status == "claim_semantics_changed"


@pytest.mark.asyncio
async def test_recovery_requires_explicit_unique_scope(l2_store_with_schema):
    store = l2_store_with_schema
    with pytest.raises(ValueError, match="explicit"):
        await recover_assertion_summaries(store.db_path, requests=[])
    request = await _seed(store)
    with pytest.raises(ValueError, match="unique"):
        await recover_assertion_summaries(store.db_path, requests=[request, request])
    changed = replace(request, expected_summary="unobserved")
    result = await recover_assertion_summaries(store.db_path, requests=[changed], dry_run=False)
    assert result.items[0].status == "snapshot_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize(("predicate", "family", "trait", "value", "expected"), [
    ("PREFERRED_FORM_OF_ADDRESS", "communication_profile", "communication.address.preferred",
     "other:source:opaque-identity", "用户希望被称为other:source:opaque-identity。"),
    ("BIRTH_DATE", "identity_profile", "identity.birth_date", "2000-01-02", "用户生日是2000-01-02。"),
    ("PLANS_TO", "goal_profile", "goal.intent", "下周修好电脑", "用户计划下周修好电脑。"),
])
async def test_recovery_keeps_literal_value_contracts(l2_store_with_schema, predicate, family, trait, value, expected):
    store = l2_store_with_schema
    request = await _seed(store)
    slot = _slot(predicate=predicate, value=value, kind="future_intent" if predicate == "PLANS_TO" else "explicit_fact")
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """UPDATE l2_grounded_claims SET canonical_predicate = ?, object_value_json = ?,
            object_surface = ?, fact_kind = ?, object_type = 'literal'""",
            (predicate, json.dumps(value), value, "future_intent" if predicate == "PLANS_TO" else "explicit_fact"),
        )
        await db.execute("DELETE FROM l2_claim_entity_refs")
        await db.execute(
            """UPDATE tom_trait_assertions SET trait_family = ?, trait_name = ?, trait_value = ?,
            target_entity_id = '', target_entity_type = '', slot_key = ?""", (family, trait, value, slot),
        )
        await db.execute("UPDATE l2_claim_projection_outcomes SET target_slot_key = ?", (slot,))
        await db.commit()
    before = await _row(store.db_path, "l2_grounded_claims", "claim_id", "claim:apple")
    result = await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert result.items[0].rebuilt_summary == expected
    assert await _row(store.db_path, "l2_grounded_claims", "claim_id", "claim:apple") == before


@pytest.mark.asyncio
async def test_recovery_rolls_back_on_receipt_failure(l2_store_with_schema):
    store = l2_store_with_schema
    request = await _seed(store)
    before = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    with patch(
        "magi.memory.l2.assertions.summary_recovery.append_claim_target_outcomes_on_connection",
        new=AsyncMock(side_effect=RuntimeError("Receipt unavailable")),
    ), pytest.raises(RuntimeError, match="Receipt unavailable"):
        await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id) == before


@pytest.mark.asyncio
async def test_recovery_does_not_override_active_correction_rules(l2_store_with_schema):
    store = l2_store_with_schema
    request = await _seed(store)
    row = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """INSERT INTO memory_corrections (
                correction_id, request_id, actor_id, target_kind, target_id, slot_key,
                claim_fingerprint, correction_kind, before_json, state, created_at
            ) VALUES ('correction:apple', 'request:apple', 'u1', 'assertion', ?, ?, ?,
                'record_error', '{}', 'active', 1)""",
            (request.assertion_id, row["slot_key"], row["claim_fingerprint"]),
        )
        await db.execute(
            """INSERT INTO memory_correction_rules (
                rule_id, correction_id, target_kind, rule_kind, slot_key, claim_fingerprint, created_at
            ) VALUES ('rule:apple', 'correction:apple', 'assertion', 'block_claim', ?, ?, 1)""",
            (row["slot_key"], row["claim_fingerprint"]),
        )
        await db.commit()
    result = await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert result.items[0].status == "user_governed"


@pytest.mark.asyncio
async def test_recovery_cannot_revive_forgotten_entity(l2_store_with_schema):
    store = l2_store_with_schema
    request = await _seed(store)
    await store.forget_entity(entity_id="other:source:opaque-identity")
    row = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    current_request = AssertionSummaryRecoveryRequest(request.assertion_id, row["updated_at"], row["natural_summary"])
    result = await recover_assertion_summaries(store.db_path, requests=[current_request], dry_run=False, language="zh")
    assert result.items[0].status == "assertion_not_active"
    claim = await _row(store.db_path, "l2_grounded_claims", "claim_id", "claim:apple")
    assert claim["availability"] == "forgotten"
    assert claim["object_value_json"] is None


async def _seed_l3_dependency(db_path, *, assertion_id, review_state):
    async with sqlite_connection_async(db_path) as db:
        for summary_id, source_id in (("summary:affected", assertion_id), ("summary:unrelated", "assertion:other")):
            await db.execute(
                """INSERT INTO summaries (
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, source_event_ids, source_event_count, generated_by_model,
                    review_state, derivation_state, created_at, updated_at
                ) VALUES (?, 'insight', 'state_change', 1, 2, 'Retained derived text',
                    '["event:apple"]', 1, 'rule-summary', ?, 'current', 1, 1)""",
                (summary_id, review_state),
            )
            await db.execute(
                """INSERT INTO memory_derivation_dependencies (
                    artifact_kind, artifact_id, source_kind, source_id, subject_key,
                    source_revision, created_at
                ) VALUES ('l3_insight', ?, 'assertion', ?, 'user:u1', 0, 1)""",
                (summary_id, source_id),
            )
            await db.execute(
                "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, 'Retained derived text')",
                (summary_id,),
            )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("review_state", ["candidate", "confirmed", "dismissed"])
async def test_recovery_invalidates_only_dependent_l3_and_preserves_review_state(l2_store_with_schema, review_state):
    store = l2_store_with_schema
    request = await _seed(store)
    await _seed_l3_dependency(store.db_path, assertion_id=request.assertion_id, review_state=review_state)
    affected_before = await _row(store.db_path, "summaries", "summary_id", "summary:affected")
    unrelated_before = await _row(store.db_path, "summaries", "summary_id", "summary:unrelated")
    preview = await recover_assertion_summaries(store.db_path, requests=[request], language="zh")
    assert preview.l3_summary_ids == ("summary:affected",)
    assert await _row(store.db_path, "summaries", "summary_id", "summary:affected") == affected_before
    result = await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert result.l3_summary_ids == ("summary:affected",)
    affected_after = await _row(store.db_path, "summaries", "summary_id", "summary:affected")
    assert affected_after["derivation_state"] == "stale"
    assert {key: value for key, value in affected_after.items() if key not in {"derivation_state", "updated_at"}} == {
        key: value for key, value in affected_before.items() if key not in {"derivation_state", "updated_at"}
    }
    assert await _row(store.db_path, "summaries", "summary_id", "summary:unrelated") == unrelated_before
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute("SELECT summary_id FROM l3_summaries_fts") as cursor:
            assert [row[0] for row in await cursor.fetchall()] == ["summary:unrelated"]


@pytest.mark.asyncio
async def test_l3_invalidation_failure_rolls_back_assertion_recovery(l2_store_with_schema):
    store = l2_store_with_schema
    request = await _seed(store)
    before = await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id)
    with patch(
        "magi.memory.l2.assertions.summary_recovery.MemoryCorrectionRepository.invalidate_l3_insights_on_connection",
        new=AsyncMock(side_effect=RuntimeError("L3 invalidation unavailable")),
    ), pytest.raises(RuntimeError, match="L3 invalidation unavailable"):
        await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert await _row(store.db_path, "tom_trait_assertions", "assertion_id", request.assertion_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("governed_state", ["retired", "rejected", "deleted"])
async def test_recovery_leaves_governed_l3_dependencies_untouched(l2_store_with_schema, governed_state):
    store = l2_store_with_schema
    request = await _seed(store)
    await _seed_l3_dependency(store.db_path, assertion_id=request.assertion_id, review_state="candidate")
    async with sqlite_connection_async(store.db_path) as db:
        if governed_state == "deleted":
            await db.execute("DELETE FROM summaries WHERE summary_id = 'summary:affected'")
        elif governed_state == "retired":
            await db.execute("UPDATE summaries SET derivation_state = 'retired' WHERE summary_id = 'summary:affected'")
        else:
            await db.execute("UPDATE summaries SET review_state = 'rejected' WHERE summary_id = 'summary:affected'")
        await db.commit()
    before = None if governed_state == "deleted" else await _row(store.db_path, "summaries", "summary_id", "summary:affected")
    preview = await recover_assertion_summaries(store.db_path, requests=[request], language="zh")
    assert preview.l3_summary_ids == ()
    result = await recover_assertion_summaries(store.db_path, requests=[request], dry_run=False, language="zh")
    assert result.items[0].status == "rebuilt"
    assert result.l3_summary_ids == ()
    if before is not None:
        assert await _row(store.db_path, "summaries", "summary_id", "summary:affected") == before
    else:
        async with sqlite_connection_async(store.db_path) as db:
            async with db.execute("SELECT 1 FROM summaries WHERE summary_id = 'summary:affected'") as cursor:
                assert await cursor.fetchone() is None


@pytest.mark.asyncio
async def test_l3_invalidation_owner_respects_explicit_scope_and_retains_default_behavior(l2_store_with_schema):
    store = l2_store_with_schema
    request = await _seed(store)
    await _seed_l3_dependency(store.db_path, assertion_id=request.assertion_id, review_state="candidate")
    repository = MemoryCorrectionRepository(store.db_path)
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE memory_derivation_dependencies SET source_id = ?", (request.assertion_id,))
        await db.commit()
        await db.execute("BEGIN IMMEDIATE")
        subjects = await repository.invalidate_l3_insights_on_connection(
            db, source_kind="assertion", source_ids=[request.assertion_id], summary_ids=[],
        )
        assert subjects == set()
        subjects = await repository.invalidate_l3_insights_on_connection(
            db, source_kind="assertion", source_ids=[request.assertion_id], summary_ids=["summary:affected"],
        )
        assert subjects == {"user:u1"}
        await db.commit()
    assert (await _row(store.db_path, "summaries", "summary_id", "summary:affected"))["derivation_state"] == "stale"
    assert (await _row(store.db_path, "summaries", "summary_id", "summary:unrelated"))["derivation_state"] == "current"
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        await repository.invalidate_l3_insights_on_connection(
            db, source_kind="assertion", source_ids=[request.assertion_id],
        )
        await db.commit()
    assert (await _row(store.db_path, "summaries", "summary_id", "summary:unrelated"))["derivation_state"] == "stale"
