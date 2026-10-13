"""Provider failures through the L2 worker and its durable SQLite queue."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import httpx
import pytest

from magi.llm import LLMRequestPriority, LLMScenario
from magi.memory.l2.llm_json_client import (
    L2InvalidJsonResponseError,
    L2LLMCallError,
    L2LLMUnavailableError,
    _L2JsonCall,
    _L2JsonTarget,
)
from magi.memory.l2.llm_service import L2LLMService
from magi.memory.l2.models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.store import L2CognitionStore


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.invalid")
    return httpx.HTTPStatusError(
        "private-provider-payload-do-not-persist",
        request=request,
        response=httpx.Response(status, request=request),
    )


async def _provider_failure(monkeypatch, cause: Exception) -> L2LLMCallError:
    service = L2LLMService(None)
    provider_call = AsyncMock(side_effect=cause)
    monkeypatch.setattr(service, "_call_json_once", provider_call)
    monkeypatch.setattr(service, "_resolve_max_output_tokens", lambda **kwargs: 100)
    monkeypatch.setattr("magi.memory.l2.llm_json_client._RATE_LIMIT_BACKOFF_SECONDS", (0, 0, 0))
    with pytest.raises(L2LLMCallError) as caught:
        await service._call_json_with_retries(
            call=_L2JsonCall(
                system_prompt="system",
                prompt="synthetic evidence",
                request_kind="memory:l2_phase1_extract",
                turn_id=None,
                session_id=None,
                scenario=LLMScenario.AUXILIARY,
                disable_thinking=True,
                priority=LLMRequestPriority.LOW,
            ),
            target=_L2JsonTarget(adapter=None, provider_bridge=None),
            context={},
            started_at=time.perf_counter(),
        )
    assert provider_call.await_count == (4 if caught.value.status_code == 429 else 1)
    assert caught.value.__cause__ is cause
    return caught.value


def _pipeline(store: L2CognitionStore) -> L2Pipeline:
    return L2Pipeline(
        cognition_store=store,
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )


async def _claim_job(store: L2CognitionStore, pipeline: L2Pipeline) -> L2BatchJob:
    rows = await store.claim_projection_jobs(
        consumer_name=pipeline._projection_consumer_name, limit=1,
    )
    assert len(rows) == 1
    lease = L2ProjectionLease.from_dict(rows[0])
    assert await store.bind_projection_job_batch(
        [lease], consumer_name=pipeline._projection_consumer_name,
    ) == 1
    return L2BatchJob(
        job_id=f"projection:{lease.event_id}",
        bucket_key="owner:test",
        events=[{"event_id": lease.event_id, "content": "synthetic evidence", "timestamp": 1.0}],
        flush_reason="projection_ready",
        estimated_tokens=3,
        projection_leases=[lease],
    )


async def _row(store: L2CognitionStore) -> dict:
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        return dict(await (await db.execute("SELECT * FROM l2_projection_jobs")).fetchone())


async def _make_retry_due(store: L2CognitionStore) -> None:
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET next_retry_at = 0 WHERE status = 'pending'")
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause,kind,retryable",
    [
        (TimeoutError(), "timeout", True),
        (httpx.ConnectError("peer closed"), "service_unavailable", True),
        (_http_error(429), "rate_limit", True),
        (_http_error(503), "service_unavailable", True),
        (_http_error(529), "service_unavailable", True),
        (_http_error(401), "auth", False),
        (_http_error(422), "invalid_parameter", False),
        (RuntimeError("private-provider-payload-do-not-persist"), "unknown", False),
    ],
)
async def test_provider_failure_keeps_retry_policy_and_safe_diagnostics(
    l2_store_with_schema, monkeypatch, cause, kind, retryable,
) -> None:
    store = l2_store_with_schema
    error = await _provider_failure(monkeypatch, cause)
    assert error.error_kind.value == kind
    assert error.retryable is retryable
    assert await store.enqueue_projection_job(
        event_id="event-failure", source="chat", event_type="UserMessage",
    )
    pipeline = _pipeline(store)
    job = await _claim_job(store, pipeline)
    monkeypatch.setattr(pipeline, "_extract_and_persist", AsyncMock(side_effect=error))

    before_failure = time.time()
    await pipeline._process_extract_job(job)
    row = await _row(store)

    assert row["status"] == ("pending" if retryable else "failed")
    assert row["attempt_count"] == 1
    assert row["max_attempts"] == 5
    assert f"kind={kind}" in row["last_error"]
    assert f"cause={type(cause).__name__}" in row["last_error"]
    assert "private-provider-payload-do-not-persist" not in row["last_error"]
    if retryable:
        assert row["next_retry_at"] >= before_failure + 1.0
        assert row["terminal_at"] is None
    else:
        assert row["next_retry_at"] is None
        assert row["terminal_at"] is not None
    assert await store.claim_projection_jobs(consumer_name="too-early", limit=1) == []


@pytest.mark.asyncio
async def test_transient_failure_survives_store_restart_and_completes_once(
    l2_store_with_schema, monkeypatch,
) -> None:
    store = l2_store_with_schema
    assert await store.enqueue_projection_job(
        event_id="event-restart", source="chat", event_type="UserMessage",
    )
    first_pipeline = _pipeline(store)
    first_job = await _claim_job(store, first_pipeline)
    error = await _provider_failure(monkeypatch, TimeoutError())
    monkeypatch.setattr(first_pipeline, "_extract_and_persist", AsyncMock(side_effect=error))
    await first_pipeline._process_extract_job(first_job)
    before_restart = await _row(store)

    reopened = L2CognitionStore(db_path=store.db_path)
    await reopened.initialize()
    second_pipeline = _pipeline(reopened)
    assert await reopened.recover_foreign_projection_jobs(
        consumer_name=second_pipeline._projection_consumer_name,
    ) == 0
    assert (await _row(reopened))["next_retry_at"] == before_restart["next_retry_at"]
    assert await reopened.claim_projection_jobs(consumer_name="before-deadline", limit=1) == []

    await _make_retry_due(reopened)
    second_job = await _claim_job(reopened, second_pipeline)
    assert second_job.projection_leases[0].attempt_count == 2
    async def stage_success(job: L2BatchJob) -> dict[str, object]:
        await reopened.stage_event_entity_link_projections(
            desired_links_by_event={event_id: [] for event_id in job.event_ids},
            projection_leases=job.projection_leases,
        )
        return {"relation_count": 0, "assertion_count": 0, "skipped": True}

    success = AsyncMock(side_effect=stage_success)
    monkeypatch.setattr(second_pipeline, "_extract_and_persist", success)
    await second_pipeline._process_extract_job(second_job)
    assert (await _row(reopened))["status"] == "completed"
    success.assert_awaited_once()
    assert await reopened.claim_projection_jobs(consumer_name="duplicate", limit=1) == []


@pytest.mark.asyncio
async def test_transient_failures_stop_at_the_durable_attempt_budget(
    l2_store_with_schema, monkeypatch,
) -> None:
    store = l2_store_with_schema
    assert await store.enqueue_projection_job(
        event_id="event-budget", source="chat", event_type="UserMessage",
    )
    pipeline = _pipeline(store)
    error = await _provider_failure(monkeypatch, httpx.ConnectError("peer closed"))
    monkeypatch.setattr(pipeline, "_extract_and_persist", AsyncMock(side_effect=error))
    for attempt in range(1, 6):
        await _make_retry_due(store)
        job = await _claim_job(store, pipeline)
        before_failure = time.time()
        await pipeline._process_extract_job(job)
        row = await _row(store)
        assert row["attempt_count"] == attempt
        if attempt < 5:
            assert row["status"] == "pending"
            assert row["next_retry_at"] >= before_failure + 2 ** (attempt - 1)
        else:
            assert row["status"] == "failed"
            assert row["next_retry_at"] is None
            assert row["terminal_at"] is not None
    assert await store.claim_projection_jobs(consumer_name="over-budget", limit=1) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        L2InvalidJsonResponseError("invalid model response"),
        L2LLMUnavailableError("No L2 LLM adapter is available"),
    ],
)
async def test_permanent_model_errors_still_end_on_first_attempt(
    l2_store_with_schema, monkeypatch, error,
) -> None:
    store = l2_store_with_schema
    assert await store.enqueue_projection_job(
        event_id="event-permanent", source="chat", event_type="UserMessage",
    )
    pipeline = _pipeline(store)
    job = await _claim_job(store, pipeline)
    monkeypatch.setattr(pipeline, "_extract_and_persist", AsyncMock(side_effect=error))
    await pipeline._process_extract_job(job)
    row = await _row(store)
    assert (row["status"], row["attempt_count"], row["next_retry_at"]) == ("failed", 1, None)
