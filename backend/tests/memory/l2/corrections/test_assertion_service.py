from __future__ import annotations

import time

import aiosqlite
import pytest

from _shared.context_scope import context_scope
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.corrections.service import (
    MemoryCorrectionConflictError,
    MemoryCorrectionValidationError,
)


async def _seed_assertion(
    store,  # type: ignore[no-untyped-def]
    *,
    trait_value: str = "Hangzhou",
    evidence_events: list[str] | None = None,
    scope: dict | None = None,
    observed_at: float | None = None,
) -> str:
    now = float(observed_at if observed_at is not None else time.time() - 3600)
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "location.home",
            "trait_value": trait_value,
            "confidence_score": 0.6,
            "evidence_events": evidence_events or ["evt-original"],
            "volatility_index": 0.2,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "corroborated",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
            "scope": scope,
        }
    )


async def _fetch_all(db_path: str, query: str, args: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_forget_entity_blocks_revert_and_cancels_future_assertion_correction(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-assertion-before-forget-entity",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=time.time() + 3600,
    )
    assert applied is not None
    correction_id = applied["correction"]["correction_id"]
    replacement_id = applied["current_assertion"]["assertion_id"]

    await store.forget_entity(entity_id="user:u1")

    with pytest.raises(
        MemoryCorrectionConflictError, match="Forgotten memories cannot be restored"
    ):
        await store.revert_assertion_correction(
            correction_id=correction_id,
            request_id="revert-forgotten-assertion",
            actor_id="user:u1",
        )

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert original is not None and original["status"] == "archived"
    assert replacement is not None and replacement["status"] == "archived"
    await _seed_assertion(store, trait_value="Hangzhou")
    await _seed_assertion(store, trait_value="Shanghai")
    assert await store.list_current_assertions(entity_id="user:u1") == []
    governance = await _fetch_all(
        store.db_path,
        """
        SELECT transition_applied_at, transition_cancelled_at,
               transition_cancel_reason,
               (SELECT COUNT(*) FROM memory_correction_rules
                WHERE correction_id = memory_corrections.correction_id
                  AND active = 1 AND rule_kind = 'block_claim') AS block_rules
        FROM memory_corrections
        WHERE correction_id = ?
        """,
        (correction_id,),
    )
    assert governance[0]["transition_applied_at"] is None
    assert governance[0]["transition_cancelled_at"] is not None
    assert governance[0]["transition_cancel_reason"] == "forget_entity"
    assert governance[0]["block_rules"] == 0
    assert await store.next_memory_correction_job_wakeup_at() is None
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(time, "time", lambda: float(applied["correction"]["effective_at"]) + 1)
        stats = await store.process_memory_correction_jobs(limit=10)
    assert stats["activated"] == 0
    assert await store.get_memory_correction_derivation_state(correction_id) == "completed"


@pytest.mark.asyncio
async def test_forget_time_range_blocks_assertion_revert_without_forgetting_replacement(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original is not None
    original_time = float(original["first_inferred_at"])
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="assertion-before-forget-time-range",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    assert applied is not None
    correction_id = applied["correction"]["correction_id"]
    replacement_id = applied["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=original_time - 1, end=original_time + 1)

    with pytest.raises(
        MemoryCorrectionConflictError, match="Forgotten memories cannot be restored"
    ):
        await store.revert_assertion_correction(
            correction_id=correction_id,
            request_id="revert-time-forgotten-assertion",
            actor_id="user:u1",
        )

    forgotten = await store.get_tom_assertion(assertion_id=assertion_id)
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert forgotten is not None and forgotten["status"] == "archived"
    assert replacement is not None and replacement["status"] == "stable"
    rules = await _fetch_all(
        store.db_path,
        """
        SELECT rule_kind, claim_fingerprint
        FROM memory_correction_rules
        WHERE correction_id = ? AND active = 1
        ORDER BY rule_kind, claim_fingerprint
        """,
        (correction_id,),
    )
    assert sorted(row["rule_kind"] for row in rules) == [
        "authoritative_slot",
        "block_claim",
    ]


@pytest.mark.asyncio
async def test_forget_time_range_cancels_future_assertion_and_restores_original(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    before = await store.get_tom_assertion(assertion_id=assertion_id)
    assert before is not None
    effective_at = time.time() + 3600
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-assertion-forgotten-before-effective",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert applied is not None
    correction_id = applied["correction"]["correction_id"]
    replacement_id = applied["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=effective_at - 1, end=effective_at + 1)

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert original is not None
    assert original["status"] == before["status"]
    assert original["valid_to"] is None
    assert replacement is not None and replacement["status"] == "archived"
    rules = await _fetch_all(
        store.db_path,
        "SELECT active FROM memory_correction_rules WHERE correction_id = ?",
        (correction_id,),
    )
    assert rules and all(row["active"] == 0 for row in rules)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(time, "time", lambda: effective_at + 2)
        stats = await store.process_memory_correction_jobs(limit=10)
    assert stats["activated"] == 0
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [assertion_id]

    repeated = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-assertion-forgotten-before-effective",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert repeated is not None
    assert repeated["created"] is False
    assert repeated["current_assertion"]["assertion_id"] == assertion_id


@pytest.mark.asyncio
async def test_forget_time_range_cancellation_is_idempotent_after_later_assertion_correction(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    effective_at = time.time() + 3600
    first = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="cancelled-assertion-before-later-correction",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert first is not None
    first_id = first["correction"]["correction_id"]

    await store.forget_time_range(start=effective_at - 1, end=effective_at + 1)
    cancelled_before = await _fetch_all(
        store.db_path,
        "SELECT transition_cancelled_at FROM memory_corrections WHERE correction_id = ?",
        (first_id,),
    )
    later = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="later-assertion-after-cancelled-schedule",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Beijing",
    )
    assert later is not None
    later_id = later["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=effective_at - 1, end=effective_at + 1)

    cancelled_after = await _fetch_all(
        store.db_path,
        "SELECT transition_cancelled_at FROM memory_corrections WHERE correction_id = ?",
        (first_id,),
    )
    assert cancelled_after == cancelled_before
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [later_id]


@pytest.mark.asyncio
async def test_forget_time_range_restores_partially_supported_assertion_after_cancel(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    retained_at = time.time() - 3600
    effective_at = time.time() + 3600
    assertion_id = await _seed_assertion(
        store,
        evidence_events=["evt-assertion-retained"],
        observed_at=retained_at,
    )
    await _seed_assertion(
        store,
        evidence_events=["evt-assertion-forgotten"],
        observed_at=effective_at,
    )
    before = await store.get_tom_assertion(assertion_id=assertion_id)
    assert before is not None
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="partially-supported-assertion-schedule",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert applied is not None
    replacement_id = applied["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=effective_at - 1, end=effective_at + 1)

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert original is not None
    assert original["status"] == before["status"]
    assert original["valid_to"] is None
    assert original["evidence_events"] == ["evt-assertion-retained"]
    assert replacement is not None and replacement["status"] == "archived"


@pytest.mark.asyncio
async def test_forget_time_range_after_due_assertion_activation_restores_original(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    effective_at = time.time() + 3600
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="due-assertion-before-forget",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert applied is not None
    correction_id = applied["correction"]["correction_id"]
    replacement_id = applied["current_assertion"]["assertion_id"]
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(time, "time", lambda: effective_at + 1)
        stats = await store.process_memory_correction_jobs(limit=10)
    assert stats["activated"] == 1

    await store.forget_time_range(start=effective_at - 1, end=effective_at + 1)

    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [assertion_id]
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert replacement is not None and replacement["status"] == "archived"
    governance = await _fetch_all(
        store.db_path,
        """
        SELECT transition_applied_at, transition_cancelled_at,
               (SELECT COUNT(*) FROM memory_correction_rules
                WHERE correction_id = memory_corrections.correction_id AND active = 1) AS active_rules
        FROM memory_corrections WHERE correction_id = ?
        """,
        (correction_id,),
    )
    assert governance[0]["transition_applied_at"] is not None
    assert governance[0]["transition_cancelled_at"] is not None
    assert governance[0]["active_rules"] == 0


@pytest.mark.asyncio
async def test_forget_time_range_cascades_through_future_assertion_chain(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    first_at = time.time() + 1800
    second_at = first_at + 1800
    first = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="assertion-chain-a-b",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=first_at,
    )
    assert first is not None
    first_replacement_id = first["current_assertion"]["assertion_id"]
    second = await store.apply_assertion_correction(
        assertion_id=first_replacement_id,
        request_id="assertion-chain-b-c",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Beijing",
        effective_at=second_at,
    )
    assert second is not None
    second_replacement_id = second["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=first_at - 1, end=first_at + 1)

    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [assertion_id]
    for replacement_id in (first_replacement_id, second_replacement_id):
        replacement = await store.get_tom_assertion(assertion_id=replacement_id)
        assert replacement is not None and replacement["status"] == "archived"
    cancellations = await _fetch_all(
        store.db_path,
        """
        SELECT transition_cancelled_at
        FROM memory_corrections
        WHERE request_id IN ('assertion-chain-a-b', 'assertion-chain-b-c')
        ORDER BY request_id
        """,
    )
    assert len(cancellations) == 2
    assert all(row["transition_cancelled_at"] is not None for row in cancellations)
    future_current = await store.list_current_assertions(
        entity_id="user:u1",
        effective_at=second_at + 1,
    )
    assert [item["assertion_id"] for item in future_current] == [assertion_id]


@pytest.mark.asyncio
async def test_forget_middle_of_applied_assertion_chain_preserves_latest_then_root(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    base_at = time.time() - 600
    first_at = base_at + 120
    second_at = base_at + 240
    root_id = await _seed_assertion(store, observed_at=base_at)
    first = await store.apply_assertion_correction(
        assertion_id=root_id,
        request_id="applied-assertion-chain-a-b",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=first_at,
    )
    assert first is not None
    middle_id = first["current_assertion"]["assertion_id"]
    second = await store.apply_assertion_correction(
        assertion_id=middle_id,
        request_id="applied-assertion-chain-b-c",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Beijing",
        effective_at=second_at,
    )
    assert second is not None
    latest_id = second["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=first_at - 1, end=first_at + 1)

    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [latest_id]
    transitions = await _fetch_all(
        store.db_path,
        """
        SELECT request_id, transition_applied_at, transition_cancelled_at
        FROM memory_corrections
        WHERE request_id IN (
            'applied-assertion-chain-a-b',
            'applied-assertion-chain-b-c'
        )
        ORDER BY request_id
        """,
    )
    assert all(row["transition_applied_at"] is not None for row in transitions)
    assert transitions[0]["transition_cancelled_at"] is not None
    assert transitions[1]["transition_cancelled_at"] is None

    retried = await store.apply_assertion_correction(
        assertion_id=root_id,
        request_id="applied-assertion-chain-a-b",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=first_at,
    )
    assert retried is not None
    assert retried["created"] is False
    assert retried["current_assertion"]["assertion_id"] == middle_id

    await store.forget_time_range(start=second_at - 1, end=second_at + 1)

    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [root_id]
    middle = await store.get_tom_assertion(assertion_id=middle_id)
    latest = await store.get_tom_assertion(assertion_id=latest_id)
    assert middle is not None and middle["status"] == "archived"
    assert latest is not None and latest["status"] == "archived"


@pytest.mark.asyncio
async def test_forget_applied_assertion_with_pending_successor_restores_root(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    base_at = time.time() - 300
    applied_at = base_at + 120
    pending_at = time.time() + 3600
    root_id = await _seed_assertion(store, observed_at=base_at)
    first = await store.apply_assertion_correction(
        assertion_id=root_id,
        request_id="mixed-assertion-chain-a-b",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=applied_at,
    )
    assert first is not None
    middle_id = first["current_assertion"]["assertion_id"]
    second = await store.apply_assertion_correction(
        assertion_id=middle_id,
        request_id="mixed-assertion-chain-b-c",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Beijing",
        effective_at=pending_at,
    )
    assert second is not None
    pending_id = second["current_assertion"]["assertion_id"]

    await store.forget_time_range(start=applied_at - 1, end=applied_at + 1)

    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [root_id]
    pending = await store.get_tom_assertion(assertion_id=pending_id)
    assert pending is not None and pending["status"] == "archived"
    transitions = await _fetch_all(
        store.db_path,
        """
        SELECT request_id, transition_applied_at, transition_cancelled_at
        FROM memory_corrections
        WHERE request_id IN (
            'mixed-assertion-chain-a-b',
            'mixed-assertion-chain-b-c'
        )
        ORDER BY request_id
        """,
    )
    assert transitions[0]["transition_applied_at"] is not None
    assert transitions[0]["transition_cancelled_at"] is not None
    assert transitions[1]["transition_applied_at"] is None
    assert transitions[1]["transition_cancelled_at"] is not None


@pytest.mark.asyncio
async def test_correction_source_evidence_is_governed_on_replacement_assertion(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    source_at = time.time() - 120
    later_at = time.time() + 120

    async def resolve_timestamps(event_ids: list[str]) -> dict[str, float]:
        return {
            event_id: source_at
            for event_id in event_ids
            if event_id == "evt-assertion-correction-source"
        }

    store._evidence_timestamp_resolver = resolve_timestamps
    assertion_id = await _seed_assertion(store)
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="assertion-source-evidence-ledger",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
        source_event_id="evt-assertion-correction-source",
    )
    assert applied is not None
    replacement_id = applied["current_assertion"]["assertion_id"]
    replacement_fingerprint = applied["current_assertion"]["claim_fingerprint"]

    ledger = await _fetch_all(
        store.db_path,
        """
        SELECT event_id, observed_at
        FROM memory_claim_evidence_events
        WHERE target_kind = 'assertion' AND claim_fingerprint = ?
        """,
        (replacement_fingerprint,),
    )
    assert ledger == [
        {
            "event_id": "evt-assertion-correction-source",
            "observed_at": source_at,
        }
    ]

    reinforced_id = await _seed_assertion(
        store,
        trait_value="Shanghai",
        evidence_events=["evt-assertion-later-evidence"],
        observed_at=later_at,
    )
    assert reinforced_id == replacement_id

    await store.forget_time_range(start=source_at - 1, end=source_at + 1)

    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert replacement is not None
    assert replacement["status"] == "stable"
    assert replacement["evidence_events"] == ["evt-assertion-later-evidence"]


@pytest.mark.asyncio
async def test_correction_governs_evidence_older_than_assertion_row_cap(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = ""
    for index in range(60):
        assertion_id = await _seed_assertion(
            store,
            evidence_events=[f"evt-ledger-{index:02d}"],
        )

    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="assertion-ledger-beyond-row-cap",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )

    assert applied is not None
    assert await store.active_correction_evidence_event_ids(["evt-ledger-00", "evt-ledger-59"]) == {
        "evt-ledger-00",
        "evt-ledger-59",
    }


@pytest.mark.parametrize(
    ("suffix", "correction_kind", "kwargs", "message"),
    [
        (
            "record-scope",
            CorrectionKind.RECORD_ERROR,
            {
                "replacement_value": "Shanghai",
                "scope": context_scope(project="magi"),
            },
            "scope is only supported for scope_refinement",
        ),
        (
            "changed-scope",
            CorrectionKind.SITUATION_CHANGED,
            {
                "replacement_value": "Shanghai",
                "effective_at": 1.0,
                "scope": context_scope(project="magi"),
            },
            "scope is only supported for scope_refinement",
        ),
        (
            "record-time",
            CorrectionKind.RECORD_ERROR,
            {"replacement_value": "Shanghai", "effective_at": 1.0},
            "effective_at is only supported for situation_changed",
        ),
        (
            "scope-time",
            CorrectionKind.SCOPE_REFINEMENT,
            {
                "replacement_value": "Shanghai",
                "scope": context_scope(project="magi"),
                "effective_at": 1.0,
            },
            "effective_at is only supported for situation_changed",
        ),
    ],
)
@pytest.mark.asyncio
async def test_assertion_correction_rejects_fields_for_other_meanings(
    l2_store_with_schema,
    suffix: str,
    correction_kind: CorrectionKind,
    kwargs: dict,
    message: str,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)

    with pytest.raises(MemoryCorrectionValidationError, match=message):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id=f"request-invalid-{suffix}",
            actor_id="user:u1",
            correction_kind=correction_kind,
            **kwargs,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("correction_kind", "extra"),
    [
        (CorrectionKind.RECORD_ERROR, {}),
        (CorrectionKind.SITUATION_CHANGED, {"effective_at": time.time()}),
    ],
)
async def test_assertion_correction_rejects_unchanged_replacement(
    l2_store_with_schema,
    correction_kind: CorrectionKind,
    extra: dict,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store, trait_value="Hangzhou")

    with pytest.raises(MemoryCorrectionValidationError, match="must change the assertion"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id=f"request-unchanged-{correction_kind}",
            actor_id="user:u1",
            correction_kind=correction_kind,
            replacement_value="  HANGZHOU  ",
            **extra,
        )


@pytest.mark.asyncio
async def test_assertion_scope_refinement_rejects_existing_scope(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    existing_scope = context_scope(project="magi")
    assertion_id = await _seed_assertion(store, scope=existing_scope)

    with pytest.raises(MemoryCorrectionValidationError, match="must change the scope"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-unchanged-assertion-scope",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SCOPE_REFINEMENT,
            replacement_value="Hangzhou",
            scope=existing_scope,
        )


@pytest.mark.asyncio
async def test_assertion_scope_refinement_cannot_change_the_claim(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store, trait_value="Hangzhou")

    with pytest.raises(MemoryCorrectionValidationError, match="cannot change the assertion"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-scope-and-value-change",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SCOPE_REFINEMENT,
            replacement_value="Shanghai",
            scope=context_scope(project="magi"),
        )


@pytest.mark.asyncio
async def test_record_error_replaces_without_copying_evidence(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(
        store,
        evidence_events=["evt-original", "evt-corroboration"],
    )

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-record-error",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
        reason="The original record was wrong",
    )

    assert result is not None
    replacement = result["current_assertion"]
    assert replacement["trait_value"] == "Shanghai"
    assert replacement["evidence_events"] == []
    assert replacement["previous_version_id"] == assertion_id
    assert replacement["authority_ref"].startswith("correction:")
    assert result["subject_revision"] == 1

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original["status"] == "user_rejected"
    assert original["superseded_by"] == replacement["assertion_id"]

    correction = result["correction"]
    assert correction["reason"] == "The original record was wrong"
    assert correction["before"]["evidence_events"] == '["evt-original", "evt-corroboration"]'
    rules = await _fetch_all(
        store.db_path,
        "SELECT rule_kind FROM memory_correction_rules WHERE correction_id = ? ORDER BY rule_kind",
        (correction["correction_id"],),
    )
    assert [row["rule_kind"] for row in rules] == ["authoritative_slot", "block_claim"]


@pytest.mark.asyncio
async def test_rejected_feedback_creates_durable_correction(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)

    rejected = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="rejected",
    )

    assert rejected is not None
    assert rejected["status"] == "user_rejected"
    corrections = await store.list_assertion_corrections(assertion_id=assertion_id)
    assert len(corrections) == 1
    assert corrections[0]["correction_kind"] == CorrectionKind.RECORD_ERROR
    repeated = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="rejected",
    )
    assert repeated["status"] == "user_rejected"
    assert len(await store.list_assertion_corrections(assertion_id=assertion_id)) == 1
    with pytest.raises(MemoryCorrectionConflictError, match="correction history"):
        await store.apply_user_feedback(
            assertion_id=assertion_id,
            feedback="confirmed",
        )
    rules = await _fetch_all(
        store.db_path,
        "SELECT rule_kind FROM memory_correction_rules WHERE correction_id = ?",
        (corrections[0]["correction_id"],),
    )
    assert rules == [{"rule_kind": "block_claim"}]


@pytest.mark.asyncio
async def test_confirmed_feedback_is_idempotent(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)

    first = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="confirmed",
    )
    repeated = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="confirmed",
    )

    assert first is not None
    assert repeated is not None
    assert repeated["confidence_score"] == pytest.approx(first["confidence_score"])
    assert repeated["user_feedback_at"] == pytest.approx(first["user_feedback_at"])


@pytest.mark.asyncio
async def test_situation_changed_closes_old_version_at_effective_time(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    effective_at = time.time() - 60

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-situation-changed",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )

    assert result is not None
    replacement = result["current_assertion"]
    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original["status"] == "superseded"
    assert original["valid_to"] == pytest.approx(effective_at)
    assert replacement["valid_from"] == pytest.approx(effective_at)

    history = await store.get_assertion_correction_history(slot_key=replacement["slot_key"])
    assert [item["trait_value"] for item in history["assertions"]] == [
        "Hangzhou",
        "Shanghai",
    ]
    assert history["corrections"][0]["effective_at"] == pytest.approx(effective_at)


@pytest.mark.asyncio
async def test_situation_change_rejects_time_before_assertion_started(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    original = await store.get_tom_assertion(assertion_id=assertion_id)

    with pytest.raises(MemoryCorrectionValidationError, match="assertion start time"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-before-assertion-start",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SITUATION_CHANGED,
            replacement_value="Shanghai",
            effective_at=float(original["first_inferred_at"]) - 1,
        )


@pytest.mark.asyncio
async def test_shadow_assertion_cannot_be_corrected(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'shadow', validation_state = 'shadow'
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        )
        await db.commit()

    with pytest.raises(MemoryCorrectionConflictError, match="no longer current"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-shadow-assertion",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
        )

    assert await store.list_assertion_corrections(assertion_id=assertion_id) == []


@pytest.mark.asyncio
async def test_invalidated_assertion_cannot_be_corrected(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'invalidated', validation_state = 'invalidated'
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        )
        await db.commit()

    with pytest.raises(MemoryCorrectionConflictError, match="no longer current"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-invalidated-assertion",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
        )

    assert await store.list_assertion_corrections(assertion_id=assertion_id) == []


@pytest.mark.asyncio
async def test_scope_refinement_only_reads_in_matching_context(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store, trait_value="Shanghai")

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-scope-refinement",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope=context_scope(project="magi"),
    )

    assert result is not None
    assert result["current_assertion"]["scope"] == context_scope(project="magi")
    assert await store.list_current_assertions(entity_id="user:u1") == []
    assert (
        await store.list_current_assertions(
            entity_id="user:u1",
            context_scope=context_scope(project="another"),
        )
        == []
    )
    matching = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=context_scope(project="magi"),
    )
    assert [item["assertion_id"] for item in matching] == [
        result["current_assertion"]["assertion_id"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("correction_kind", "extra"),
    [
        (CorrectionKind.RECORD_ERROR, {}),
        (CorrectionKind.SITUATION_CHANGED, {"effective_at": time.time() - 60}),
    ],
)
async def test_correction_preserves_existing_assertion_scope(
    l2_store_with_schema,
    correction_kind: CorrectionKind,
    extra: dict,
) -> None:
    store = l2_store_with_schema
    project_scope = context_scope(project="magi")
    assertion_id = await _seed_assertion(store, scope=project_scope)

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id=f"preserve-assertion-scope-{correction_kind}",
        actor_id="user:u1",
        correction_kind=correction_kind,
        replacement_value="Shanghai",
        **extra,
    )
    repeated = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id=f"preserve-assertion-scope-{correction_kind}",
        actor_id="user:u1",
        correction_kind=correction_kind,
        replacement_value="Shanghai",
        **extra,
    )

    assert result is not None and repeated is not None
    assert repeated["created"] is False
    assert result["current_assertion"]["scope"] == project_scope
    assert result["correction"]["scope"] == project_scope
    assert await store.list_current_assertions(entity_id="user:u1") == []
    matching = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=project_scope,
    )
    assert [item["assertion_id"] for item in matching] == [
        result["current_assertion"]["assertion_id"]
    ]
    assert (
        await store.list_current_assertions(
            entity_id="user:u1",
            context_scope=context_scope(project="another"),
        )
        == []
    )


@pytest.mark.asyncio
async def test_newer_assertion_correction_in_another_scope_does_not_block_revert(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    first_scope = context_scope(project="magi")
    second_scope = context_scope(project="another")
    first_id = await _seed_assertion(store, scope=first_scope)
    second_id = await _seed_assertion(store, scope=second_scope)
    first = await store.apply_assertion_correction(
        assertion_id=first_id,
        request_id="correct-first-project-assertion",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    await store.apply_assertion_correction(
        assertion_id=second_id,
        request_id="correct-second-project-assertion",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Beijing",
    )

    reverted = await store.revert_assertion_correction(
        correction_id=first["correction"]["correction_id"],
        request_id="revert-first-project-assertion",
        actor_id="user:u1",
    )

    assert reverted is not None
    assert reverted["current_assertion"]["assertion_id"] == first_id
    first_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=first_scope,
    )
    second_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=second_scope,
    )
    assert [item["trait_value"] for item in first_current] == ["Hangzhou"]
    assert [item["trait_value"] for item in second_current] == ["Beijing"]


@pytest.mark.asyncio
async def test_request_id_is_idempotent(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    command = {
        "assertion_id": assertion_id,
        "request_id": "request-idempotent",
        "actor_id": "user:u1",
        "correction_kind": CorrectionKind.RECORD_ERROR,
        "replacement_value": "Shanghai",
    }

    first = await store.apply_assertion_correction(**command)
    second = await store.apply_assertion_correction(**command)

    assert first is not None and second is not None
    assert first["created"] is True
    assert second["created"] is False
    assert first["correction"]["correction_id"] == second["correction"]["correction_id"]
    assert first["current_assertion"]["assertion_id"] == second["current_assertion"]["assertion_id"]
    counts = await _fetch_all(
        store.db_path,
        """
        SELECT
          (SELECT COUNT(*) FROM memory_corrections) AS corrections,
          (SELECT COUNT(*) FROM memory_subject_revisions WHERE subject_key = 'user:u1') AS revisions
        """,
    )
    assert counts == [{"corrections": 1, "revisions": 1}]
    assert await store.list_current_assertions(entity_id="user:u1")


@pytest.mark.asyncio
async def test_request_id_retry_ignores_transport_only_fields(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    command = {
        "assertion_id": assertion_id,
        "request_id": "request-idempotent-transport",
        "actor_id": "user:u1",
        "correction_kind": CorrectionKind.RECORD_ERROR,
        "replacement_value": "Shanghai",
        "reason": "  The original record was wrong  ",
        "audit_event_id": "audit-first",
    }

    first = await store.apply_assertion_correction(**command)
    second = await store.apply_assertion_correction(
        **{
            **command,
            "audit_event_id": "audit-retry",
            "expected_updated_at": -1.0,
        }
    )

    assert first is not None and second is not None
    assert first["created"] is True
    assert second["created"] is False
    assert first["correction"]["correction_id"] == second["correction"]["correction_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"assertion_id": "assertion:another"},
        {"actor_id": "user:another"},
        {"replacement_value": "Beijing"},
        {"reason": "A different reason"},
        {
            "scope": {
                "all_of": [
                    {
                        "dimension": "project",
                        "context_id": "ctx_project_" + "a" * 64,
                    }
                ]
            }
        },
        {"source_event_id": "evt:another"},
        {
            "correction_kind": CorrectionKind.SITUATION_CHANGED,
            "effective_at": time.time() + 3600,
        },
    ],
)
async def test_request_id_reuse_with_different_assertion_intent_conflicts(
    l2_store_with_schema,
    changes,
):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    command = {
        "assertion_id": assertion_id,
        "request_id": "request-id-bound-to-intent",
        "actor_id": "user:u1",
        "correction_kind": CorrectionKind.RECORD_ERROR,
        "replacement_value": "Shanghai",
        "reason": "The original record was wrong",
    }
    await store.apply_assertion_correction(**command)

    with pytest.raises(MemoryCorrectionConflictError, match="different correction"):
        await store.apply_assertion_correction(**{**command, **changes})


@pytest.mark.asyncio
async def test_request_id_reuse_with_different_effective_time_conflicts(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    effective_at = time.time() + 3600
    command = {
        "assertion_id": assertion_id,
        "request_id": "request-id-bound-to-effective-time",
        "actor_id": "user:u1",
        "correction_kind": CorrectionKind.SITUATION_CHANGED,
        "replacement_value": "Shanghai",
        "effective_at": effective_at,
    }
    await store.apply_assertion_correction(**command)

    with pytest.raises(MemoryCorrectionConflictError, match="different correction"):
        await store.apply_assertion_correction(**{**command, "effective_at": effective_at + 60})


@pytest.mark.asyncio
async def test_revert_restores_original_and_deactivates_rules(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-to-revert",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    correction_id = applied["correction"]["correction_id"]
    replacement_id = applied["current_assertion"]["assertion_id"]

    reverted = await store.revert_assertion_correction(
        correction_id=correction_id,
        request_id="revert-request",
        actor_id="user:u1",
    )

    assert reverted is not None
    assert reverted["correction"]["state"] == "reverted"
    assert reverted["subject_revision"] == 2
    assert reverted["current_assertion"]["assertion_id"] == assertion_id
    assert reverted["current_assertion"]["trait_value"] == "Hangzhou"
    assert reverted["current_assertion"]["evidence_events"] == ["evt-original"]
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert replacement["status"] == "archived"
    rules = await _fetch_all(
        store.db_path,
        "SELECT DISTINCT active FROM memory_correction_rules WHERE correction_id = ?",
        (correction_id,),
    )
    assert rules == [{"active": 0}]


@pytest.mark.asyncio
async def test_revert_preserves_valid_evidence_added_to_historical_assertion(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    effective_at = time.time() - 120
    assertion_id = await _seed_assertion(
        store,
        evidence_events=["evt-original"],
    )
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="preserve-later-historical-evidence",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )

    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "location.home",
            "trait_value": "Hangzhou",
            "confidence_score": 0.6,
            "evidence_events": ["evt-later-historical"],
            "volatility_index": 0.2,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "corroborated",
            "first_inferred_at": effective_at - 1800,
            "last_validated_at": effective_at - 60,
            "temporal_scope": "persistent",
        }
    )

    reverted = await store.revert_assertion_correction(
        correction_id=applied["correction"]["correction_id"],
        request_id="revert-preserving-later-historical-evidence",
        actor_id="user:u1",
    )

    assert reverted is not None
    assert reverted["current_assertion"]["evidence_events"] == [
        "evt-later-historical",
        "evt-original",
    ]


@pytest.mark.asyncio
async def test_scope_refinement_rejects_occupied_destination_scope(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    destination_scope = context_scope(project="magi")
    assertion_id = await _seed_assertion(store, trait_value="Hangzhou")
    destination_id = await _seed_assertion(
        store,
        trait_value="Beijing",
        scope=destination_scope,
    )

    with pytest.raises(MemoryCorrectionConflictError) as raised:
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="scope-refinement-occupied-destination",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SCOPE_REFINEMENT,
            replacement_value="Hangzhou",
            scope=destination_scope,
        )

    assert raised.value.code == "assertion_scope_occupied"
    assert "selected scope already has a current memory" in str(raised.value)
    assert await store.list_assertion_corrections(assertion_id=assertion_id) == []
    assert (await store.get_tom_assertion(assertion_id=assertion_id))["status"] != "superseded"
    assert (await store.get_tom_assertion(assertion_id=destination_id))["status"] != "superseded"


@pytest.mark.asyncio
async def test_scope_refinement_revert_rejects_occupied_original_scope(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    destination_scope = context_scope(project="magi")
    assertion_id = await _seed_assertion(store, trait_value="Hangzhou")
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="scope-refinement-before-original-conflict",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Hangzhou",
        scope=destination_scope,
    )
    competing_id = await _seed_assertion(store, trait_value="Beijing")

    with pytest.raises(MemoryCorrectionConflictError) as raised:
        await store.revert_assertion_correction(
            correction_id=applied["correction"]["correction_id"],
            request_id="revert-into-occupied-original-scope",
            actor_id="user:u1",
        )

    assert raised.value.code == "assertion_scope_occupied"
    assert "original scope now has a current memory" in str(raised.value)
    assert (await store.get_tom_assertion(assertion_id=competing_id))["status"] != "archived"
    corrections = await store.list_assertion_corrections(assertion_id=assertion_id)
    assert corrections[0]["state"] == "active"
    assert applied["current_assertion"]["assertion_id"] in {
        item["assertion_id"]
        for item in await store.list_current_assertions(
            entity_id="user:u1",
            context_scope=destination_scope,
        )
    }


@pytest.mark.asyncio
async def test_stale_update_and_older_revert_are_rejected(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    original = await store.get_tom_assertion(assertion_id=assertion_id)

    with pytest.raises(MemoryCorrectionConflictError, match="changed after"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="stale-request",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
            expected_updated_at=original["updated_at"] - 1,
        )

    first = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="first-request",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    second = await store.apply_assertion_correction(
        assertion_id=first["current_assertion"]["assertion_id"],
        request_id="second-request",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Beijing",
    )
    assert second is not None

    with pytest.raises(MemoryCorrectionConflictError, match="newer correction"):
        await store.revert_assertion_correction(
            correction_id=first["correction"]["correction_id"],
            request_id="invalid-revert",
            actor_id="user:u1",
        )
