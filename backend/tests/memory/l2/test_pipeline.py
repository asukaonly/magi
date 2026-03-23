from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory import UnifiedMemoryStore
from magi.memory.event_contracts import normalize_runtime_event


class _FakeAdapter:
    def __init__(self, response: str | list[str]) -> None:
        if isinstance(response, list):
            self._responses = list(response)
        else:
            self._responses = [response]
        self._fallback_response = self._responses[-1] if self._responses else "{}"
        self.calls: list[dict[str, object]] = []
        self.provider_name = "openai"
        self.model_name = "gpt-test"
        self._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=self._create_completion),
            )
        )

    async def _create_completion(self, **kwargs):  # type: ignore[no-untyped-def]
        messages = kwargs.get("messages") or []
        system_prompt = str(kwargs.get("system_prompt") or "")
        prompt = ""
        if isinstance(messages, list):
            if not system_prompt and messages and isinstance(messages[0], dict):
                system_prompt = str(messages[0].get("content") or "")
            if len(messages) > 1 and isinstance(messages[1], dict):
                prompt = str(messages[1].get("content") or "")
            elif len(messages) == 1 and isinstance(messages[0], dict):
                prompt = str(messages[0].get("content") or "")
        call = {"prompt": prompt, "system_prompt": system_prompt}
        for key, value in kwargs.items():
            if key != "messages":
                call[key] = value
        self.calls.append(call)
        response_text = self._responses.pop(0) if self._responses else self._fallback_response
        message = SimpleNamespace(content=response_text, tool_calls=[], role="assistant")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=None,
        )


class _FakeScenarioPool:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self.adapter = adapter
        self.requested_scenarios: list[object] = []

    def get(self, scenario):  # type: ignore[no-untyped-def]
        self.requested_scenarios.append(scenario)
        return self.adapter


async def _build_pipeline(*, temp_dir: str, batch_flush_interval_seconds: int = 60):
    from magi.memory.l2.entity_catalog import L2EntityCatalog
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.store import L2CognitionStore

    memory_db = str(Path(temp_dir) / "memory.db")
    cognition_store = L2CognitionStore(db_path=memory_db)
    await cognition_store.initialize()
    entity_catalog = L2EntityCatalog(db_path=memory_db)
    await entity_catalog.initialize()
    pipeline = L2Pipeline(
        cognition_store,
        entity_catalog=entity_catalog,
        llm_service=L2LLMService(None),
        batch_flush_interval_seconds=batch_flush_interval_seconds,
    )
    return pipeline


def _make_memory_event(
    *,
    event_id: str,
    content: str = "hello",
    session_id: str | None = "s1",
    user_id: str | None = "u1",
    timestamp: float | None = None,
):
    resolved_timestamp = time.time() if timestamp is None else timestamp
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": user_id,
                "session_id": session_id,
                "content": content,
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id=f"corr-{event_id}",
            timestamp=resolved_timestamp,
        ),
        event_id=event_id,
    )


def test_reconcile_job_accepts_multiple_entities():
    from magi.memory.l2.models import L2EntityReconcileJob

    job = L2EntityReconcileJob(entity_ids=["user:u1", "place:shanghai"])

    assert job.job_type == "reconcile"
    assert job.entity_ids == ["place:shanghai", "user:u1"]
    assert job.batch_key == "entities:place:shanghai|user:u1"


def test_microbatch_bucket_tracks_pending_events_and_estimated_tokens():
    from magi.memory.l2.models import L2PendingBatchBucket

    bucket = L2PendingBatchBucket.for_owner(session_id="s1", user_id="u1")
    bucket.add_event(
        {
            "event_id": "evt-2",
            "timestamp": 2.0,
            "session_id": "s1",
            "user_id": "u1",
            "content": "second",
        },
        estimated_tokens=9,
    )
    bucket.add_event(
        {
            "event_id": "evt-1",
            "timestamp": 1.0,
            "session_id": "s1",
            "user_id": "u1",
            "content": "first",
        },
        estimated_tokens=7,
    )

    assert bucket.bucket_key == "session:s1"
    assert bucket.session_id == "s1"
    assert bucket.user_id == "u1"
    assert [item["event_id"] for item in bucket.events] == ["evt-2", "evt-1"]
    assert bucket.estimated_tokens == 16
    assert bucket.oldest_event_timestamp == 1.0
    assert bucket.newest_event_timestamp == 2.0


def test_microbatch_bucket_uses_enqueue_time_when_initialized_with_existing_events(monkeypatch: pytest.MonkeyPatch):
    from magi.memory.l2.models import L2PendingBatchBucket

    monkeypatch.setattr("magi.memory.l2.models.time.time", lambda: 1234.5)
    bucket = L2PendingBatchBucket(
        bucket_key="session:s1",
        session_id="s1",
        user_id="u1",
        events=[
            {"event_id": "evt-1", "timestamp": 1.0, "content": "first"},
            {"event_id": "evt-2", "timestamp": 2.0, "content": "second"},
        ],
    )

    assert bucket.created_at == 1234.5
    assert bucket.last_event_at == 1234.5
    assert bucket.oldest_event_timestamp == 1.0
    assert bucket.newest_event_timestamp == 2.0


def test_microbatch_job_captures_flush_reason_and_sorts_events_by_timestamp():
    from magi.memory.l2.models import L2PendingBatchBucket

    bucket = L2PendingBatchBucket.for_owner(user_id="u1")
    bucket.add_event(
        {
            "event_id": "evt-2",
            "timestamp": 20.0,
            "user_id": "u1",
            "content": "later",
        },
        estimated_tokens=8,
    )
    bucket.add_event(
        {
            "event_id": "evt-1",
            "timestamp": 10.0,
            "user_id": "u1",
            "content": "earlier",
        },
        estimated_tokens=6,
    )

    job = bucket.build_job(flush_reason="interval_elapsed")

    assert job.bucket_key == "user:u1"
    assert job.flush_reason == "interval_elapsed"
    assert job.event_ids == ["evt-1", "evt-2"]
    assert [item["event_id"] for item in job.events] == ["evt-1", "evt-2"]
    assert job.estimated_tokens == 14
    assert job.oldest_event_timestamp == 10.0
    assert job.newest_event_timestamp == 20.0


@pytest.mark.parametrize(
    ("session_id", "user_id", "expected"),
    [
        ("s1", "u1", "session:s1"),
        (None, "u1", "user:u1"),
        ("  ", "u1", "user:u1"),
        (None, None, None),
    ],
)
def test_microbatch_bucket_keys_normalize_session_and_user_owners(
    session_id: str | None,
    user_id: str | None,
    expected: str | None,
):
    from magi.memory.l2.models import build_l2_batch_bucket_key

    assert build_l2_batch_bucket_key(session_id=session_id, user_id=user_id) == expected


