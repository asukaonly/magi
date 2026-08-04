"""Terminal failure closure for durable grounded Claim projections."""

from __future__ import annotations

from types import SimpleNamespace

import aiosqlite
import pytest

from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import ClaimEvidenceInput, GroundedClaimInput
from magi.memory.l2.models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.projection.models import TerminalClaimFailureContext


def _lease(row: dict[str, object]) -> L2ProjectionLease:
    return L2ProjectionLease(
        event_id=str(row["event_id"]),
        lease_token=str(row["lease_token"]),
        attempt_count=int(row["attempt_count"]),
    )


def _job(lease: L2ProjectionLease) -> L2BatchJob:
    return L2BatchJob(
        job_id=f"projection:{lease.event_id}",
        bucket_key="owner:test",
        events=[
            {
                "event_id": lease.event_id,
                "content": "I like jazz.",
                "timestamp": 1710000000.0,
            }
        ],
        flush_reason="projection_ready",
        estimated_tokens=4,
        projection_leases=[lease],
    )


def _batch_job(leases: list[L2ProjectionLease]) -> L2BatchJob:
    return L2BatchJob(
        job_id="projection:batch-terminal-recovery",
        bucket_key="owner:test",
        events=[
            {
                "event_id": lease.event_id,
                "content": lease.event_id,
                "timestamp": 1710000000.0 + index,
            }
            for index, lease in enumerate(leases)
        ],
        flush_reason="projection_ready",
        estimated_tokens=len(leases),
        projection_leases=leases,
    )


async def _persist_claim_for_batch_event(
    store,  # type: ignore[no-untyped-def]
    *,
    event_id: str,
    leases: list[L2ProjectionLease],
    attempt_key: str,
) -> dict:
    identity_key = derive_claim_identity_key(
        extractor_contract_version=1,
        evidence_rule_version=1,
        user_id="user-1",
        subject_ref="user:user-1",
        subject_type="user",
        canonical_predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        polarity="positive",
        specificity="specific",
        temporal_cue="persistent",
        fact_valid_from=None,
        fact_valid_to=None,
        target_from=None,
        target_to=None,
        raw_time_frame=None,
        evidence_mode="direct",
        object_surface=event_id,
        object_value={"name": event_id},
        supporting_event_ids=[event_id],
        antecedent_event_ids=[],
    )
    return await store.upsert_grounded_claim(
        claim=GroundedClaimInput(
            identity_key=identity_key,
            extractor_contract_version=1,
            evidence_rule_version=1,
            origin_attempt_key=attempt_key,
            profile_id="chat.user_message",
            user_id="user-1",
            subject_ref="user:user-1",
            subject_type="user",
            canonical_predicate="LIKES",
            fact_kind="explicit_fact",
            object_type="topic",
            polarity="positive",
            specificity="specific",
            confidence=0.95,
            object_value={"name": event_id},
            object_surface=event_id,
            temporal_cue="persistent",
        ),
        evidence=[
            ClaimEvidenceInput(
                event_id=event_id,
                link_role="supporting",
                required_for_grounding=True,
                event_time=1710000000.0,
                timestamp_confidence="exact",
                timestamp_quality="source",
                evidence_rule_version=1,
                evidence_mode="direct",
                source_type="chat",
                source_domain="user_authored",
                author_type="user",
            )
        ],
        projection_leases=leases,
    )


async def _claim_and_start_attempt(store, event_id: str) -> tuple[dict, L2ProjectionLease]:  # type: ignore[no-untyped-def]
    assert await store.enqueue_projection_job(
        event_id=event_id,
        source="chat",
        event_type="UserMessage",
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 2 WHERE event_id = ?",
            (event_id,),
        )
        await db.commit()
    row = (await store.claim_projection_jobs(consumer_name="worker", limit=1))[0]
    lease = _lease(row)
    assert await store.bind_projection_job_batch([lease], consumer_name="worker") == 1
    assert await store.mark_projection_jobs_running([lease], consumer_name="worker") == 1
    identity_key = derive_claim_identity_key(
        extractor_contract_version=1,
        evidence_rule_version=1,
        user_id="user-1",
        subject_ref="user:user-1",
        subject_type="user",
        canonical_predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        polarity="positive",
        specificity="specific",
        temporal_cue="persistent",
        fact_valid_from=None,
        fact_valid_to=None,
        target_from=None,
        target_to=None,
        raw_time_frame=None,
        evidence_mode="direct",
        object_surface="jazz",
        object_value={"name": "jazz"},
        supporting_event_ids=[event_id],
        antecedent_event_ids=[],
    )
    claim = await store.upsert_grounded_claim(
        claim=GroundedClaimInput(
            identity_key=identity_key,
            extractor_contract_version=1,
            evidence_rule_version=1,
            origin_attempt_key=_job(lease).attempt_key,
            profile_id="chat.user_message",
            user_id="user-1",
            subject_ref="user:user-1",
            subject_type="user",
            canonical_predicate="LIKES",
            fact_kind="explicit_fact",
            object_type="topic",
            polarity="positive",
            specificity="specific",
            confidence=0.95,
            object_value={"name": "jazz"},
            object_surface="jazz",
            temporal_cue="persistent",
        ),
        evidence=[
            ClaimEvidenceInput(
                event_id=event_id,
                link_role="supporting",
                required_for_grounding=True,
                event_time=1710000000.0,
                timestamp_confidence="exact",
                timestamp_quality="source",
                evidence_rule_version=1,
                evidence_mode="direct",
                source_type="chat",
                source_domain="user_authored",
                author_type="user",
            )
        ],
        projection_leases=[lease],
    )
    return claim, lease


@pytest.mark.asyncio
async def test_retry_budget_exhaustion_appends_one_fenced_terminal_outcome(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    claim, first = await _claim_and_start_attempt(store, "event-terminal")
    pipeline = L2Pipeline(
        cognition_store=store,
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )

    await pipeline._fail_extract_job(_job(first), RuntimeError("temporary"))

    assert await store.list_claim_projection_outcomes(claim_id=claim["claim_id"]) == []
    async with aiosqlite.connect(store.db_path) as db:
        first_state = await (
            await db.execute(
                "SELECT status, attempt_count, terminal_at FROM l2_projection_jobs WHERE event_id = ?",
                (first.event_id,),
            )
        ).fetchone()
        await db.execute(
            "UPDATE l2_projection_jobs SET next_retry_at = 0 WHERE event_id = ?",
            (first.event_id,),
        )
        await db.commit()
    assert first_state == ("pending", 1, None)

    second_row = (await store.claim_projection_jobs(consumer_name="worker", limit=1))[0]
    second = _lease(second_row)
    assert second.attempt_count == 2
    assert await store.bind_projection_job_batch([second], consumer_name="worker") == 1
    assert await store.mark_projection_jobs_running([second], consumer_name="worker") == 1
    second_job = _job(second)

    await pipeline._fail_extract_job(second_job, RuntimeError("still broken"))

    outcomes = await store.list_claim_projection_outcomes(claim_id=claim["claim_id"])
    assert len(outcomes) == 1
    assert outcomes[0]["attempt_key"] == second_job.attempt_key
    assert outcomes[0]["target_kind"] == "pipeline"
    assert outcomes[0]["target_id"] == second_job.job_id
    assert outcomes[0]["outcome"] == "failed"
    assert outcomes[0]["reason_code"] == "pipeline_retry_budget_exhausted"
    assert outcomes[0]["details"] == {
        "error_type": "RuntimeError",
        "terminal_event_ids": [second.event_id],
    }
    async with aiosqlite.connect(store.db_path) as db:
        terminal_state = await (
            await db.execute(
                "SELECT status, attempt_count, terminal_at FROM l2_projection_jobs WHERE event_id = ?",
                (second.event_id,),
            )
        ).fetchone()
    assert terminal_state[0:2] == ("failed", 2)
    assert terminal_state[2] is not None

    assert (
        await store.fail_projection_jobs(
            [second],
            error_text="stale retry",
            requeue=True,
            terminal_claim_failure=TerminalClaimFailureContext(
                attempt_key=second_job.attempt_key,
                target_id=second_job.job_id,
                error_type="RuntimeError",
                reason_code="pipeline_retry_budget_exhausted",
            ),
        )
        == 0
    )
    assert len(await store.list_claim_projection_outcomes(claim_id=claim["claim_id"])) == 1


@pytest.mark.asyncio
async def test_requested_replay_skips_terminal_claim_outcome(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    claim, lease = await _claim_and_start_attempt(store, "event-replay-terminal")
    assert await store.request_projection_replay(lease.event_id) is True

    assert (
        await store.fail_projection_jobs(
            [lease],
            error_text="non-retryable",
            requeue=False,
            terminal_claim_failure=TerminalClaimFailureContext(
                attempt_key=_job(lease).attempt_key,
                target_id=_job(lease).job_id,
                error_type="RuntimeError",
                reason_code="pipeline_non_retryable_failure",
            ),
        )
        == 1
    )

    assert await store.list_claim_projection_outcomes(claim_id=claim["claim_id"]) == []
    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                "SELECT status, attempt_count, terminal_at FROM l2_projection_jobs WHERE event_id = ?",
                (lease.event_id,),
            )
        ).fetchone()
    assert state == ("pending", 0, None)