@pytest.mark.parametrize(
    ("text", "user_id"),
    [
        ("", "u1"),
        ("   ", "u1"),
        ("hello", ""),
    ],
)
def test_manual_l2_event_request_rejects_blank_text_or_user(text: str, user_id: str):
    from magi.memory.l2.models import ManualL2EventRequest

    with pytest.raises(ValueError):
        ManualL2EventRequest(text=text, user_id=user_id)


def test_contradiction_hint_and_reconcile_outcome_serialize_deterministically():
    from magi.memory.l2.models import ContradictionHint, ReconciledTraitOutcome

    hint = ContradictionHint(
        target_record_id="assert-1",
        target_record_type="tom_trait_assertion",
        contradiction_kind="preference_reversal",
        confidence=0.65,
        evidence_text="I do not like sushi anymore",
        recommended_action="downgrade_confidence",
    )
    outcome = ReconciledTraitOutcome(
        entity_id="user:u1",
        entity_type="user",
        trait_name="preference.food",
        winning_value="sushi",
        status="corroborated",
        confidence=0.7,
        evidence_event_ids=["evt-1", "evt-2"],
        time_span_hours=48.0,
        stability_kind="stable_trait",
        recommended_snapshot_field="preferences",
    )

    assert hint.to_dict() == {
        "target_record_id": "assert-1",
        "target_record_type": "tom_trait_assertion",
        "contradiction_kind": "preference_reversal",
        "confidence": 0.65,
        "evidence_text": "I do not like sushi anymore",
        "recommended_action": "downgrade_confidence",
    }
    assert outcome.to_dict() == {
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_name": "preference.food",
        "winning_value": "sushi",
        "status": "corroborated",
        "confidence": 0.7,
        "evidence_event_ids": ["evt-1", "evt-2"],
        "time_span_hours": 48.0,
        "stability_kind": "stable_trait",
        "recommended_snapshot_field": "preferences",
    }


def test_normalized_memory_event_uses_canonical_text_fields():
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "user_id": "web_user",
            "session_id": "s1",
            "turn_id": "turn-1",
            "content": "hello",
            "author_type": "user",
            "content_type": "text",
        },
        source="chat",
        level=EventLevel.INFO,
        correlation_id="corr-canonical-text",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.user_id == "web_user"
    assert normalized.session_id == "s1"
    assert normalized.turn_id == "turn-1"
    assert normalized.content == "hello"
    assert normalized.author_type == "user"
    assert normalized.content_type == "text"


@pytest.mark.asyncio
async def test_l1_round_trip_preserves_canonical_text_fields():
    from magi.memory.l1.event_store import L1EventStore

    with tempfile.TemporaryDirectory() as temp_dir:
        store = L1EventStore(db_path=str(Path(temp_dir) / "l1_events.db"), vector_enabled=False)
        await store.initialize()
        try:
            normalized = normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "web_user",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "content": "hello",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-canonical-roundtrip",
                )
            )

            await store.store(normalized)
            restored = await store.get_memory_event(normalized.event_id)

            assert restored is not None
            assert restored.user_id == "web_user"
            assert restored.turn_id == "turn-1"
            assert restored.content == "hello"
            assert restored.author_type == "user"
            assert restored.content_type == "text"
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_ingest_event_enqueues_l2_work_and_returns_without_sync_l2_counts():
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
        )
        await store.initialize()
        try:
            result = await store.ingest_event(
                {
                    "id": "evt-queue-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I have been stressed about work.",
                    },
                }
            )
            assert result["l1_written"] is True
            assert result["l2_relation_count"] == 0
            assert result["l2_assertion_count"] == 0

            stats = store.get_l2_pipeline_stats()
            assert stats["extract_enqueued"] == 1

            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            final_stats = store.get_l2_pipeline_stats()
            assert final_stats["extract_completed"] == 1
            assert final_stats["assertions_written"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_cognition_ineligible_event_is_not_enqueued_for_l2():
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-queue-2",
                    "type": EventTypes.TASK_COMPLETED,
                    "timestamp": time.time(),
                    "source": "runtime",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "task_id": "task-1",
                        "success": True,
                    },
                }
            )

            stats = store.get_l2_pipeline_stats()
            assert stats["extract_enqueued"] == 0
            assert stats["extract_skipped"] == 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_shutdown_drains_l2_pipeline_workers_cleanly():
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
        )
        await store.initialize()
        await store.ingest_event(
            {
                "id": "evt-queue-3",
                "type": EventTypes.USER_MESSAGE,
                "timestamp": time.time(),
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I feel calm now.",
                },
            }
        )

        await store.shutdown()

        stats = store.get_l2_pipeline_stats()
        assert stats["is_running"] is False


@pytest.mark.asyncio
async def test_l2_pipeline_starts_with_five_extract_workers():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.start()

            assert pipeline._extract_worker_count == 5
            assert len(pipeline._extract_workers) == 5
            assert all(worker is not None and not worker.done() for worker in pipeline._extract_workers)
        finally:
            await pipeline.shutdown()


def test_l2_pipeline_requires_entity_catalog_and_llm_service():
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.store import L2CognitionStore

    with tempfile.TemporaryDirectory() as temp_dir:
        cognition_store = L2CognitionStore(db_path=str(Path(temp_dir) / "memory.db"))

        with pytest.raises(ValueError, match="entity_catalog"):
            L2Pipeline(cognition_store)

        with pytest.raises(ValueError, match="entity_catalog"):
            L2Pipeline(cognition_store, llm_service=SimpleNamespace())

        with pytest.raises(ValueError, match="llm_service"):
            L2Pipeline(cognition_store, entity_catalog=SimpleNamespace())


def test_unified_memory_store_wires_l2_batch_flush_interval_into_pipeline():
    store = UnifiedMemoryStore(
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=90,
        enable_l2_conflict_arbitration=False,
        l2_conflict_arbitration_min_confidence=0.9,
    )

    assert store.l2_pipeline is not None
    assert store.l2_pipeline._batch_flush_interval_seconds == 90
    assert store.l2_pipeline._enable_conflict_arbitration is False
    assert store.l2_pipeline._conflict_arbitration_min_confidence == 0.9