@pytest.mark.asyncio
async def test_terminal_callback_failure_rolls_back_outcome_and_job_transition(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    store = l2_store_with_schema
    claim, lease = await _claim_and_start_attempt(store, "event-atomic-rollback")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 1 WHERE event_id = ?",
            (lease.event_id,),
        )
        await db.commit()
    original = store._append_terminal_claim_projection_failure_outcomes_on_connection

    async def _insert_then_fail(db, *, context, terminal_leases):  # type: ignore[no-untyped-def]
        await original(
            db,
            context=context,
            terminal_leases=terminal_leases,
        )
        raise RuntimeError("terminal callback failed")

    monkeypatch.setattr(
        store,
        "_append_terminal_claim_projection_failure_outcomes_on_connection",
        _insert_then_fail,
    )

    with pytest.raises(RuntimeError, match="terminal callback failed"):
        await store.fail_projection_jobs(
            [lease],
            error_text="broken",
            requeue=True,
            terminal_claim_failure=TerminalClaimFailureContext(
                attempt_key=_job(lease).attempt_key,
                target_id=_job(lease).job_id,
                error_type="RuntimeError",
                reason_code="pipeline_retry_budget_exhausted",
            ),
        )

    assert await store.list_claim_projection_outcomes(claim_id=claim["claim_id"]) == []
    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                "SELECT status, lease_token, attempt_count FROM l2_projection_jobs WHERE event_id = ?",
                (lease.event_id,),
            )
        ).fetchone()
    assert state == ("running", lease.lease_token, lease.attempt_count)


@pytest.mark.asyncio
async def test_stale_last_attempt_atomically_closes_linked_claim(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    claim, lease = await _claim_and_start_attempt(store, "event-stale-terminal")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET max_attempts = 1, lease_heartbeat_at = 0, updated_at = 0
            WHERE event_id = ?
            """,
            (lease.event_id,),
        )
        await db.commit()

    assert (
        await store.requeue_stale_projection_jobs(
            queued_timeout_seconds=1,
            running_timeout_seconds=1,
        )
        == 1
    )

    outcomes = await store.list_claim_projection_outcomes(claim_id=claim["claim_id"])
    assert len(outcomes) == 1
    assert outcomes[0]["attempt_key"] == _job(lease).attempt_key
    assert outcomes[0]["target_kind"] == "pipeline"
    assert outcomes[0]["target_id"] == f"projection_event:{lease.event_id}"
    assert outcomes[0]["reason_code"] == "pipeline_retry_budget_exhausted_stale"
    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                "SELECT status, terminal_at FROM l2_projection_jobs WHERE event_id = ?",
                (lease.event_id,),
            )
        ).fetchone()
    assert state[0] == "failed"
    assert state[1] is not None


@pytest.mark.asyncio
async def test_startup_recovery_closes_foreign_last_attempt_claim(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    claim, lease = await _claim_and_start_attempt(store, "event-recovery-terminal")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 1 WHERE event_id = ?",
            (lease.event_id,),
        )
        await db.commit()

    assert await store.recover_foreign_projection_jobs(consumer_name="new-worker") == 1

    outcomes = await store.list_claim_projection_outcomes(claim_id=claim["claim_id"])
    assert len(outcomes) == 1
    assert outcomes[0]["attempt_key"] == _job(lease).attempt_key
    assert outcomes[0]["target_id"] == f"projection_event:{lease.event_id}"
    assert outcomes[0]["reason_code"] == "pipeline_retry_budget_exhausted_on_startup"


@pytest.mark.asyncio
async def test_stale_recovery_preserves_multi_event_attempt_lineage(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    event_ids = ["event-recovery-batch-a", "event-recovery-batch-b"]
    for event_id in event_ids:
        assert await store.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 1 WHERE event_id IN (?, ?)",
            tuple(event_ids),
        )
        await db.commit()
    rows = await store.claim_projection_jobs(consumer_name="old-worker", limit=2)
    leases = [_lease(row) for row in rows]
    assert await store.bind_projection_job_batch(leases, consumer_name="old-worker") == 2
    assert await store.mark_projection_jobs_running(leases, consumer_name="old-worker") == 2
    job = _batch_job(leases)
    claims = [
        await _persist_claim_for_batch_event(
            store,
            event_id=event_id,
            leases=leases,
            attempt_key=job.attempt_key,
        )
        for event_id in event_ids
    ]
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET lease_heartbeat_at = 0, updated_at = 0
            WHERE event_id IN (?, ?)
            """,
            tuple(event_ids),
        )
        await db.commit()

    assert (
        await store.requeue_stale_projection_jobs(
            queued_timeout_seconds=1,
            running_timeout_seconds=1,
        )
        == 2
    )
    for claim in claims:
        outcomes = await store.list_claim_projection_outcomes(claim_id=claim["claim_id"])
        assert len(outcomes) == 1
        assert outcomes[0]["attempt_key"] == job.attempt_key
        assert outcomes[0]["target_id"] == f"projection_attempt:{job.attempt_key}"
        assert outcomes[0]["details"]["terminal_event_ids"] == sorted(event_ids)
    async with aiosqlite.connect(store.db_path) as db:
        states = await (
            await db.execute(
                """
                SELECT status, batch_attempt_key, batch_descriptor_json
                FROM l2_projection_jobs
                WHERE event_id IN (?, ?)
                ORDER BY event_id
                """,
                tuple(event_ids),
            )
        ).fetchall()
    assert states == [("failed", None, None), ("failed", None, None)]


@pytest.mark.asyncio
async def test_bound_last_attempt_failure_closes_owned_claim(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    claim, first = await _claim_and_start_attempt(store, "event-start-terminal")
    assert await store.fail_projection_jobs([first], error_text="temporary", requeue=True) == 1
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET next_retry_at = 0 WHERE event_id = ?",
            (first.event_id,),
        )
        await db.commit()
    second = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    assert await store.bind_projection_job_batch([second], consumer_name="worker") == 1
    stale_peer = L2ProjectionLease(
        event_id="missing-peer",
        lease_token="missing-token",
        attempt_count=second.attempt_count,
    )

    assert (
        await store.mark_projection_jobs_running(
            [second, stale_peer],
            consumer_name="worker",
        )
        == 0
    )

    assert await store.mark_projection_jobs_running([second], consumer_name="worker") == 1
    assert await store.fail_projection_jobs(
        [second],
        error_text="terminal",
        requeue=True,
    ) == 1

    outcomes = await store.list_claim_projection_outcomes(claim_id=claim["claim_id"])
    assert len(outcomes) == 1
    assert outcomes[0]["attempt_key"] == _job(second).attempt_key
    assert outcomes[0]["target_id"] == f"projection_event:{second.event_id}"
    assert outcomes[0]["reason_code"] == "pipeline_retry_budget_exhausted"
    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                "SELECT status, terminal_at FROM l2_projection_jobs WHERE event_id = ?",
                (second.event_id,),
            )
        ).fetchone()
    assert state[0] == "failed"
    assert state[1] is not None