@pytest.mark.asyncio
async def test_enqueue_event_stages_session_owned_events_before_extraction():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            queued = await pipeline.enqueue_event(_make_memory_event(event_id="evt-stage-1", session_id="s-session"))

            assert queued is True
            assert "session:s-session" in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 0
            stats = pipeline.get_statistics()
            assert stats["extract_enqueued"] == 0
            assert stats["pending_staged_event_count"] == 1
            assert stats["active_bucket_count"] == 1
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_reuses_same_bucket_for_matching_session():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        now = time.time()
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.enqueue_event(_make_memory_event(event_id="evt-stage-2a", session_id="s-shared", timestamp=now))
            await pipeline.enqueue_event(_make_memory_event(event_id="evt-stage-2b", session_id="s-shared", timestamp=now + 1.0))

            bucket = pipeline._staging_buckets["session:s-shared"]
            assert [item["event_id"] for item in bucket.events] == ["evt-stage-2a", "evt-stage-2b"]
            assert pipeline.get_statistics()["pending_staged_event_count"] == 2
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_falls_back_to_user_bucket_without_session():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.enqueue_event(_make_memory_event(event_id="evt-stage-3", session_id=None, user_id="u-bucket"))

            assert "user:u-bucket" in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 0
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_without_session_or_user_uses_direct_fallback_job():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.enqueue_event(_make_memory_event(event_id="evt-stage-4", session_id=None, user_id=None))

            assert pipeline._staging_buckets == {}
            assert pipeline._extract_queue.qsize() == 1
            stats = pipeline.get_statistics()
            assert stats["extract_enqueued"] == 1
            assert stats["pending_staged_event_count"] == 0
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_flush_ready_buckets_enqueues_interval_elapsed_batch_job():
    from magi.memory.l2.models import L2PendingBatchBucket
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            bucket = L2PendingBatchBucket.for_owner(session_id="s-flush", user_id="u1")
            bucket.add_event(
                {"event_id": "evt-flush-1", "timestamp": time.time() - 61, "session_id": "s-flush", "user_id": "u1"},
                estimated_tokens=8,
                queued_at=time.time() - 61,
            )
            pipeline._staging_buckets[bucket.bucket_key] = bucket
            pipeline._refresh_staging_stats_locked()

            await pipeline._flush_ready_buckets()

            assert pipeline._extract_queue.qsize() == 1
            job = pipeline._extract_queue.get_nowait()
            assert job is not None
            assert job.flush_reason == "interval_elapsed"
            assert job.event_ids == ["evt-flush-1"]
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_flushes_when_bucket_hits_event_cap():
    from magi.memory.l2.pipeline import DEFAULT_L2_MAX_EVENTS_PER_BATCH, L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        now = time.time()
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            for index in range(DEFAULT_L2_MAX_EVENTS_PER_BATCH):
                await pipeline.enqueue_event(
                    _make_memory_event(
                        event_id=f"evt-cap-{index}",
                        session_id="s-cap",
                        timestamp=now + index,
                    )
                )

            assert "session:s-cap" not in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 1
            job = pipeline._extract_queue.get_nowait()
            assert job is not None
            assert job.flush_reason == "max_events"
            assert len(job.event_ids) == DEFAULT_L2_MAX_EVENTS_PER_BATCH
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_does_not_flush_immediately_for_historical_business_timestamp():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.enqueue_event(
                _make_memory_event(
                    event_id="evt-historical-1",
                    session_id="s-historical",
                    timestamp=1.0,
                )
            )

            assert pipeline._extract_queue.qsize() == 0
            assert "session:s-historical" in pipeline._staging_buckets
            stats = pipeline.get_statistics()
            assert stats["pending_staged_event_count"] == 1
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_flushes_when_bucket_hits_token_cap():
    from magi.memory.l2.pipeline import L2Pipeline

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.enqueue_event(
                _make_memory_event(
                    event_id="evt-token-cap",
                    session_id="s-token",
                    content="x" * 10000,
                )
            )

            assert "session:s-token" not in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 1
            job = pipeline._extract_queue.get_nowait()
            assert job is not None
            assert job.flush_reason == "token_cap"
            assert job.estimated_tokens >= 2400
        finally:
            await pipeline.shutdown()


def test_contradiction_and_reconcile_prompt_rendering_is_deterministic():
    from magi.memory.l2.prompts import (
        render_contradiction_hint_prompt,
        render_entity_reconcile_prompt,
    )

    contradiction_prompt = render_contradiction_hint_prompt(
        new_event={"event_id": "evt-1", "text": "I do not like sushi anymore."},
        existing_records=[{"record_id": "triple-1", "predicate": "LIKES", "object_id": "food:sushi"}],
    )
    reconcile_prompt = render_entity_reconcile_prompt(
        entity={"entity_id": "user:u1", "entity_type": "user"},
        graph_facts=[{"predicate": "LIKES", "object_id": "food:sushi"}],
        assertions=[{"trait_name": "stress_level", "trait_value": "high"}],
        recent_events=[{"event_id": "evt-1", "raw_content": "I am stressed."}],
    )

    assert '"event_id": "evt-1"' in contradiction_prompt
    assert '"predicate": "LIKES"' in contradiction_prompt
    assert '"entity_id": "user:u1"' in reconcile_prompt
    assert '"trait_name": "stress_level"' in reconcile_prompt


@pytest.mark.asyncio
async def test_low_confidence_resolution_is_returned_as_unresolved():
    from magi.memory.l2.llm_service import L2LLMService

    response = json.dumps(
        {
            "resolution": {
                "decision": "match",
                "matched_entity_id": "place:shanghai",
                "matched_entity_name": "Shanghai",
                "confidence": 0.4,
                "reason_tags": ["nickname_match"],
                "should_merge": True,
                "canonical_name_suggestion": "Shanghai",
            }
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    resolution = await service.resolve_entity(
        mention={"mention_text": "魔都", "entity_type": "place", "context_text": "我好喜欢魔都"},
        candidate_entities=[{"entity_id": "place:shanghai", "canonical_name": "Shanghai", "entity_type": "place"}],
    )

    assert resolution["decision"] == "unresolved"
    assert resolution["matched_entity_id"] is None


@pytest.mark.asyncio
async def test_invalid_json_from_contradiction_and_reconcile_llm_fails_closed():
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(["not-json", "still-not-json"])))

    hints = await service.detect_contradiction_hints(
        new_event={"event_id": "evt-1"},
        existing_records=[{"record_id": "triple-1"}],
    )
    outcomes = await service.reconcile_entity_state(
        entity={"entity_id": "user:u1", "entity_type": "user"},
        graph_facts=[],
        assertions=[],
        recent_events=[],
    )

    assert hints == []
    assert outcomes == []


@pytest.mark.asyncio
async def test_extract_worker_records_mentions_and_resolved_graph_edge():
    responses = [
        json.dumps(
            {
                "mentions": [
                    {
                        "mention_text": "魔都",
                        "normalized_surface": "魔都",
                        "entity_type": "place",
                        "canonical_name_hint": "上海",
                        "alias_signals": ["魔都"],
                        "evidence_text": "我好喜欢魔都",
                        "confidence": 0.96,
                    }
                ],
                "graph_candidates": [],
                "assertion_candidates": [],
                "diagnostics": {"entity_status": "found"},
            }
        ),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(_FakeAdapter(responses)),
        )
        await store.initialize()
        try:
            assert store.l2_entity_catalog is not None
            await store.l2_entity_catalog.upsert_entity(
                entity_id="place:shanghai",
                canonical_name="Shanghai",
                entity_type="place",
            )
            await store.l2_entity_catalog.add_alias(
                entity_id="place:shanghai",
                alias_text="魔都",
                confidence=0.98,
            )

            await store.ingest_event(
                {
                    "id": "evt-graph-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "我好喜欢魔都",
                    },
                }
            )

            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            mentions = await store.l2_entity_catalog.list_mentions(limit=10)
            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []

            assert mentions[0]["mention_text"] == "魔都"
            assert mentions[0]["resolved_entity_id"] == "place:shanghai"
            assert any(
                edge["predicate"] == "LIKES" and edge["object_id"] == "place:shanghai"
                for edge in relationships
            )
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_resolve_mentions_returns_typed_mentions():
    from magi.memory.l2.models import ResolvedEntityMention

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            event = _make_memory_event(event_id="evt-resolve-mention", content="我好喜欢魔都")
            resolved_mentions = await pipeline._resolve_mentions(
                event,
                [
                    {
                        "mention_text": "魔都",
                        "normalized_surface": "魔都",
                        "entity_type": "place",
                        "canonical_name_hint": "上海",
                        "alias_signals": ["魔都"],
                        "evidence_text": "我好喜欢魔都",
                        "confidence": 0.96,
                    }
                ],
                evidence_event_ids=[event.event_id],
            )

            assert len(resolved_mentions) == 1
            assert isinstance(resolved_mentions[0], ResolvedEntityMention)
            assert resolved_mentions[0].mention_text == "魔都"
            assert resolved_mentions[0].normalized_surface == "魔都"
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_build_focal_entities_returns_typed_refs():
    from magi.memory.l2.models import L2FocalEntityRef, ResolvedEntityMention

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            event = _make_memory_event(event_id="evt-focal-entities", content="我喜欢魔都")
            focal_entities = pipeline._build_focal_entities(
                event,
                [
                    ResolvedEntityMention(
                        mention_text="魔都",
                        normalized_surface="魔都",
                        entity_type="place",
                        resolved_entity_id="place:shanghai",
                        confidence=0.96,
                    )
                ],
            )

            assert [item.entity_id for item in focal_entities] == ["user:u1", "place:shanghai"]
            assert all(isinstance(item, L2FocalEntityRef) for item in focal_entities)
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_uses_recent_session_context_in_mention_prompt():
    from magi.memory.l2.prompts import UNIFIED_EXTRACTION_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "mentions": [],
                    "graph_candidates": [],
                    "assertion_candidates": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
            json.dumps(
                {
                    "mentions": [],
                    "graph_candidates": [],
                    "assertion_candidates": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
        ]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-context-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time() - 30,
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I call Shanghai Modu sometimes.",
                    },
                }
            )
            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            await store.ingest_event(
                {
                    "id": "evt-context-2",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I like Shanghai.",
                    },
                }
            )
            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 2:
                    break
                await asyncio.sleep(0.01)

            unified_prompts = [
                str(call["prompt"])
                for call in adapter.calls
                if call.get("system_prompt") == UNIFIED_EXTRACTION_SYSTEM_PROMPT
            ]

            assert len(unified_prompts) == 2
            assert "I like Shanghai." in unified_prompts[1]
            assert "I call Shanghai Modu sometimes." in unified_prompts[1]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_uses_related_cross_session_history_in_unified_prompt():
    from magi.memory.l2.prompts import UNIFIED_EXTRACTION_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "mentions": [],
                    "graph_candidates": [],
                    "assertion_candidates": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
        ]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l1 is not None
            assert store.l2_entity_catalog is not None
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-history-1",
                    session_id="s-old",
                    user_id="u1",
                    timestamp=time.time() - 60,
                    content="I call Shanghai Modu sometimes.",
                )
            )
            await store.l2_entity_catalog.upsert_entity(
                canonical_name="Shanghai",
                entity_type="place",
                entity_id="place:shanghai",
            )
            await store.l2_entity_catalog.add_alias(entity_id="place:shanghai", alias_text="Modu")

            await store.ingest_event(
                {
                    "id": "evt-history-2",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-new",
                        "content": "I still like Modu.",
                    },
                }
            )
            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            unified_prompts = [
                str(call["prompt"])
                for call in adapter.calls
                if call.get("system_prompt") == UNIFIED_EXTRACTION_SYSTEM_PROMPT
            ]

            assert len(unified_prompts) == 1
            assert "I still like Modu." in unified_prompts[0]
            assert "I call Shanghai Modu sometimes." in unified_prompts[0]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_orders_history_contexts_chronologically_in_prompt():
    from magi.memory.l2.prompts import UNIFIED_EXTRACTION_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "mentions": [],
                    "graph_candidates": [],
                    "assertion_candidates": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
        ]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l1 is not None
            assert store.l2_entity_catalog is not None
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-history-early",
                    session_id="s-old-1",
                    user_id="u1",
                    timestamp=100.0,
                    content="I called Shanghai Modu years ago.",
                )
            )
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-history-late",
                    session_id="s-old-2",
                    user_id="u1",
                    timestamp=200.0,
                    content="I still call Shanghai Modu now.",
                )
            )
            await store.l2_entity_catalog.upsert_entity(
                canonical_name="Shanghai",
                entity_type="place",
                entity_id="place:shanghai",
            )
            await store.l2_entity_catalog.add_alias(entity_id="place:shanghai", alias_text="Modu")

            await store.ingest_event(
                {
                    "id": "evt-history-anchor",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": 300.0,
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-new",
                        "content": "Modu is still my favorite city.",
                    },
                }
            )
            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            unified_prompts = [
                str(call["prompt"])
                for call in adapter.calls
                if call.get("system_prompt") == UNIFIED_EXTRACTION_SYSTEM_PROMPT
            ]

            assert len(unified_prompts) == 1
            prompt = unified_prompts[0]
            assert prompt.index("I called Shanghai Modu years ago.") < prompt.index("I still call Shanghai Modu now.")
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_persists_llm_tom_assertions():
    responses = [
        json.dumps(
            {
                "mentions": [],
                "graph_candidates": [],
                "assertion_candidates": [
                    {
                        "entity_ref": "user:u1",
                        "entity_type": "user",
                        "trait_family": "stress",
                        "trait_name": "stress_level",
                        "trait_value": "high",
                        "inference_depth": "defensive_psychology",
                        "volatility_index": 0.7,
                        "confidence": 0.94,
                        "validation_state": "tentative",
                        "evidence_texts": ["I am stressed about work today."],
                        "supporting_event_ids": ["evt-stress-1"],
                        "notes": None,
                    }
                ],
                "diagnostics": {"entity_status": "none"},
            }
        ),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(_FakeAdapter(responses)),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-stress-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I am stressed about work today.",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["assertions_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            assert len(assertions) == 1
            assert assertions[0]["trait_name"] == "stress_level"
            assert assertions[0]["validation_state"] == "tentative"
            assert assertions[0]["confidence_score"] == 0.3
            assert store.get_l2_pipeline_stats()["reconcile_enqueued"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_applies_contradiction_hints_to_existing_assertions():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l2 is not None
            assert store.l1 is not None
            for event_id, ts in (
                ("evt-old-1", 1710000000.0),
                ("evt-old-2", 1710090000.0),
                ("evt-old-3", 1710185000.0),
            ):
                await store.l1.store(
                    normalize_runtime_event(
                        Event(
                            type=EventTypes.USER_MESSAGE,
                            data={"user_id": "u1", "session_id": "s1", "content": f"Historical stress evidence {event_id}"},
                            source="chat",
                            level=EventLevel.INFO,
                            correlation_id=event_id,
                            timestamp=ts,
                        ),
                        event_id=event_id,
                    )
                )
            await store.l2.upsert_assertion_candidate(
                {
                    "assertion_id": "assert-existing",
                    "entity_id": "user:u1",
                    "entity_type": "user",
                    "trait_name": "stress_level",
                    "trait_value": "high",
                    "confidence_score": 0.84,
                    "evidence_events": ["evt-old-1", "evt-old-2", "evt-old-3"],
                    "volatility_index": 0.7,
                    "source_domain": "user_authored",
                    "inference_depth": "defensive_psychology",
                    "validation_state": "stable",
                    "first_inferred_at": 1710000000.0,
                    "last_validated_at": 1710185000.0,
                }
            )
            existing_assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            existing_assertion_id = existing_assertions[0]["assertion_id"]
            adapter._responses = [
                json.dumps(
                    {
                        "mentions": [],
                        "graph_candidates": [],
                        "assertion_candidates": [],
                        "diagnostics": {"entity_status": "none"},
                    }
                ),
                json.dumps(
                    {
                        "contradiction_hints": [
                            {
                                "target_record_id": existing_assertion_id,
                                "target_record_type": "tom_trait_assertion",
                                "contradiction_kind": "state_reversal",
                                "confidence": 0.88,
                                "evidence_text": "I feel calm and relaxed now.",
                                "recommended_action": "downgrade_confidence",
                            }
                        ]
                    }
                ),
            ]

            await store.ingest_event(
                {
                    "id": "evt-calm-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I feel calm and relaxed now.",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["reconcile_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            summaries = await store.l3.list_summaries(limit=10) if store.l3 is not None else []

            assert assertions[0]["assertion_id"] == existing_assertion_id
            assert assertions[0]["validation_state"] == "contradicted"
            assert assertions[0]["confidence_score"] < 0.84
            assert any(item["summary_category"] == "conflict_resolution" for item in summaries)
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_uses_conflict_arbitration_to_keep_existing_graph_fact():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l2 is not None
            assert store.l1 is not None
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-like-1",
                    session_id="s-old",
                    user_id="u1",
                    timestamp=1710000000.0,
                    content="I love Shanghai.",
                )
            )
            existing_triple_id = await store.l2.upsert_knowledge_edge(
                subject_id="user:u1",
                subject_type="user",
                predicate="LIKES",
                object_id="place:shanghai",
                object_type="place",
                evidence_event_ids=["evt-like-1"],
                confidence=0.91,
                observed_at=1710000000.0,
                source_type="chat",
                extraction_method="llm",
            )
            adapter._responses = [
                json.dumps(
                    {
                        "mentions": [],
                        "graph_candidates": [
                            {
                                "subject_ref": "user:u1",
                                "subject_type": "user",
                                "predicate": "DISLIKES",
                                "object_ref": "place:shanghai",
                                "object_type": "place",
                                "fact_kind": "stable_preference",
                                "polarity": "negative",
                                "evidence_text": "I hate Shanghai now.",
                                "confidence": 0.94,
                            }
                        ],
                        "assertion_candidates": [],
                        "diagnostics": {"entity_status": "none"},
                    }
                ),
                json.dumps(
                    {
                        "contradiction_hints": [
                            {
                                "target_record_id": existing_triple_id,
                                "target_record_type": "knowledge_graph",
                                "contradiction_kind": "preference_reversal",
                                "confidence": 0.93,
                                "evidence_text": "I hate Shanghai now.",
                                "recommended_action": "mark_deprecated",
                            }
                        ]
                    }
                ),
                json.dumps(
                    {
                        "decision": "keep_existing",
                        "winning_record_ids": [existing_triple_id],
                        "superseded_record_ids": [],
                        "reason": "The new statement is too weak to overturn the established preference.",
                    }
                ),
            ]

            await store.ingest_event(
                {
                    "id": "evt-hate-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-new",
                        "content": "I hate Shanghai now.",
                    },
                }
            )

            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            active_edges = await store.l2.get_relationships(subject_id="user:u1", status="active", limit=10)
            deprecated_edges = await store.l2.get_relationships(subject_id="user:u1", status="deprecated", limit=10)

            assert len(active_edges) == 1
            assert active_edges[0]["triple_id"] == existing_triple_id
            assert active_edges[0]["predicate"] == "LIKES"
            assert active_edges[0]["last_confirmed_at"] > 1710000000.0
            assert deprecated_edges == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_marks_evolution_by_deprecating_old_graph_fact_and_keeping_new_one():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l2 is not None
            await store.l2.upsert_knowledge_edge(
                subject_id="user:u1",
                subject_type="user",
                predicate="LIKES",
                object_id="place:shanghai",
                object_type="place",
                evidence_event_ids=["evt-like-1"],
                confidence=0.91,
                observed_at=1710000000.0,
                source_type="chat",
                extraction_method="llm",
            )
            previous_edge = (await store.l2.get_relationships(subject_id="user:u1", status="active", limit=10))[0]
            adapter._responses = [
                json.dumps(
                    {
                        "mentions": [],
                        "graph_candidates": [
                            {
                                "subject_ref": "user:u1",
                                "subject_type": "user",
                                "predicate": "DISLIKES",
                                "object_ref": "place:shanghai",
                                "object_type": "place",
                                "fact_kind": "stable_preference",
                                "polarity": "negative",
                                "evidence_text": "I hate Shanghai these days.",
                                "confidence": 0.94,
                            }
                        ],
                        "assertion_candidates": [],
                        "diagnostics": {"entity_status": "none"},
                    }
                ),
                json.dumps(
                    {
                        "contradiction_hints": [
                            {
                                "target_record_id": previous_edge["triple_id"],
                                "target_record_type": "knowledge_graph",
                                "contradiction_kind": "preference_reversal",
                                "confidence": 0.92,
                                "evidence_text": "I hate Shanghai these days.",
                                "recommended_action": "revalidate_only",
                            }
                        ]
                    }
                ),
                json.dumps(
                    {
                        "decision": "mark_evolution",
                        "winning_record_ids": [],
                        "superseded_record_ids": [previous_edge["triple_id"]],
                        "reason": "The user's preference appears to have evolved over time.",
                    }
                ),
            ]

            await store.ingest_event(
                {
                    "id": "evt-evolution-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-new",
                        "content": "I hate Shanghai these days.",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            active_edges = await store.l2.get_relationships(subject_id="user:u1", status="active", limit=10)
            deprecated_edges = await store.l2.get_relationships(subject_id="user:u1", status="deprecated", limit=10)
            stats = store.get_l2_pipeline_stats()

            assert len(active_edges) == 1
            assert active_edges[0]["predicate"] == "DISLIKES"
            assert len(deprecated_edges) == 1
            assert deprecated_edges[0]["triple_id"] == previous_edge["triple_id"]
            assert stats["conflict_arbitration_triggered"] == 1
            assert stats["conflict_arbitration_by_decision"]["mark_evolution"] == 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_refreshes_snapshot_after_graph_mark_evolution():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l2 is not None
            await store.l2.upsert_knowledge_edge(
                subject_id="user:u1",
                subject_type="user",
                predicate="LIKES",
                object_id="place:shanghai",
                object_type="place",
                evidence_event_ids=["evt-like-1"],
                confidence=0.91,
                observed_at=1710000000.0,
                source_type="chat",
                extraction_method="llm",
            )
            previous_edge = (await store.l2.get_relationships(subject_id="user:u1", status="active", limit=10))[0]
            seeded_snapshot = await store.l2.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
            assert seeded_snapshot is not None
            assert seeded_snapshot["preferences"]["place:shanghai"] == "like"

            adapter._responses = [
                json.dumps(
                    {
                        "mentions": [],
                        "graph_candidates": [
                            {
                                "subject_ref": "user:u1",
                                "subject_type": "user",
                                "predicate": "DISLIKES",
                                "object_ref": "place:shanghai",
                                "object_type": "place",
                                "fact_kind": "stable_preference",
                                "polarity": "negative",
                                "evidence_text": "I hate Shanghai these days.",
                                "confidence": 0.94,
                            }
                        ],
                        "assertion_candidates": [],
                        "diagnostics": {"entity_status": "none"},
                    }
                ),
                json.dumps(
                    {
                        "contradiction_hints": [
                            {
                                "target_record_id": previous_edge["triple_id"],
                                "target_record_type": "knowledge_graph",
                                "contradiction_kind": "preference_reversal",
                                "confidence": 0.92,
                                "evidence_text": "I hate Shanghai these days.",
                                "recommended_action": "revalidate_only",
                            }
                        ]
                    }
                ),
                json.dumps(
                    {
                        "decision": "mark_evolution",
                        "winning_record_ids": [],
                        "superseded_record_ids": [previous_edge["triple_id"]],
                        "reason": "The user's preference appears to have evolved over time.",
                    }
                ),
            ]

            await store.ingest_event(
                {
                    "id": "evt-evolution-2",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-new",
                        "content": "I hate Shanghai these days.",
                    },
                }
            )

            for _ in range(80):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["snapshot_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            snapshot = await store.l2.get_tom_snapshot(entity_id="user:u1", entity_type="user")
            stats = store.get_l2_pipeline_stats()

            assert snapshot is not None
            assert snapshot["preferences"]["place:shanghai"] == "dislike"
            assert snapshot["preferences_history"][0]["field"] == "place:shanghai"
            assert snapshot["preferences_history"][0]["from"] == "like"
            assert snapshot["preferences_history"][0]["to"] == "dislike"
            assert stats["snapshot_completed"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_response_action_runtime_event_is_skipped_before_llm_extraction():
    adapter = _FakeAdapter(json.dumps({"mentions": [], "graph_candidates": [], "assertion_candidates": []}))

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                Event(
                    type="ActionExecuted",
                    data={
                        "agent_id": "chat:web_user",
                        "event_type": "UserMessage",
                        "action_type": "ChatResponseAction",
                        "content": "懂你，这种天气确实烦。",
                        "user_id": "web_user",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "success": True,
                    },
                    source="runtime_action_emitter",
                    level=EventLevel.INFO,
                    correlation_id="evt-runtime-chat-1",
                    timestamp=time.time(),
                )
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_skipped"] >= 1:
                    break
                await asyncio.sleep(0.01)

            stats = store.get_l2_pipeline_stats()
            assert stats["extract_by_evidence_class"]["assistant_runtime_derivation"] >= 1
            assert stats["skip_by_reason"]["assistant_runtime_derivation"] >= 1
            assert adapter.calls == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_assistant_freeform_event_is_skipped_before_llm_extraction():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-ai-freeform-1",
                    "type": EventTypes.AI_RESPONSE,
                    "timestamp": time.time(),
                    "source": "assistant",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "You might enjoy Hangzhou weather this week.",
                        "author_type": "assistant",
                        "content_type": "text",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            stats = store.get_l2_pipeline_stats()
            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            assert stats["extract_completed"] >= 1
            assert stats["extract_skipped"] >= 1
            assert relationships == []
            assert assertions == []
            assert adapter.calls == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_assistant_tool_grounded_event_is_skipped_before_llm_extraction():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-ai-tool-1",
                    "type": EventTypes.AI_RESPONSE,
                    "timestamp": time.time(),
                    "source": "assistant",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "According to the weather tool, Hangzhou is 17C right now.",
                        "author_type": "assistant",
                        "content_type": "tool_result",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []
            stats = store.get_l2_pipeline_stats()

            assert stats["extract_completed"] >= 1
            assert stats["extract_skipped"] >= 1
            assert relationships == []
            assert assertions == []
            assert adapter.calls == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_assistant_quote_does_not_add_new_evidence_weight():
    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "mentions": [],
                    "graph_candidates": [],
                    "assertion_candidates": [
                        {
                            "entity_ref": "user:u1",
                            "entity_type": "user",
                            "trait_family": "stress",
                            "trait_name": "stress_level",
                            "trait_value": "high",
                            "inference_depth": "defensive_psychology",
                            "volatility_index": 0.7,
                            "confidence": 0.88,
                            "validation_state": "tentative",
                            "evidence_texts": ["I am stressed about work today."],
                            "supporting_event_ids": ["evt-user-stress-1"],
                            "notes": None,
                        }
                    ],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
        ]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-user-stress-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I am stressed about work today.",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["assertions_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            before_assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []
            before_call_count = len(adapter.calls)

            await store.ingest_event(
                {
                    "id": "evt-ai-quote-1",
                    "type": EventTypes.AI_RESPONSE,
                    "timestamp": time.time() + 1,
                    "source": "assistant",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "You mentioned earlier that you feel stressed about work today.",
                        "author_type": "assistant",
                        "content_type": "text",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 2:
                    break
                await asyncio.sleep(0.01)

            after_assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []
            stats = store.get_l2_pipeline_stats()

            assert len(before_assertions) == 1
            assert len(after_assertions) == 1
            assert after_assertions[0]["assertion_id"] == before_assertions[0]["assertion_id"]
            assert after_assertions[0]["evidence_events"] == ["evt-user-stress-1"]
            assert after_assertions[0]["confidence_score"] == before_assertions[0]["confidence_score"]
            assert len(adapter.calls) == before_call_count
            assert stats["extract_skipped"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_pipeline_stats_track_evidence_class_and_skip_reason_breakdown():
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-user-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I like sushi.",
                    },
                }
            )
            await store.ingest_event(
                {
                    "id": "evt-ai-freeform-2",
                    "type": EventTypes.AI_RESPONSE,
                    "timestamp": time.time() + 1,
                    "source": "assistant",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "You might want sushi for dinner.",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 2:
                    break
                await asyncio.sleep(0.01)

            stats = store.get_l2_pipeline_stats()

            assert stats["extract_by_evidence_class"]["user_self_report"] >= 1
            assert stats["extract_by_evidence_class"]["assistant_freeform"] >= 1
            assert stats["skip_by_reason"]["assistant_freeform"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_pipeline_logs_skip_decision_with_evidence_context(caplog: pytest.LogCaptureFixture):
    adapter = _FakeAdapter("{}")

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            with caplog.at_level(logging.INFO, logger="magi.memory.l2.pipeline"):
                await store.ingest_event(
                    {
                        "id": "evt-ai-freeform-log-1",
                        "type": EventTypes.AI_RESPONSE,
                        "timestamp": time.time(),
                        "source": "assistant",
                        "level": EventLevel.INFO.value,
                        "data": {
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": "You might enjoy sushi tonight.",
                        },
                    }
                )

                for _ in range(50):
                    stats = store.get_l2_pipeline_stats()
                    if stats["extract_completed"] >= 1:
                        break
                    await asyncio.sleep(0.01)

            messages = [record.getMessage() for record in caplog.records if record.name == "magi.memory.l2.pipeline"]
            assert any("L2 extract started" in message for message in messages)
            assert any("L2 extract skipped" in message for message in messages)
            assert any("assistant_freeform" in message for message in messages)
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_pipeline_logs_profile_and_rejection_counts_for_unified_extraction(
    caplog: pytest.LogCaptureFixture,
):
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [
                    {
                        "mention_text": "GitHub",
                        "normalized_surface": "github",
                        "entity_type": "product",
                        "canonical_name_hint": "GitHub",
                        "alias_signals": [],
                        "evidence_text": "Visited GitHub today",
                        "confidence": 0.95,
                    }
                ],
                "graph_candidates": [
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "VISITED",
                        "object_ref": "GitHub",
                        "object_type": "product",
                        "fact_kind": "explicit_fact",
                        "polarity": "positive",
                        "evidence_text": "Visited GitHub today",
                        "confidence": 0.9,
                    },
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "LIKES",
                        "object_ref": "GitHub",
                        "object_type": "product",
                        "fact_kind": "stable_preference",
                        "polarity": "positive",
                        "evidence_text": "Visited GitHub today",
                        "confidence": 0.9,
                    },
                ],
                "assertion_candidates": [
                    {
                        "entity_ref": "user:u1",
                        "entity_type": "user",
                        "trait_family": "mood",
                        "trait_name": "mood",
                        "trait_value": "happy",
                        "inference_depth": "defensive_psychology",
                        "volatility_index": 0.7,
                        "confidence": 0.8,
                        "validation_state": "tentative",
                        "evidence_texts": ["Visited GitHub today"],
                        "supporting_event_ids": ["evt-log-unified-1"],
                    }
                ],
                "diagnostics": {"entity_status": "found"},
            },
            ensure_ascii=False,
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            with caplog.at_level(logging.INFO, logger="magi.memory.l2.pipeline"):
                await store.ingest_event(
                    {
                        "id": "evt-log-unified-1",
                        "type": EventTypes.USER_MESSAGE,
                        "timestamp": time.time(),
                        "source": "calendar",
                        "level": EventLevel.INFO.value,
                        "data": {
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": "Visited GitHub today",
                        },
                    }
                )

                for _ in range(50):
                    stats = store.get_l2_pipeline_stats()
                    if stats["extract_completed"] >= 1:
                        break
                    await asyncio.sleep(0.01)

            messages = [record.getMessage() for record in caplog.records if record.name == "magi.memory.l2.pipeline"]
            assert any("L2 extract completed" in message for message in messages)
            assert any("L2 unified extraction stage started" in message for message in messages)
            assert any("L2 unified candidate validation completed" in message for message in messages)
            assert any("L2 persistence completed" in message for message in messages)
            assert any("timeline.calendar" in message for message in messages)
            assert any("rejected_graph_candidate_count" in message for message in messages)
            assert any("rejected_assertion_candidate_count" in message for message in messages)
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_extraction_normalizes_food_and_persists_dislikes_edge():
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [
                    {
                        "mention_text": "西湖醋鱼",
                        "normalized_surface": "西湖醋鱼",
                        "entity_type": "dish",
                        "canonical_name_hint": "西湖醋鱼",
                        "alias_signals": [],
                        "evidence_text": "但我讨厌吃西湖醋鱼",
                        "confidence": 0.95,
                    }
                ],
                "graph_candidates": [
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "DISLIKES",
                        "object_ref": "food:west-lake-vinegar-fish",
                        "object_type": "dish",
                        "fact_kind": "stable_preference",
                        "polarity": "negative",
                        "evidence_text": "但我讨厌吃西湖醋鱼",
                        "confidence": 0.88,
                    }
                ],
                "assertion_candidates": [],
                "diagnostics": {"entity_status": "found"},
            },
            ensure_ascii=False,
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-unified-food-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "但我讨厌吃西湖醋鱼",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            mentions = await store.l2_entity_catalog.list_mentions() if store.l2_entity_catalog is not None else []
            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []

            assert mentions[0]["entity_type"] == "food"
            assert relationships[0]["predicate"] == "DISLIKES"
            assert relationships[0]["object_type"] == "food"
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_extraction_suppresses_duplicate_leaf_assertions():
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [
                    {
                        "mention_text": "西湖醋鱼",
                        "normalized_surface": "西湖醋鱼",
                        "entity_type": "dish",
                        "canonical_name_hint": "西湖醋鱼",
                        "alias_signals": [],
                        "evidence_text": "但我讨厌吃西湖醋鱼",
                        "confidence": 0.95,
                    }
                ],
                "graph_candidates": [
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "DISLIKES",
                        "object_ref": "food:xi-hu-cu-yu",
                        "object_type": "dish",
                        "fact_kind": "stable_preference",
                        "polarity": "negative",
                        "evidence_text": "但我讨厌吃西湖醋鱼",
                        "confidence": 0.88,
                    }
                ],
                "assertion_candidates": [
                    {
                        "entity_ref": "user:u1",
                        "entity_type": "user",
                        "trait_family": "taste_profile",
                        "trait_name": "taste_preference",
                        "trait_value": "dislikes_food:food:xi-hu-cu-yu",
                        "inference_depth": "defensive_psychology",
                        "volatility_index": 0.4,
                        "confidence": 0.7,
                        "validation_state": "tentative",
                        "evidence_texts": ["但我讨厌吃西湖醋鱼"],
                        "supporting_event_ids": ["evt-unified-food-dup-1"],
                    }
                ],
                "diagnostics": {"entity_status": "found"},
            },
            ensure_ascii=False,
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-unified-food-dup-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "但我讨厌吃西湖醋鱼",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            assert assertions == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_extraction_keeps_higher_order_assertions_alongside_graph_fact():
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [
                    {
                        "mention_text": "西湖醋鱼",
                        "normalized_surface": "西湖醋鱼",
                        "entity_type": "dish",
                        "canonical_name_hint": "西湖醋鱼",
                        "alias_signals": [],
                        "evidence_text": "但我讨厌吃西湖醋鱼",
                        "confidence": 0.95,
                    }
                ],
                "graph_candidates": [
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "DISLIKES",
                        "object_ref": "food:xi-hu-cu-yu",
                        "object_type": "dish",
                        "fact_kind": "stable_preference",
                        "polarity": "negative",
                        "evidence_text": "但我讨厌吃西湖醋鱼",
                        "confidence": 0.88,
                    }
                ],
                "assertion_candidates": [
                    {
                        "entity_ref": "user:u1",
                        "entity_type": "user",
                        "trait_family": "taste_profile",
                        "trait_name": "taste_profile",
                        "trait_value": "avoids_vinegar_heavy_dishes",
                        "inference_depth": "defensive_psychology",
                        "volatility_index": 0.4,
                        "confidence": 0.7,
                        "validation_state": "tentative",
                        "evidence_texts": ["但我讨厌吃西湖醋鱼"],
                        "supporting_event_ids": ["evt-unified-food-high-order-1"],
                    }
                ],
                "diagnostics": {"entity_status": "found"},
            },
            ensure_ascii=False,
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-unified-food-high-order-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "但我讨厌吃西湖醋鱼",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1 and stats["assertions_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            assert [item["predicate"] for item in relationships] == ["DISLIKES"]
            assert [item["trait_name"] for item in assertions] == ["taste_profile"]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_extraction_respects_calendar_profile_restrictions():
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [
                    {
                        "mention_text": "Shanghai",
                        "normalized_surface": "shanghai",
                        "entity_type": "place",
                        "canonical_name_hint": "Shanghai",
                        "alias_signals": [],
                        "evidence_text": "Visited Shanghai today",
                        "confidence": 0.95,
                    }
                ],
                "graph_candidates": [
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "VISITED",
                        "object_ref": "Shanghai",
                        "object_type": "place",
                        "fact_kind": "explicit_fact",
                        "polarity": "positive",
                        "evidence_text": "Visited Shanghai today",
                        "confidence": 0.9,
                    },
                    {
                        "subject_ref": "user:u1",
                        "subject_type": "user",
                        "predicate": "LIKES",
                        "object_ref": "Shanghai",
                        "object_type": "place",
                        "fact_kind": "stable_preference",
                        "polarity": "positive",
                        "evidence_text": "Visited Shanghai today",
                        "confidence": 0.9,
                    },
                ],
                "assertion_candidates": [
                    {
                        "entity_ref": "user:u1",
                        "entity_type": "user",
                        "trait_family": "mood",
                        "trait_name": "mood",
                        "trait_value": "happy",
                        "inference_depth": "defensive_psychology",
                        "volatility_index": 0.7,
                        "confidence": 0.8,
                        "validation_state": "tentative",
                        "evidence_texts": ["Visited Shanghai today"],
                        "supporting_event_ids": ["evt-calendar-1"],
                    }
                ],
                "diagnostics": {"entity_status": "found"},
            },
            ensure_ascii=False,
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-calendar-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "calendar",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "Visited Shanghai today",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            assert [item["predicate"] for item in relationships] == ["VISITED"]
            assert assertions == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_reconcile_worker_promotes_assertions_and_refreshes_snapshots(caplog: pytest.LogCaptureFixture):
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
        )
        await store.initialize()
        try:
            assert store.l1 is not None
            assert store.l2 is not None
            assert store.l2_pipeline is not None

            timestamps = [1710000000.0, 1710090000.0, 1710185000.0]
            with caplog.at_level(logging.INFO, logger="magi.memory.l2.pipeline"), caplog.at_level(
                logging.INFO, logger="magi.memory.l2.store"
            ):
                for index, ts in enumerate(timestamps, start=1):
                    memory_event = normalize_runtime_event(
                        Event(
                            type=EventTypes.USER_MESSAGE,
                            data={"user_id": "u1", "session_id": "s1", "content": f"Stress signal {index}"},
                            source="chat",
                            level=EventLevel.INFO,
                            correlation_id=f"evt-reconcile-{index}",
                            timestamp=ts,
                            metadata={"user_id": "u1"},
                        ),
                        event_id=f"evt-reconcile-{index}",
                    )
                    await store.l1.store(memory_event)

                await store.l2.upsert_assertion_candidate(
                    {
                        "entity_id": "user:u1",
                        "entity_type": "user",
                        "trait_name": "stress_level",
                        "trait_value": "high",
                        "confidence_score": 0.3,
                        "evidence_events": [
                            "evt-reconcile-1",
                            "evt-reconcile-2",
                            "evt-reconcile-3",
                        ],
                        "volatility_index": 0.7,
                        "source_domain": "user_authored",
                        "inference_depth": "defensive_psychology",
                        "validation_state": "tentative",
                        "first_inferred_at": timestamps[0],
                        "last_validated_at": timestamps[-1],
                    }
                )

                await store.l2_pipeline.enqueue_entities(["user:u1"])
                for _ in range(50):
                    stats = store.get_l2_pipeline_stats()
                    if stats["reconcile_completed"] >= 1 and stats["snapshot_completed"] >= 1:
                        break
                    await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            snapshot = await store.l2.get_tom_snapshot(entity_id="user:u1", entity_type="user")
            summaries = await store.l3.list_summaries(limit=10) if store.l3 is not None else []

            assert assertions[0]["validation_state"] == "stable"
            assert assertions[0]["confidence_score"] >= 0.82
            assert snapshot is not None
            assert snapshot["core_traits"]["stress_level"] == "high"
            assert snapshot["current_stress_level"] == 1.0
            assert any(item["summary_category"] == "state_change" for item in summaries)
            assert any(item["summary_category"] == "trend_shift" for item in summaries)
            messages = [record.getMessage() for record in caplog.records]
            assert any("L2 reconcile completed" in message for message in messages)
            assert any("L2 snapshot completed" in message for message in messages)
            assert any("L2 snapshot refreshed" in message for message in messages)
        finally:
            await store.shutdown()
