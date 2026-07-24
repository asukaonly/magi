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
from magi.memory import MemoryStoreTuning
from magi.memory import UnifiedMemoryStore as _RuntimeUnifiedMemoryStore
from magi.memory.event_contracts import normalize_runtime_event
from magi_plugin_sdk import ExtractionProfileSpec


def _calendar_profile_specs() -> list[ExtractionProfileSpec]:
    return [
        ExtractionProfileSpec(
            profile_id="source.calendar",
            source_types=["calendar"],
            allowed_entity_types=["activity", "event", "place", "organization"],
            allowed_predicates=["ATTENDED", "PLANS_TO", "VISITED"],
            allow_graph=True,
            allow_assertion=False,
        )
    ]


def _chrome_history_profile():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry([
        ExtractionProfileSpec(
            profile_id="source.chrome_history",
            source_types=["chrome_history"],
            allowed_entity_types=["product", "software", "technology", "media", "person", "organization", "topic"],
            allowed_predicates=["VISITED", "USES", "INTERESTED_IN", "FOLLOWS", "VIEWED", "WORKS_WITH"],
            structured_allowed_entity_types=[
                "presence",
                "product",
                "software",
                "technology",
                "media",
                "person",
                "group",
                "organization",
                "topic",
            ],
            structured_allowed_predicates=[
                "VISITED",
                "USES",
                "INTERESTED_IN",
                "FOLLOWS",
                "VIEWED",
                "WORKS_WITH",
                "ON_PLATFORM",
                "PRESENCE_OF",
                "LOCATED_IN",
            ],
            allow_graph=True,
            allow_assertion=False,
            extraction_instructions=(
                "Use INTERESTED_IN for repeated topics and VIEWED for content. "
                "Be SELECTIVE, MERGE related pages, and never use virtual_object."
            ),
        )
    ])
    return profiles["source.chrome_history"]


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


def _migrate_memory_shared_schema(db_path: str) -> None:
    from alembic import command

    from magi.db.runner import MIGRATION_TARGETS, _build_config

    memory_shared_target = next(
        target for target in MIGRATION_TARGETS if target.name == "memory_shared"
    )
    command.upgrade(_build_config(memory_shared_target, Path(db_path)), "head")


_MIGRATED_MEMORY_DBS: set[str] = set()


class UnifiedMemoryStore(_RuntimeUnifiedMemoryStore):
    async def initialize(self) -> None:
        if self.l2 is not None:
            db_path = self.l2.db_path
            if db_path not in _MIGRATED_MEMORY_DBS:
                _migrate_memory_shared_schema(db_path)
                _MIGRATED_MEMORY_DBS.add(db_path)
        await super().initialize()


async def _build_pipeline(*, temp_dir: str, batch_flush_interval_seconds: int = 60):
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.store import L2CognitionStore

    memory_db = str(Path(temp_dir) / "memory.db")
    _migrate_memory_shared_schema(memory_db)
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
            event_id=event_id,
        ),
    )


def _phase1_result_with_support(event_id: str):
    from magi.memory.l2.models import L2Phase1FactClaim, L2Phase1Result
    from magi.memory.l2.phase1_models import L2TemporalCue

    return L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:1",
                subject_ref="user:local_user",
                predicate="INTERESTED_IN",
                object_ref="topic:test",
                object_type="topic",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECENT,
                evidence_text="test",
                confidence=0.7,
                supporting_event_ids=[event_id],
            )
        ]
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


def test_microbatch_bucket_key_scopes_source_owner_to_user():
    from magi.memory.l2.models import build_l2_batch_bucket_key

    assert build_l2_batch_bucket_key(
        session_id=None,
        user_id="u1",
        source_type="chrome_history",
        owner_key="Default:github.com",
    ) == "source:chrome_history|owner:Default:github.com|user:u1"


def test_microbatch_bucket_key_separates_sources_for_same_user():
    from magi.memory.l2.models import build_l2_batch_bucket_key

    chrome_key = build_l2_batch_bucket_key(
        session_id=None,
        user_id="u1",
        source_type="chrome_history",
    )
    music_key = build_l2_batch_bucket_key(
        session_id=None,
        user_id="u1",
        source_type="netease_music",
    )

    assert chrome_key == "source:chrome_history|user:u1"
    assert music_key == "source:netease_music|user:u1"
    assert chrome_key != music_key


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
        "trait_family": "",
        "winning_value": "sushi",
        "natural_summary": "",
        "status": "corroborated",
        "confidence": 0.7,
        "evidence_event_ids": ["evt-1", "evt-2"],
        "time_span_hours": 48.0,
        "stability_kind": "stable_trait",
        "recommended_snapshot_field": "preferences",
        "expires_at": None,
        "source_assertion_id": "",
    }


def test_normalized_memory_event_uses_canonical_text_fields():
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "user_id": "local_user",
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

    assert normalized.user_id == "local_user"
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
                        "user_id": "local_user",
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
            assert restored.user_id == "local_user"
            assert restored.turn_id == "turn-1"
            assert restored.content == "hello"
            assert restored.author_type == "user"
            assert restored.content_type == "text"
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_ingest_event_enqueues_l2_work_and_returns_without_sync_l2_counts():
    responses = [
        # Phase 1: extract entity + fact claim
        json.dumps({
            "entities": [],
            "fact_claims": [
                {
                    "claim_id": "claim:1",
                    "subject_ref": "user:self",
                    "predicate": "HAS_METRIC",
                    "object_ref": "stress",
                    "object_type": "health_metric",
                    "fact_kind": "explicit_fact",
                    "temporal_cue": "recent",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "I have been stressed about work.",
                    "confidence": 0.9,
                    "supporting_event_ids": ["evt-queue-1"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "none"},
        }),
        # Phase 2: produce assertion
        json.dumps({
            "claim_assessments": [],
            "assertion_candidates": [
                {
                    "entity_ref": "user:u1",
                    "entity_type": "user",
                    "trait_family": "stress",
                    "trait_name": "stress_level",
                    "trait_value": "high",
                    "natural_summary": "Work has recently felt stressful.",
                    "supporting_claim_ids": ["claim:1"],
                }
            ],
        }),
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
            assert result["l2_job_enqueued"] is True
            assert result["l2_relation_count"] == 0
            assert result["l2_assertion_count"] == 0

            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_enqueued"] >= 1:
                    break
                await asyncio.sleep(0.01)

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
            result = await store.ingest_event(
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

            assert result["l2_job_enqueued"] is False
            stats = store.get_l2_pipeline_stats()
            assert stats["extract_enqueued"] == 0
            assert stats["extract_skipped"] == 0
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
        tuning=MemoryStoreTuning(
            enable_l2_conflict_arbitration=False,
            l2_conflict_arbitration_min_confidence=0.9,
        ),
    )

    assert store.l2_pipeline is not None
    assert store.l2_pipeline._batch_flush_interval_seconds == 90
    assert store.l2_pipeline._enable_conflict_arbitration is False
    assert store.l2_pipeline._conflict_arbitration_min_confidence == 0.9


@pytest.mark.asyncio
async def test_enqueue_event_stages_session_owned_events_before_extraction():
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
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            await pipeline.enqueue_event(_make_memory_event(event_id="evt-stage-3", session_id=None, user_id="u-bucket"))

            assert "source:chat|user:u-bucket" in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 0
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_without_session_or_user_uses_direct_fallback_job():
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
async def test_enqueue_event_uses_explicit_l2_batch_owner_without_session_or_user():
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            event = _make_memory_event(event_id="evt-stage-4b", session_id=None, user_id=None)
            event.metadata_json = {"l2_batch_owner": "chrome_history:Default"}

            await pipeline.enqueue_event(event)

            assert "source:chat|owner:chrome_history:Default" in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 0
            stats = pipeline.get_statistics()
            assert stats["extract_enqueued"] == 0
            assert stats["pending_staged_event_count"] == 1
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_separates_sensor_sources_for_same_user():
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            chrome = _make_memory_event(
                event_id="evt-source-chrome",
                session_id=None,
                user_id="u-source",
            )
            chrome.source = "chrome_history"
            music = _make_memory_event(
                event_id="evt-source-music",
                session_id=None,
                user_id="u-source",
            )
            music.source = "netease_music"

            await pipeline.enqueue_event(chrome)
            await pipeline.enqueue_event(music)

            assert set(pipeline._staging_buckets) == {
                "source:chrome_history|user:u-source",
                "source:netease_music|user:u-source",
            }
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_enqueue_event_uses_owner_batch_size_hint_for_flush():
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            first = _make_memory_event(event_id="evt-stage-hint-1", session_id=None, user_id=None)
            first.metadata_json = {
                "l2_batch_owner": "chrome_history:Default:github.com",
                "l2_batch_max_events": 2,
            }
            second = _make_memory_event(event_id="evt-stage-hint-2", session_id=None, user_id=None)
            second.metadata_json = {
                "l2_batch_owner": "chrome_history:Default:github.com",
                "l2_batch_max_events": 2,
            }

            await pipeline.enqueue_event(first)
            bucket_key = "source:chat|owner:chrome_history:Default:github.com"
            assert bucket_key in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 0

            await pipeline.enqueue_event(second)

            assert bucket_key not in pipeline._staging_buckets
            assert pipeline._extract_queue.qsize() == 1
            job = pipeline._extract_queue.get_nowait()
            assert job is not None
            assert job.flush_reason == "max_events"
            assert job.event_ids == ["evt-stage-hint-1", "evt-stage-hint-2"]
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_flush_ready_buckets_enqueues_interval_elapsed_batch_job():
    from magi.memory.l2.models import L2PendingBatchBucket

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
    from magi.memory.l2.pipeline import DEFAULT_L2_MAX_EVENTS_PER_BATCH

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


def test_reconcile_prompt_rendering_is_deterministic():
    from magi.memory.l2.models import (
        L2ReconcileAssertion,
        L2ReconcileEntity,
        L2ReconcileGraphFact,
        L2SourceEvent,
    )
    from magi.memory.l2.pipeline.prompts import (
        render_entity_reconcile_prompt,
    )

    reconcile_prompt = render_entity_reconcile_prompt(
        entity=L2ReconcileEntity(entity_id="user:u1", entity_type="user"),
        graph_facts=[L2ReconcileGraphFact(predicate="LIKES", object_id="food:sushi")],
        assertions=[L2ReconcileAssertion(trait_name="stress_level", trait_value="high")],
        recent_events=[
            L2SourceEvent(
                event_id="evt-1",
                timestamp=1710000000.0,
                source="chat",
                event_type="UserMessage",
                content="I am stressed.",
            )
        ],
    )

    assert '"entity_id": "user:u1"' in reconcile_prompt
    assert '"trait_name": "stress_level"' in reconcile_prompt


@pytest.mark.asyncio
async def test_low_confidence_resolution_is_returned_as_unresolved():
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        L2EntityCandidate,
        L2EntityResolution,
        L2EntityResolutionMention,
    )

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
        mention=L2EntityResolutionMention(
            mention_text="魔都",
            entity_type="place",
            context_text="我好喜欢魔都",
        ),
        candidate_entities=[
            L2EntityCandidate(
                entity_id="place:shanghai",
                canonical_name="Shanghai",
                entity_type="place",
            )
        ],
    )

    assert isinstance(resolution, L2EntityResolution)
    assert resolution.decision == "unresolved"
    assert resolution.matched_entity_id is None


@pytest.mark.asyncio
async def test_batch_entity_resolution_single_item_delegates():
    """Single-item batch should delegate to non-batch resolve_entity."""
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        L2BatchEntityResolutionItem,
        L2EntityCandidate,
        L2EntityResolutionMention,
    )

    response = json.dumps(
        {
            "resolution": {
                "decision": "match",
                "matched_entity_id": "person:alice",
                "matched_entity_name": "Alice",
                "confidence": 0.95,
                "reason_tags": ["exact_match"],
                "should_merge": False,
                "canonical_name_suggestion": None,
            }
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))
    results = await service.resolve_entities_batch(
        items=[
            L2BatchEntityResolutionItem(
                mention_key="0",
                mention=L2EntityResolutionMention(mention_text="Alice", entity_type="person"),
                candidate_entities=[L2EntityCandidate(entity_id="person:alice", canonical_name="Alice", entity_type="person")],
            ),
        ],
    )
    assert "0" in results
    assert results["0"].decision == "match"
    assert results["0"].matched_entity_id == "person:alice"


@pytest.mark.asyncio
async def test_batch_entity_resolution_multiple_items():
    """Multiple items should be resolved in a single LLM call."""
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        L2BatchEntityResolutionItem,
        L2EntityCandidate,
        L2EntityResolutionMention,
    )

    response = json.dumps(
        {
            "resolutions": [
                {
                    "mention_key": "0",
                    "decision": "match",
                    "matched_entity_id": "person:alice",
                    "matched_entity_name": "Alice",
                    "confidence": 0.95,
                    "reason_tags": ["exact"],
                },
                {
                    "mention_key": "1",
                    "decision": "unresolved",
                    "matched_entity_id": None,
                    "confidence": 0.3,
                    "reason_tags": [],
                },
            ]
        }
    )
    adapter = _FakeAdapter(response)
    service = L2LLMService(_FakeScenarioPool(adapter))
    results = await service.resolve_entities_batch(
        items=[
            L2BatchEntityResolutionItem(
                mention_key="0",
                mention=L2EntityResolutionMention(mention_text="Alice", entity_type="person"),
                candidate_entities=[L2EntityCandidate(entity_id="person:alice", canonical_name="Alice", entity_type="person")],
            ),
            L2BatchEntityResolutionItem(
                mention_key="1",
                mention=L2EntityResolutionMention(mention_text="BobX", entity_type="person"),
                candidate_entities=[L2EntityCandidate(entity_id="person:bob", canonical_name="Bob", entity_type="person")],
            ),
        ],
    )
    assert len(adapter.calls) == 1, "Should use a single LLM call for batch"
    assert results["0"].decision == "match"
    assert results["0"].matched_entity_id == "person:alice"
    assert results["1"].decision == "unresolved"


@pytest.mark.asyncio
async def test_batch_entity_resolution_empty_returns_empty():
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    results = await service.resolve_entities_batch(items=[])
    assert results == {}


@pytest.mark.asyncio
async def test_batch_entity_resolution_fills_missing_keys():
    """If LLM omits some mention_keys, they should be filled as unresolved."""
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        L2BatchEntityResolutionItem,
        L2EntityCandidate,
        L2EntityResolutionMention,
    )

    response = json.dumps({"resolutions": []})  # LLM returns nothing
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))
    results = await service.resolve_entities_batch(
        items=[
            L2BatchEntityResolutionItem(
                mention_key="0",
                mention=L2EntityResolutionMention(mention_text="X", entity_type="person"),
                candidate_entities=[L2EntityCandidate(entity_id="person:x", canonical_name="X", entity_type="person")],
            ),
            L2BatchEntityResolutionItem(
                mention_key="1",
                mention=L2EntityResolutionMention(mention_text="Y", entity_type="person"),
                candidate_entities=[L2EntityCandidate(entity_id="person:y", canonical_name="Y", entity_type="person")],
            ),
        ],
    )
    assert results["0"].decision == "unresolved"
    assert results["1"].decision == "unresolved"


@pytest.mark.asyncio
async def test_invalid_json_from_reconcile_llm_fails_closed():
    from magi.memory.l2.llm_json_client import L2InvalidJsonResponseError
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        L2ReconcileEntity,
    )

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("not-json")))

    with pytest.raises(L2InvalidJsonResponseError):
        await service.reconcile_entity_state(
            entity=L2ReconcileEntity(entity_id="user:u1", entity_type="user"),
            graph_facts=[],
            assertions=[],
            recent_events=[],
        )


@pytest.mark.asyncio
async def test_extract_worker_records_mentions_and_resolved_graph_edge():
    responses = [
        # Phase 1: extract entity
        json.dumps(
            {
                "entities": [
                    {
                        "surface": "魔都",
                        "normalized_name": "上海",
                        "entity_type": "place",
                        "specificity": "concrete",
                        "resolved_id": "place:shanghai",
                        "is_new": False,
                        "alias_signals": ["魔都"],
                        "confidence": 0.96,
                    }
                ],
                "fact_claims": [
                    {
                        "subject_ref": "user:self",
                        "predicate": "LIKES",
                        "object_ref": "魔都",
                        "object_type": "place",
                        "fact_kind": "stable_preference",
                        "temporal_cue": "unspecified",
                        "polarity": "positive",
                        "specificity": "concrete",
                        "evidence_text": "我好喜欢魔都",
                        "confidence": 0.96,
                        "supporting_event_ids": ["evt-graph-1"],
                    }
                ],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "found"},
            }
        ),
        # Phase 2 has no higher-order inference; Phase 1 owns the graph fact.
        json.dumps({"claim_assessments": [], "assertion_candidates": []}),
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
async def test_short_reply_context_error_does_not_fail_or_create_false_mentions():
    phase1_response = json.dumps(
        {
            "entities": [
                {
                    "surface": "DIIV",
                    "normalized_name": "DIIV",
                    "entity_type": "group",
                    "specificity": "concrete",
                    "resolved_id": "group:diiv",
                    "is_new": False,
                    "confidence": 0.95,
                },
                {
                    "surface": "新专",
                    "normalized_name": "新专",
                    "entity_type": "media",
                    "specificity": "underspecified",
                    "resolved_id": None,
                    "is_new": True,
                    "confidence": 0.9,
                },
            ],
            "fact_claims": [
                {
                    "subject_ref": "user:self",
                    "subject_type": "user",
                    "predicate": "LIKES",
                    "object_ref": "DIIV",
                    "object_type": "group",
                    "fact_kind": "stable_preference",
                    "temporal_cue": "recent",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "我最近在听 DIIV 的专辑，好好听",
                    "confidence": 0.95,
                    "supporting_event_ids": ["evt-user-prior"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "found"},
        },
        ensure_ascii=False,
    )
    adapter = _FakeAdapter(phase1_response)

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
            assert store.l2 is not None
            assert store.l2_entity_catalog is not None
            await store.l2_entity_catalog.upsert_entity(
                entity_id="group:diiv",
                canonical_name="DIIV",
                entity_type="group",
            )

            prior_user = _make_memory_event(
                event_id="evt-user-prior",
                session_id="s-short-reply",
                user_id="u1",
                timestamp=100.0,
                content="我最近在听 DIIV 的专辑，好好听",
            )
            prior_assistant = _make_memory_event(
                event_id="evt-assistant-prior",
                session_id="s-short-reply",
                user_id="u1",
                timestamp=101.0,
                content="是《Oshin》还是新专？",
            )
            prior_assistant.author_type = "assistant"
            await store.l1.store(prior_user)
            await store.l1.store(prior_assistant)

            await store.ingest_event(
                {
                    "id": "evt-current-short-reply",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": 102.0,
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-short-reply",
                        "content": "是新专",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 or stats["extract_failed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            stats = store.get_l2_pipeline_stats()
            mentions = await store.l2_entity_catalog.list_mentions(limit=10)
            relationships = await store.l2.get_relationships(subject_id="user:u1")

            assert stats["extract_completed"] == 1
            assert stats["extract_failed"] == 0
            assert len(adapter.calls) == 1
            assert mentions == []
            assert relationships == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_plumbs_place_and_type_hints_into_episode():
    """The extract worker passes place + type hints into episode formation.

    Task 1.2: after extraction the worker builds ``EpisodeCandidateJob``s from
    the touched place/topic hints and the event's ``event_type`` (no longer a
    hardcoded ``"activity"``). This drives the streaming formation so the
    created candidate episode carries the touched place in ``primary_place_ids``
    and an ``episode_type`` matching the ingested event's ``event_type``.
    """
    responses = [
        # Phase 1: extract place entity
        json.dumps(
            {
                "entities": [
                    {
                        "surface": "魔都",
                        "normalized_name": "上海",
                        "entity_type": "place",
                        "specificity": "concrete",
                        "resolved_id": "place:shanghai",
                        "is_new": False,
                        "alias_signals": ["魔都"],
                        "confidence": 0.96,
                    }
                ],
                "fact_claims": [
                    {
                        "subject_ref": "user:self",
                        "predicate": "LIKES",
                        "object_ref": "魔都",
                        "object_type": "place",
                        "fact_kind": "stable_preference",
                        "temporal_cue": "unspecified",
                        "polarity": "positive",
                        "specificity": "concrete",
                        "evidence_text": "我好喜欢魔都",
                        "confidence": 0.96,
                        "supporting_event_ids": ["evt-episode-hint-1"],
                    }
                ],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "found"},
            }
        ),
        # Phase 2 has no higher-order inference; Phase 1 owns the graph fact.
        json.dumps({"claim_assessments": [], "assertion_candidates": []}),
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
                    "id": "evt-episode-hint-1",
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

            assert store.l2 is not None
            # Episode formation runs *after* extract_completed is incremented,
            # so poll on the candidate episode itself rather than the stat to
            # avoid a read-before-write race.
            episodes: list[dict] = []
            for _ in range(100):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    episodes = await store.l2.list_episodes(status="candidate", limit=10)
                    if episodes:
                        break
                await asyncio.sleep(0.01)

            # The extract worker should have formed a candidate episode.
            assert episodes, "extract worker did not form a candidate episode"
            episode = episodes[0]

            # place hint plumbed through: touched place flows into primary_place_ids
            assert "place:shanghai" in (episode.get("primary_place_ids") or [])

            # type hint plumbed through: episode_type follows the event's
            # event_type, MAPPED to a gap-table category, rather than the old
            # hardcoded "activity". A UserMessage maps to "conversation", which
            # is distinct from the "activity" default — so this proves the hint
            # is both plumbed and mapped (not silently falling back).
            from magi.memory.l2.episode_formation import episode_type_for_event

            stored_event = await store.l1.get_memory_event("evt-episode-hint-1")
            assert stored_event is not None
            assert stored_event.event_type == EventTypes.USER_MESSAGE
            expected_type = episode_type_for_event(stored_event.event_type)
            assert expected_type == "conversation"
            assert expected_type != "activity"
            assert episode["episode_type"] == expected_type
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
async def test_write_event_entity_links_uses_mention_scoped_event_ids():
    from magi.memory.l2.models import ResolvedEntityMention

    class _RecordingL1Store:
        def __init__(self) -> None:
            self.mappings: list[tuple[str, str | None, str | None, float | None]] = []

        async def write_event_entities(self, mappings):  # type: ignore[no-untyped-def]
            self.mappings.extend(mappings)

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        l1_store = _RecordingL1Store()
        pipeline._l1_store = l1_store
        try:
            event = _make_memory_event(event_id="evt-batch-last", content="batch")
            await pipeline._write_event_entity_links(
                event=event,
                batch_event_ids=["evt-song-a", "evt-song-b"],
                resolved_mentions=[
                    ResolvedEntityMention(
                        mention_text="归潮",
                        normalized_surface="归潮",
                        entity_type="media",
                        resolved_entity_id="media:1ee3b9131dd8",
                        confidence=0.95,
                        evidence_event_ids=["evt-song-a"],
                    ),
                    ResolvedEntityMention(
                        mention_text="旅人の唄",
                        normalized_surface="旅人の唄",
                        entity_type="media",
                        resolved_entity_id="media:2ab5d1f0285f",
                        confidence=0.95,
                        evidence_event_ids=["evt-song-b"],
                    ),
                ],
            )

            assert l1_store.mappings == [
                ("evt-song-a", "media:1ee3b9131dd8", "media", 0.95),
                ("evt-song-b", "media:2ab5d1f0285f", "media", 0.95),
            ]
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_prepare_unified_graph_candidates_rejects_generic_preference_domain_questions():
    from magi.memory.evidence import PolicyDecision
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.models import L2GraphCandidate

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=60)
        try:
            event = _make_memory_event(event_id="evt-pref-generic", content="我喜欢什么天气")
            prepared, rejected_count = pipeline._prepare_unified_graph_candidates(
                event=event,
                profile=ExtractionProfile(profile_id="chat.user_message"),
                policy=PolicyDecision(
                    allow_entity_extraction=True,
                    allow_graph_write=True,
                    allow_assertion_write=True,
                    allow_snapshot_impact=True,
                    l1_retrieval_scope="fact_authoritative",
                    graph_scope="full",
                    assertion_scope="full",
                    evidence_weight=1.0,
                    count_as_new_evidence=True,
                    require_source_backlink=False,
                ),
                resolved_mentions=[],
                resolved_context_refs=[],
                evidence_event_ids=[event.event_id],
                raw_candidates=[
                    L2GraphCandidate(
                        subject_ref="self",
                        subject_type="user",
                        predicate="LIKES",
                        object_ref="weather_state:weather-state",
                        object_type="weather_state",
                        fact_kind="stable_preference",
                        polarity="positive",
                        confidence=0.88,
                    )
                ],
            )

            assert prepared == []
            assert rejected_count == 1
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_uses_recent_session_context_in_mention_prompt():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "entities": [],
                    "fact_claims": [],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
            json.dumps(
                {
                    "entities": [],
                    "fact_claims": [],
                    "resolved_refs": [],
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
            extraction_profile_provider=_calendar_profile_specs,
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
                if call.get("system_prompt") == PHASE1_EXTRACT_SYSTEM_PROMPT
            ]

            assert len(unified_prompts) == 2
            assert "I like Shanghai." in unified_prompts[1]
            assert "I call Shanghai Modu sometimes." in unified_prompts[1]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_uses_related_cross_session_history_in_unified_prompt():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "entities": [],
                    "fact_claims": [],
                    "resolved_refs": [],
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
                if call.get("system_prompt") == PHASE1_EXTRACT_SYSTEM_PROMPT
            ]

            assert len(unified_prompts) == 1
            assert "I still like Modu." in unified_prompts[0]
            assert "I call Shanghai Modu sometimes." in unified_prompts[0]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_orders_history_contexts_chronologically_in_prompt():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "entities": [],
                    "fact_claims": [],
                    "resolved_refs": [],
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
                if call.get("system_prompt") == PHASE1_EXTRACT_SYSTEM_PROMPT
            ]

            assert len(unified_prompts) == 1
            prompt = unified_prompts[0]
            assert prompt.index("I called Shanghai Modu years ago.") < prompt.index("I still call Shanghai Modu now.")
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_phase2_uses_phase1_entities_to_recall_l1_entity_history():
    from magi.memory.l2.pipeline.prompts import PHASE2_INTEGRATE_SYSTEM_PROMPT

    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "entities": [
                        {
                            "surface": "DIIV",
                            "normalized_name": "DIIV",
                            "entity_type": "group",
                            "specificity": "concrete",
                            "resolved_id": "group:diiv",
                            "is_new": False,
                        }
                    ],
                    "fact_claims": [
                        {
                            "subject_ref": "user:self",
                            "predicate": "ATTENDED",
                            "object_ref": "DIIV",
                            "object_type": "group",
                            "fact_kind": "interaction_evidence",
                            "temporal_cue": "one_off",
                            "specificity": "concrete",
                            "confidence": 0.9,
                            "evidence_text": "DIIV was great last night.",
                            "supporting_event_ids": ["evt-current-band"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "found"},
                }
            ),
            json.dumps({"claim_assessments": [], "assertion_candidates": []}),
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
            await store.l2_entity_catalog.upsert_entity(
                canonical_name="DIIV",
                entity_type="group",
                entity_id="group:diiv",
            )
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-linked-history",
                    session_id="s-old",
                    user_id="u1",
                    timestamp=100.0,
                    content="The concert replay made me revisit that night.",
                )
            )
            await store.l1.write_event_entities(
                [("evt-linked-history", "group:diiv", "group", 0.95)]
            )

            await store.ingest_event(
                {
                    "id": "evt-current-band",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": 300.0,
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-new",
                        "content": "DIIV was great last night.",
                    },
                }
            )
            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            phase2_prompts = [
                str(call["prompt"])
                for call in adapter.calls
                if call.get("system_prompt") == PHASE2_INTEGRATE_SYSTEM_PROMPT
            ]

            assert len(phase2_prompts) == 1
            assert "The concert replay made me revisit that night." in phase2_prompts[0]
            assert "History Matches" in phase2_prompts[0]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_sensor_events_without_session_do_not_use_user_recent_context():
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
            assert store.l2_pipeline is not None
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-chat-context",
                    session_id="s-chat",
                    user_id="u1",
                    timestamp=100.0,
                    content="This chat sentence must not leak into sensor context.",
                )
            )
            sensor_event = normalize_runtime_event(
                Event(
                    type="SENSOR_EVENT",
                    data={
                        "user_id": "u1",
                        "session_id": None,
                        "content": "Visited a page about DIIV",
                        "author_type": "sensor",
                        "content_type": "text",
                    },
                    source="chrome_history",
                    level=EventLevel.INFO,
                    correlation_id="corr-sensor-no-session",
                    timestamp=300.0,
                    event_id="evt-sensor-no-session",
                )
            )

            messages = await store.l2_pipeline._load_context_messages(sensor_event)

            assert messages == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_persists_llm_tom_assertions():
    responses = [
        # Phase 1: extract a fact claim about stress
        json.dumps(
            {
                "entities": [],
                "fact_claims": [
                    {
                        "subject_ref": "user:self",
                        "predicate": "HAS_METRIC",
                        "object_ref": "stress",
                        "object_type": "health_metric",
                        "fact_kind": "explicit_fact",
                        "temporal_cue": "recent",
                        "polarity": "positive",
                        "specificity": "concrete",
                        "evidence_text": "I am stressed about work today.",
                        "confidence": 0.94,
                        "supporting_event_ids": ["evt-stress-1"],
                    }
                ],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "none"},
            }
        ),
        # Phase 2: produce assertion
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [
                    {
                        "entity_ref": "user:u1",
                        "entity_type": "user",
                        "trait_family": "stress",
                        "trait_name": "stress_level",
                        "trait_value": "high",
                        "natural_summary": "Work has recently felt stressful.",
                        "supporting_claim_ids": ["claim:1"],
                    }
                ],
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
            # Assertion may already have been reconciled (temporary trait → corroborated)
            assert assertions[0]["validation_state"] in ("tentative", "corroborated")
            assert assertions[0]["confidence_score"] in (0.3, 0.5)
            assert store.get_l2_pipeline_stats()["reconcile_enqueued"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_does_not_let_phase2_directly_mutate_existing_assertions():
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
                        event_id=event_id),
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
                # Phase 1: extract a fact claim so Phase 2 runs
                json.dumps(
                    {
                        "entities": [],
                        "fact_claims": [
                            {
                                "subject_ref": "user:self",
                                "predicate": "HAS_METRIC",
                                "object_ref": "calm",
                                "object_type": "health_metric",
                                "fact_kind": "explicit_fact",
                                "temporal_cue": "recent",
                                "polarity": "positive",
                                "specificity": "concrete",
                                "evidence_text": "I feel calm and relaxed now.",
                                "confidence": 0.88,
                                "supporting_event_ids": ["evt-calm-1"],
                            }
                        ],
                        "resolved_refs": [],
                        "diagnostics": {"entity_status": "none"},
                    }
                ),
                # Phase 2 may identify a conflict, but the host owns the action.
                json.dumps(
                    {
                        "claim_assessments": [
                            {
                                "claim_id": "claim:1",
                                "relationship": "evolves",
                                "related_record_id": existing_assertion_id,
                            }
                        ],
                        "assertion_candidates": [],
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
            assert assertions[0]["validation_state"] == "stable"
            assert assertions[0]["confidence_score"] == pytest.approx(0.84)
            assert not any(item["summary_category"] == "conflict_resolution" for item in summaries)
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
            assert store.l2_pipeline is not None
            store.l2_pipeline._conflict_arbitration_min_confidence = 0.2
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
                # Phase 1: extract entity mention + fact claim
                json.dumps(
                    {
                        "entities": [
                            {
                                "surface": "Shanghai",
                                "normalized_name": "Shanghai",
                                "entity_type": "place",
                                "specificity": "concrete",
                                "resolved_id": "place:shanghai",
                                "is_new": False,
                                "alias_signals": [],
                                "confidence": 0.94,
                            }
                        ],
                        "fact_claims": [
                            {
                                "subject_ref": "user:u1",
                                "predicate": "DISLIKES",
                                "object_ref": "place:shanghai",
                                "object_type": "place",
                                "fact_kind": "stable_preference",
                                "temporal_cue": "recent",
                                "polarity": "negative",
                                "specificity": "concrete",
                                "evidence_text": "I hate Shanghai now.",
                                "confidence": 0.94,
                                "supporting_event_ids": ["evt-hate-1"],
                            }
                        ],
                        "resolved_refs": [],
                        "diagnostics": {"entity_status": "found"},
                    }
                ),
                # Phase 2 only links the grounded claim to the existing record.
                json.dumps(
                    {
                        "claim_assessments": [
                            {
                                "claim_id": "claim:1",
                                "relationship": "contradicts",
                                "related_record_id": existing_triple_id,
                            }
                        ],
                        "assertion_candidates": [],
                    }
                ),
                # Conflict arbitration: keep_existing
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
            assert store.l2_pipeline is not None
            store.l2_pipeline._conflict_arbitration_min_confidence = 0.2
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
                # Phase 1: extract entity + fact claim
                json.dumps(
                    {
                        "entities": [
                            {
                                "surface": "Shanghai",
                                "normalized_name": "Shanghai",
                                "entity_type": "place",
                                "specificity": "concrete",
                                "resolved_id": "place:shanghai",
                                "is_new": False,
                                "alias_signals": [],
                                "confidence": 0.94,
                            }
                        ],
                        "fact_claims": [
                            {
                                "subject_ref": "user:u1",
                                "predicate": "DISLIKES",
                                "object_ref": "place:shanghai",
                                "object_type": "place",
                                "fact_kind": "stable_preference",
                                "temporal_cue": "recent",
                                "polarity": "negative",
                                "specificity": "concrete",
                                "evidence_text": "I hate Shanghai these days.",
                                "confidence": 0.94,
                                "supporting_event_ids": ["evt-evolution-1"],
                            }
                        ],
                        "resolved_refs": [],
                        "diagnostics": {"entity_status": "found"},
                    }
                ),
                # Phase 2 only links the grounded claim to the existing record.
                json.dumps(
                    {
                        "claim_assessments": [
                            {
                                "claim_id": "claim:1",
                                "relationship": "evolves",
                                "related_record_id": previous_edge["triple_id"],
                            }
                        ],
                        "assertion_candidates": [],
                    }
                ),
                # Conflict arbitration: mark_evolution
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
            assert store.l2_pipeline is not None
            store.l2_pipeline._conflict_arbitration_min_confidence = 0.2
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
            assert seeded_snapshot["preferences"]["place:shanghai"]["value"] == "like"

            adapter._responses = [
                # Phase 1: extract entity + fact claim
                json.dumps(
                    {
                        "entities": [
                            {
                                "surface": "Shanghai",
                                "normalized_name": "Shanghai",
                                "entity_type": "place",
                                "specificity": "concrete",
                                "resolved_id": "place:shanghai",
                                "is_new": False,
                                "alias_signals": [],
                                "confidence": 0.94,
                            }
                        ],
                        "fact_claims": [
                            {
                                "subject_ref": "user:u1",
                                "predicate": "DISLIKES",
                                "object_ref": "place:shanghai",
                                "object_type": "place",
                                "fact_kind": "stable_preference",
                                "temporal_cue": "recent",
                                "polarity": "negative",
                                "specificity": "concrete",
                                "evidence_text": "I hate Shanghai these days.",
                                "confidence": 0.94,
                                "supporting_event_ids": ["evt-evolution-2"],
                            }
                        ],
                        "resolved_refs": [],
                        "diagnostics": {"entity_status": "found"},
                    }
                ),
                # Phase 2 only links the grounded claim to the existing record.
                json.dumps(
                    {
                        "claim_assessments": [
                            {
                                "claim_id": "claim:1",
                                "relationship": "evolves",
                                "related_record_id": previous_edge["triple_id"],
                            }
                        ],
                        "assertion_candidates": [],
                    }
                ),
                # Conflict arbitration: mark_evolution
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
            assert snapshot["preferences"]["place:shanghai"]["value"] == "dislike"
            assert snapshot["preferences_history"][0]["field"] == "place:shanghai"
            assert snapshot["preferences_history"][0]["from"]["value"] == "like"
            assert snapshot["preferences_history"][0]["to"]["value"] == "dislike"
            assert stats["snapshot_completed"] >= 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_chat_response_action_runtime_event_does_not_enter_l2_pipeline():
    adapter = _FakeAdapter(
        json.dumps({"entities": [], "fact_claims": [], "resolved_refs": []})
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
                Event(
                    type="ActionExecuted",
                    data={
                        "agent_id": "chat:local_user",
                        "event_type": "UserMessage",
                        "action_type": "ChatResponseAction",
                        "content": "懂你，这种天气确实烦。",
                        "user_id": "local_user",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "success": True,
                    },
                    source="runtime_event_emitter",
                    level=EventLevel.INFO,
                    correlation_id="evt-runtime-chat-1",
                    timestamp=time.time(),
                )
            )

            stats = store.get_l2_pipeline_stats()
            assert stats["extract_enqueued"] == 0
            assert stats["extract_completed"] == 0
            assert stats["extract_skipped"] == 0
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
            result = await store.ingest_event(
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

            stats = store.get_l2_pipeline_stats()
            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            # The evidence-policy gate now skips assistant_freeform at the
            # L2 projection layer, BEFORE the pipeline: no job is enqueued and
            # the extraction stats never tick.
            assert result["l2_job_enqueued"] is False
            assert stats["extract_completed"] == 0
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
            result = await store.ingest_event(
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

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []
            stats = store.get_l2_pipeline_stats()

            # assistant_tool_grounded is also blocked by the evidence-policy
            # gate at the projection layer — skipped before the pipeline.
            assert result["l2_job_enqueued"] is False
            assert stats["extract_completed"] == 0
            assert relationships == []
            assert assertions == []
            assert adapter.calls == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_assistant_quote_does_not_add_new_evidence_weight():
    adapter = _FakeAdapter(
        [
            # Phase 1: extract fact claim about stress
            json.dumps(
                {
                    "entities": [],
                    "fact_claims": [
                        {
                            "subject_ref": "user:self",
                            "predicate": "HAS_METRIC",
                            "object_ref": "stress",
                            "object_type": "health_metric",
                            "fact_kind": "explicit_fact",
                            "temporal_cue": "recent",
                            "polarity": "positive",
                            "specificity": "concrete",
                            "evidence_text": "I am stressed about work today.",
                            "confidence": 0.88,
                            "supporting_event_ids": ["evt-user-stress-1"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
            # Phase 2: produce assertion
            json.dumps(
                {
                    "claim_assessments": [],
                    "assertion_candidates": [
                        {
                            "entity_ref": "user:u1",
                            "entity_type": "user",
                            "trait_family": "stress",
                            "trait_name": "stress_level",
                            "trait_value": "high",
                            "supporting_claim_ids": ["claim:1"],
                        }
                    ],
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
                if stats["extract_completed"] >= 1 and stats["assertions_written"] >= 1 and stats["reconcile_completed"] >= 1 and stats["snapshot_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            before_assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []
            before_call_count = len(adapter.calls)

            quote_result = await store.ingest_event(
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

            after_assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            # The assistant quote never enters the pipeline (policy gate), so
            # the existing assertion's evidence/confidence stay untouched.
            assert quote_result["l2_job_enqueued"] is False
            assert len(before_assertions) == 1
            assert len(after_assertions) == 1
            assert after_assertions[0]["assertion_id"] == before_assertions[0]["assertion_id"]
            assert after_assertions[0]["evidence_events"] == ["evt-user-stress-1"]
            assert after_assertions[0]["confidence_score"] == before_assertions[0]["confidence_score"]
            assert len(adapter.calls) == before_call_count
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
            freeform_result = await store.ingest_event(
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
                if stats["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            stats = store.get_l2_pipeline_stats()

            # Eligible user events still flow through extraction and are
            # tracked by evidence class; assistant_freeform is now blocked at
            # the projection-layer policy gate and never reaches the pipeline
            # (so its skip is observable on the ingest result, not in stats).
            assert stats["extract_by_evidence_class"]["user_self_report"] >= 1
            assert freeform_result["l2_job_enqueued"] is False
            assert "assistant_freeform" not in stats["extract_by_evidence_class"]
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
                # Eligible user event: flows into the pipeline and logs.
                await store.ingest_event(
                    {
                        "id": "evt-user-log-1",
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
                # Policy-blocked assistant event: never reaches the pipeline,
                # so the skip decision is observable on the ingest result.
                skip_result = await store.ingest_event(
                    {
                        "id": "evt-ai-freeform-log-1",
                        "type": EventTypes.AI_RESPONSE,
                        "timestamp": time.time() + 1,
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
            assert skip_result["l2_job_enqueued"] is False
            # The blocked event must never show up in pipeline activity.
            assert not any("evt-ai-freeform-log-1" in message for message in messages)
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_pipeline_logs_profile_and_rejection_counts_for_unified_extraction(
    caplog: pytest.LogCaptureFixture,
):
    adapter = _FakeAdapter(
        [
            # Phase 1: extract entity + fact claims
            json.dumps(
                {
                    "entities": [
                        {
                            "surface": "GitHub",
                            "normalized_name": "GitHub",
                            "entity_type": "product",
                            "specificity": "concrete",
                            "resolved_id": None,
                            "is_new": True,
                            "alias_signals": [],
                            "confidence": 0.95,
                        }
                    ],
                    "fact_claims": [
                        {
                            "subject_ref": "user:u1",
                            "predicate": "VISITED",
                            "object_ref": "GitHub",
                            "object_type": "product",
                            "fact_kind": "explicit_fact",
                            "temporal_cue": "one_off",
                            "polarity": "positive",
                            "specificity": "concrete",
                            "evidence_text": "Visited GitHub today",
                            "confidence": 0.9,
                            "supporting_event_ids": ["evt-log-unified-1"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "found"},
                },
                ensure_ascii=False,
            ),
            # This profile disables higher-order assertions, so Phase 2 is skipped.
            json.dumps(
                {
                    "claim_assessments": [],
                    "assertion_candidates": [],
                },
                ensure_ascii=False,
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
            # Calendar profile is plugin-contributed now; inject the spec so
            # the profile id appears in extraction logs (see calendar test).
            extraction_profile_provider=lambda: [
                {
                    "profile_id": "source.calendar",
                    "source_types": ["calendar"],
                    "allowed_predicates": ["VISITED"],
                    "allow_assertion": False,
                }
            ],
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
            assert any("L2 Phase 1 extraction started" in message for message in messages)
            # With allow_assertion=False Phase 1 persists grounded facts directly.
            assert any(
                "L2 Phase 1 persisted without Phase 2 inference" in message
                for message in messages
            )
            assert any("source.calendar" in message for message in messages)
            assert any("rejected_graph_candidate_count" in message for message in messages)
            assert any("rejected_assertion_candidate_count" in message for message in messages)
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_extraction_normalizes_food_and_persists_dislikes_edge():
    adapter = _FakeAdapter(
        [
            # Phase 1: extract entity (dish → normalized to food) + fact claim
            json.dumps(
                {
                    "entities": [
                        {
                            "surface": "西湖醋鱼",
                            "normalized_name": "西湖醋鱼",
                            "entity_type": "dish",
                            "specificity": "concrete",
                            "resolved_id": None,
                            "is_new": True,
                            "alias_signals": [],
                            "confidence": 0.95,
                        }
                    ],
                    "fact_claims": [
                        {
                            "subject_ref": "user:u1",
                            "predicate": "DISLIKES",
                            "object_ref": "西湖醋鱼",
                            "object_type": "dish",
                            "fact_kind": "stable_preference",
                            "temporal_cue": "unspecified",
                            "polarity": "negative",
                            "specificity": "concrete",
                            "evidence_text": "但我讨厌吃西湖醋鱼",
                            "confidence": 0.88,
                            "supporting_event_ids": ["evt-unified-food-1"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "found"},
                },
                ensure_ascii=False,
            ),
            # Phase 2 has no higher-order inference; Phase 1 owns the graph fact.
            json.dumps(
                {
                    "claim_assessments": [],
                    "assertion_candidates": [],
                },
                ensure_ascii=False,
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
                        "trait_family": "preference_profile",
                        "trait_name": "preference.food",
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
        [
            # Phase 1: extract entity + fact claim
            json.dumps(
                {
                    "entities": [
                        {
                            "surface": "西湖醋鱼",
                            "normalized_name": "西湖醋鱼",
                            "entity_type": "dish",
                            "specificity": "concrete",
                            "resolved_id": None,
                            "is_new": True,
                            "alias_signals": [],
                            "confidence": 0.95,
                        }
                    ],
                    "fact_claims": [
                        {
                            "subject_ref": "user:u1",
                            "predicate": "DISLIKES",
                            "object_ref": "西湖醋鱼",
                            "object_type": "dish",
                            "fact_kind": "stable_preference",
                            "temporal_cue": "unspecified",
                            "polarity": "negative",
                            "specificity": "concrete",
                            "evidence_text": "但我讨厌吃西湖醋鱼",
                            "confidence": 0.88,
                            "supporting_event_ids": ["evt-unified-food-high-order-1"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "found"},
                },
                ensure_ascii=False,
            ),
            # Phase 2: higher-order assertion grounded in the Phase 1 claim
            json.dumps(
                {
                    "claim_assessments": [],
                    "assertion_candidates": [
                        {
                            "entity_ref": "user:u1",
                            "entity_type": "user",
                            "trait_family": "preference_profile",
                            "trait_name": "preference.food.pattern",
                            "trait_value": "avoids_vinegar_heavy_dishes",
                            "supporting_claim_ids": ["claim:1"],
                        }
                    ],
                },
                ensure_ascii=False,
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
            assert [item["trait_name"] for item in assertions] == ["preference.food.pattern"]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_extraction_respects_calendar_profile_restrictions():
    adapter = _FakeAdapter(
        [
            # Phase 1: extract entity + fact claims
            json.dumps(
                {
                    "entities": [
                        {
                            "surface": "Shanghai",
                            "normalized_name": "Shanghai",
                            "entity_type": "place",
                            "specificity": "concrete",
                            "resolved_id": None,
                            "is_new": True,
                            "alias_signals": [],
                            "confidence": 0.95,
                        }
                    ],
                    "fact_claims": [
                        {
                            "subject_ref": "user:u1",
                            "predicate": "VISITED",
                            "object_ref": "Shanghai",
                            "object_type": "place",
                            "fact_kind": "explicit_fact",
                            "temporal_cue": "one_off",
                            "polarity": "positive",
                            "specificity": "concrete",
                            "evidence_text": "Visited Shanghai today",
                            "confidence": 0.9,
                            "supporting_event_ids": ["evt-calendar-1"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "found"},
                },
                ensure_ascii=False,
            ),
            # The calendar profile disables higher-order assertions, so Phase 2 is skipped.
            json.dumps(
                {
                    "claim_assessments": [],
                    "assertion_candidates": [],
                },
                ensure_ascii=False,
            ),
        ]
    )

    # The built-in calendar profile moved out of the host (profiles are now
    # plugin-contributed via extraction_profile_provider); inject an
    # equivalent spec so the restriction mechanism itself is under test.
    calendar_profile_spec = {
        "profile_id": "source.calendar",
        "source_types": ["calendar"],
        "allowed_predicates": ["VISITED"],
        "allow_assertion": False,
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
            extraction_profile_provider=lambda: [calendar_profile_spec],
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

            now = time.time()
            timestamps = [now - 49 * 3600, now - 25 * 3600, now]
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
                        event_id=f"evt-reconcile-{index}"),
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
                # stress_level is a temporary-state trait and the trend-shift
                # gate deliberately excludes temporary/volatile kinds — seed a
                # NON-temporary trait over the same long window so reconcile
                # yields a stable_trait outcome eligible for trend_shift.
                await store.l2.upsert_assertion_candidate(
                    {
                        "entity_id": "user:u1",
                        "entity_type": "user",
                        "trait_family": "preference_profile",
                        "trait_name": "communication_style",
                        "trait_value": "concise",
                        "confidence_score": 0.6,
                        "evidence_events": [
                            "evt-reconcile-1",
                            "evt-reconcile-2",
                            "evt-reconcile-3",
                        ],
                        "volatility_index": 0.2,
                        "source_domain": "user_authored",
                        "inference_depth": "direct",
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


# ── Session-end review tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_session_flushes_bucket_and_returns_empty_when_no_entities_accumulated():
    """flush_session should flush the session bucket even when no entities have
    been accumulated yet (e.g. first turn with only staged events)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=9999)

        event = _make_memory_event(event_id="evt-1", session_id="s-flush", content="hello")
        await pipeline.enqueue_event(event)

        # Bucket should exist before flush
        assert "session:s-flush" in pipeline._staging_buckets

        result = await pipeline.flush_session("s-flush")

        # Bucket should be drained
        assert "session:s-flush" not in pipeline._staging_buckets
        # No entities accumulated yet → empty list
        assert result == []
        # An extract job should have been enqueued
        assert pipeline._stats.extract_enqueued >= 1
        stats = pipeline.get_statistics()
        assert stats["batch_flush_by_reason"].get("session_end", 0) >= 1


@pytest.mark.asyncio
async def test_flush_session_returns_accumulated_entities():
    """After extraction populates touched entities, flush_session should return
    and enqueue them for reconciliation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=9999)

        # Simulate entities accumulated during prior extractions
        pipeline._session_touched_entities["s-review"] = {"user:u1", "person:alice"}

        result = await pipeline.flush_session("s-review")

        assert sorted(result) == ["person:alice", "user:u1"]
        # Session tracking should be cleared
        assert "s-review" not in pipeline._session_touched_entities
        # Entities should be enqueued for reconcile + snapshot
        assert pipeline._stats.reconcile_enqueued >= 1
        assert pipeline._stats.snapshot_enqueued >= 1


@pytest.mark.asyncio
async def test_flush_all_pending_batches_drains_all_staging_buckets():
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir, batch_flush_interval_seconds=9999)

        await pipeline.enqueue_event(_make_memory_event(event_id="evt-1", session_id="s-alpha", content="alpha"))
        await pipeline.enqueue_event(_make_memory_event(event_id="evt-2", session_id="s-beta", content="beta"))

        assert "session:s-alpha" in pipeline._staging_buckets
        assert "session:s-beta" in pipeline._staging_buckets

        flushed = await pipeline.flush_all_pending_batches()

        assert flushed == 2
        assert pipeline._staging_buckets == {}
        assert pipeline._stats.extract_enqueued >= 2
        stats = pipeline.get_statistics()
        assert stats["batch_flush_by_reason"].get("manual_flush", 0) == 2


@pytest.mark.asyncio
async def test_flush_session_noop_for_unknown_session():
    """flush_session for a session with no bucket and no entities is a no-op."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        result = await pipeline.flush_session("nonexistent")

        assert result == []
        assert pipeline._stats.reconcile_enqueued == 0


@pytest.mark.asyncio
async def test_accumulate_session_entities_aggregates_across_batches():
    """_accumulate_session_entities should merge entity sets across calls."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        pipeline._accumulate_session_entities("s1", ["user:u1", "person:alice"])
        pipeline._accumulate_session_entities("s1", ["person:alice", "place:tokyo"])

        assert pipeline._session_touched_entities["s1"] == {"user:u1", "person:alice", "place:tokyo"}


@pytest.mark.asyncio
async def test_accumulate_session_entities_ignores_empty_inputs():
    """_accumulate_session_entities should skip None session_id or empty lists."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        pipeline._accumulate_session_entities(None, ["user:u1"])
        pipeline._accumulate_session_entities("s1", [])

        assert pipeline._session_touched_entities == {}


@pytest.mark.asyncio
async def test_unified_memory_on_session_end_delegates_to_pipeline():
    """UnifiedMemoryStore.on_session_end should call l2_pipeline.flush_session."""
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            enable_l2=True,
        )
        await store.initialize()
        try:
            # Inject pre-accumulated entities
            store.l2_pipeline._session_touched_entities["s-end"] = {"user:u1"}

            result = await store.on_session_end("s-end")

            assert result == ["user:u1"]
            assert "s-end" not in store.l2_pipeline._session_touched_entities
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_unified_memory_on_session_end_noop_without_l2():
    """on_session_end should return [] when L2 pipeline is disabled."""
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            enable_l2=False,
        )
        await store.initialize()
        try:
            result = await store.on_session_end("s-end")
            assert result == []
        finally:
            await store.shutdown()


# ── Structured Entity Hints & Alias Validation ──


@pytest.mark.asyncio
async def test_inject_structured_entity_hints_adds_context_entries():
    """Sensor-provided entity hints should be injected into existing_entities as context."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        event = _make_memory_event(event_id="evt-hints-1", content="testing hints")
        event.metadata_json = {
            "structured_entity_hints": [
                {
                    "mention_text": "GitHub",
                    "entity_type": "software",
                    "canonical_name_hint": "GitHub",
                },
                {
                    "mention_text": "openai-python",
                    "entity_type": "media",
                    "canonical_name_hint": "openai-python",
                },
            ]
        }

        existing: list[dict] = []
        pipeline._inject_structured_entity_hints(event, existing)

        assert len(existing) == 2
        types = {e["entity_type"] for e in existing}
        assert "software" in types
        assert "media" in types
        assert all(e.get("hint_only") is True for e in existing)

        # Verify catalog is NOT written to
        entities = await pipeline._entity_catalog.list_entities(limit=10)
        assert len(entities) == 0


@pytest.mark.asyncio
async def test_inject_structured_entity_hints_skips_duplicates():
    """Already-present entities should not be duplicated in existing_entities."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        event = _make_memory_event(event_id="evt-hints-2", content="testing")
        event.metadata_json = {
            "structured_entity_hints": [
                {
                    "mention_text": "GitHub",
                    "entity_type": "software",
                    "canonical_name_hint": "GitHub",
                    "resolved_entity_id": "software:abc123",
                },
            ]
        }

        existing = [{"entity_id": "software:abc123", "canonical_name": "GitHub", "entity_type": "software"}]
        pipeline._inject_structured_entity_hints(event, existing)

        assert len(existing) == 1


@pytest.mark.asyncio
async def test_upsert_structured_graph_hints_uses_normalized_entity_id_for_aliases():
    """Aliases from graph hints must point at the catalog-normalized entity id."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        event = _make_memory_event(event_id="evt-graph-site-alias", content="Chrome 浏览 Google")
        event.metadata_json = {
            "structured_graph_hints": [
                {
                    "subject_ref": "user:self",
                    "subject_type": "user",
                    "predicate": "VIEWED",
                    "object_ref": "site:google.com",
                    "object_type": "software",
                    "fact_kind": "interaction_evidence",
                    "origin_mode": "source_structured",
                    "confidence": 0.78,
                    "attributes": {"domain": "google.com"},
                }
            ]
        }

        await pipeline._upsert_structured_hint_entities(event)
        resolved = await pipeline._entity_catalog.resolve_alias("google.com", entity_type="software")

        assert resolved["decision"] == "match"
        assert resolved["entity_id"] == "software:google.com"


@pytest.mark.asyncio
async def test_prepare_direct_graph_writes_processes_every_batch_event():
    from magi.memory.evidence import classify_event_evidence, resolve_l2_policy
    from magi.memory.event_contracts import MemoryDomain

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)
        try:
            events = []
            for event_id, object_id in (
                ("evt-structured-batch-1", "software:github"),
                ("evt-structured-batch-2", "software:docker"),
            ):
                event = _make_memory_event(
                    event_id=event_id,
                    session_id=None,
                    user_id="u-structured",
                )
                event.source = "chrome_history"
                event.author_type = "external"
                event.memory_domain = MemoryDomain.EXTERNAL_ACTIVITY
                event.metadata_json = {
                    "structured_graph_hints": [
                        {
                            "subject_ref": "user:self",
                            "subject_type": "user",
                            "predicate": "USES",
                            "object_ref": object_id,
                            "object_type": "software",
                            "fact_kind": "interaction_evidence",
                            "origin_mode": "source_structured",
                            "confidence": 0.8,
                        }
                    ]
                }
                classification = classify_event_evidence(event)
                events.append((event, classification, resolve_l2_policy(classification)))

            await pipeline._load_batch_existing_entities(events)
            candidates, count = await pipeline._prepare_direct_graph_writes(
                eligible_events=events,
                catalog_name_index=await pipeline._build_catalog_name_index(),
            )

            assert count == 2
            assert {candidate["object_id"] for candidate in candidates} == {
                "software:github",
                "software:docker",
            }
            assert {
                tuple(candidate["evidence_event_ids"])
                for candidate in candidates
            } == {
                ("evt-structured-batch-1",),
                ("evt-structured-batch-2",),
            }
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_structured_graph_ref_reuses_entity_hint_for_punctuated_hardware_id():
    """Graph refs should reuse same-event entity hints instead of creating ID fragments."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        event = _make_memory_event(
            event_id="evt-ipad-graph-ref",
            content="Apple iPad Pro (11-inch) (3rd generation) photo",
        )
        event.metadata_json = {
            "structured_entity_hints": [
                {
                    "mention_text": "Apple iPad Pro (11-inch) (3rd generation)",
                    "entity_type": "device",
                    "canonical_name_hint": "apple-ipad-pro-(11-inch)-(3rd-generation)",
                }
            ],
            "structured_graph_hints": [
                {
                    "subject_ref": "user:self",
                    "subject_type": "user",
                    "predicate": "OWNS",
                    "object_ref": "hardware:apple-ipad-pro-(11-inch)-(3rd-generation)",
                    "object_type": "hardware",
                    "fact_kind": "interaction_evidence",
                    "origin_mode": "source_structured",
                    "confidence": 0.9,
                }
            ],
        }

        await pipeline._upsert_structured_hint_entities(event)

        entities = await pipeline._entity_catalog.list_entities(limit=10)
        ipad_entities = [
            entity
            for entity in entities
            if "apple-ipad-pro" in str(entity.get("entity_id") or "")
        ]
        assert [entity["entity_id"] for entity in ipad_entities] == [
            "hardware:apple-ipad-pro-11-inch-3rd-generation"
        ]

        catalog_name_index = await pipeline._build_catalog_name_index()
        object_id = pipeline._resolve_phase2_object_id(
            raw_object_ref="hardware:apple-ipad-pro-(11-inch)-(3rd-generation)",
            object_type="hardware",
            resolved_mentions=[],
            catalog_name_index=catalog_name_index,
        )
        assert object_id == "hardware:apple-ipad-pro-11-inch-3rd-generation"


@pytest.mark.asyncio
async def test_phase1_resolved_id_reuses_existing_same_name_entity():
    """Phase 1 resolved IDs should not create a second entity for the same canonical name."""
    from magi.memory.l2.models import L2Phase1Entity, L2Phase1Result

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)
        canonical_id = "hardware:apple-ipad-pro-11-inch-3rd-generation"
        canonical_name = "apple-ipad-pro-(11-inch)-(3rd-generation)"
        await pipeline._entity_catalog.upsert_entity(
            entity_id=canonical_id,
            canonical_name=canonical_name,
            entity_type="hardware",
        )

        event = _make_memory_event(
            event_id="evt-ipad-phase1",
            content="iPad Pro (11-inch) (3rd generation)",
        )
        phase1_result = L2Phase1Result(
            entities=[
                L2Phase1Entity(
                    surface="iPad Pro (11-inch) (3rd generation)",
                    normalized_name=canonical_name,
                    entity_type="hardware",
                    resolved_id="hardware:apple-ipad-pro-(11-inch)-(3rd-generation)",
                    confidence=1.0,
                )
            ]
        )

        resolved_mentions = await pipeline._resolve_phase1_entities(
            event,
            phase1_result,
            evidence_event_ids=[event.event_id],
            evidence_events=[event],
            allowed_entity_types=frozenset({"hardware"}),
        )

        assert resolved_mentions[0].resolved_entity_id == canonical_id
        entities = await pipeline._entity_catalog.list_entities(limit=10)
        ipad_entities = [
            entity
            for entity in entities
            if "apple-ipad-pro" in str(entity.get("canonical_name") or "")
        ]
        assert [entity["entity_id"] for entity in ipad_entities] == [canonical_id]


def test_inject_structured_entity_hints_noop_without_metadata():
    """Missing or empty hints should be a no-op."""
    from magi.memory.l2.pipeline import L2Pipeline
    pipeline = L2Pipeline.__new__(L2Pipeline)

    event = _make_memory_event(event_id="evt-nohints", content="no hints")
    event.metadata_json = {}

    existing: list[dict] = []
    pipeline._inject_structured_entity_hints(event, existing)
    assert existing == []


def test_inject_structured_graph_hints_adds_fact_claims():
    """Sensor-provided graph hints should be injected as deterministic Phase 1 fact claims."""
    from magi.memory.l2.models import L2Phase1Result
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_memory_event(event_id="evt-graph-hints", content="sensor supplied graph hints")
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "USES",
                "object_ref": "software:github",
                "object_type": "software",
                "fact_kind": "interaction_evidence",
                "confidence": 0.88,
                "evidence_text": "opened GitHub repeatedly",
            }
        ]
    }

    phase1_result = L2Phase1Result()
    pipeline._inject_structured_graph_hints(event, phase1_result)

    assert len(phase1_result.fact_claims) == 1
    claim = phase1_result.fact_claims[0]
    assert claim.subject_ref == "user:self"
    assert claim.subject_type == "user"
    assert claim.predicate == "USES"
    assert claim.object_ref == "software:github"
    assert claim.object_type == "software"
    assert claim.fact_kind == "interaction_evidence"
    assert claim.confidence == 0.88
    assert claim.evidence_text == "opened GitHub repeatedly"
    assert claim.supporting_event_ids == ["evt-graph-hints"]


@pytest.mark.asyncio
async def test_extract_worker_persists_structured_graph_hints_without_phase2_edges():
    from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth

    responses = [
        json.dumps(
            {
                "entities": [],
                "fact_claims": [],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "none"},
            }
        ),
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [],
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
            event = MemoryEvent(
                event_id="evt-structured-graph-1",
                correlation_id="evt-structured-graph-1",
                timestamp=time.time(),
                created_at=time.time(),
                event_type="SENSOR_EVENT",
                source="chrome_history",
                source_item_id="chrome:item-1",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.TOPOLOGY_ONLY,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="u1",
                task_id=None,
                content="GitHub profile page",
                author_type="external",
                content_type="observation",
                importance_score=0.6,
                level=EventLevel.INFO.value,
                metadata_json={
                    "structured_graph_hints": [
                        {
                            "subject_ref": "user:self",
                            "subject_type": "user",
                            "predicate": "USES",
                            "object_ref": "software:github",
                            "object_type": "software",
                            "fact_kind": "interaction_evidence",
                            "confidence": 0.91,
                            "evidence_text": "Visited GitHub profile page",
                        }
                    ]
                },
            )

            await store.ingest_event(event)

            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []

            assert any(
                edge["predicate"] == "USES"
                and edge["object_id"] == "software:github"
                and edge["fact_kind"] == "interaction_evidence"
                and edge["extraction_method"] == "structured_hint"
                for edge in relationships
            )
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_structured_hint_not_double_written_when_phase2_runs():
    """Structured hints written before Phase 1 must not be re-persisted after Phase 2.

    Before the fix, _build_structured_graph_candidates was called twice in the
    Phase 2 path: once for the direct-write before Phase 1, and again after
    Phase 2 where the results were merged and written a second time.  The second
    upsert triggered Noisy-OR confidence accumulation (e.g. 0.85 → ~0.98) and
    incremented observation_count — inflating both metrics.
    """
    from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth

    hint_confidence = 0.85

    # Phase 1 must return content so pipeline proceeds past the "empty Phase 1"
    # early-return.  The external_observation policy (allow_assertion_write=True)
    # blocks the fast-track path, so Phase 2 will run.
    responses = [
        json.dumps(
            {
                "entities": [
                    {"mention": "GitHub", "entity_ref": "software:github", "entity_type": "software"},
                ],
                "fact_claims": [
                    {
                        "predicate": "USES",
                        "subject_ref": "user:self",
                        "object_ref": "software:github",
                        "object_type": "software",
                        "confidence": hint_confidence,
                    },
                ],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "resolved"},
            }
        ),
        # Phase 2 returns no new graph edges — the only graph write should be
        # the single direct-write of the structured hint before Phase 1.
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [],
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
            event = MemoryEvent(
                event_id="evt-double-write-check-1",
                correlation_id="evt-double-write-check-1",
                timestamp=time.time(),
                created_at=time.time(),
                event_type="SENSOR_EVENT",
                source="chrome_history",
                source_item_id="chrome:item-dw-1",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.TOPOLOGY_ONLY,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="u1",
                task_id=None,
                content="GitHub profile page",
                author_type="external",
                content_type="observation",
                importance_score=0.6,
                level=EventLevel.INFO.value,
                metadata_json={
                    "structured_graph_hints": [
                        {
                            "subject_ref": "user:self",
                            "subject_type": "user",
                            "predicate": "USES",
                            "object_ref": "software:github",
                            "object_type": "software",
                            "fact_kind": "interaction_evidence",
                            "confidence": hint_confidence,
                            "evidence_text": "Visited GitHub profile page",
                        }
                    ]
                },
            )

            await store.ingest_event(event)

            for _ in range(80):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.02)

            assert store.l2 is not None
            relationships = await store.l2.get_relationships(subject_id="user:u1")

            hint_edges = [
                e for e in relationships
                if e["predicate"] == "USES" and e["object_id"] == "software:github"
            ]
            assert len(hint_edges) == 1, f"Expected one USES edge, got {len(hint_edges)}"

            edge = hint_edges[0]
            assert edge["confidence"] == pytest.approx(hint_confidence, abs=0.01), (
                f"Structured hint confidence should stay at {hint_confidence}, "
                f"got {edge['confidence']} — double-write would inflate via Noisy-OR"
            )
            assert edge["observation_count"] == 1, (
                f"Structured hint should be observed once, "
                f"got {edge['observation_count']} — indicates double-write"
            )
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_persists_category_facets_from_structured_graph_hints():
    from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth

    responses = [
        json.dumps(
            {
                "entities": [],
                "fact_claims": [],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "none"},
            }
        ),
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [],
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
            event = MemoryEvent(
                event_id="evt-structured-facet-1",
                correlation_id="evt-structured-facet-1",
                timestamp=time.time(),
                created_at=time.time(),
                event_type="SENSOR_EVENT",
                source="chrome_history",
                source_item_id="chrome:item-2",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.TOPOLOGY_ONLY,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="u1",
                task_id=None,
                content="Manner cafe page",
                author_type="external",
                content_type="observation",
                importance_score=0.6,
                level=EventLevel.INFO.value,
                metadata_json={
                    "structured_graph_hints": [
                        {
                            "subject_ref": "place:manner-xihu",
                            "subject_type": "place",
                            "predicate": "LOCATED_IN",
                            "object_ref": "place:hangzhou",
                            "object_type": "place",
                            "fact_kind": "public_topology",
                            "origin_mode": "source_structured",
                            "confidence": 0.98,
                            "attributes": {"category": "coffee_shop"},
                        }
                    ]
                },
            )

            await store.ingest_event(event)

            for _ in range(50):
                if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            facets = await store.l2.list_entity_facets(entity_id="place:manner-xihu", facet_name="category") if store.l2 is not None else []

            assert facets == [
                {
                    "entity_id": "place:manner-xihu",
                    "entity_type": "place",
                    "facet_name": "category",
                    "facet_value": "coffee_shop",
                    "confidence": 0.98,
                    "evidence_event_ids": ["evt-structured-facet-1"],
                    "source_type": "chrome_history",
                    "extraction_method": "structured_hint",
                }
            ]
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_build_structured_graph_candidates_rejects_stable_preference_hints():
    from magi.memory.evidence import classify_event_evidence, resolve_l2_policy
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_memory_event(event_id="evt-structured-pref", content="sensor hinted preference")
    event.source = "chrome_history"
    event.author_type = "external"
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "INTERESTED_IN",
                "object_ref": "topic:ai",
                "object_type": "topic",
                "fact_kind": "stable_preference",
                "confidence": 0.95,
            }
        ]
    }

    profile = _chrome_history_profile()
    policy = resolve_l2_policy(classify_event_evidence(event))
    candidates, rejected = pipeline._build_structured_graph_candidates(
        event=event,
        profile=profile,
        policy=policy,
        evidence_event_ids=[event.event_id],
    )

    assert candidates == []
    assert rejected == 1


@pytest.mark.asyncio
async def test_build_structured_graph_candidates_rejects_heuristic_follows_hints():
    from magi.memory.evidence import classify_event_evidence, resolve_l2_policy
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_memory_event(event_id="evt-structured-follows-heuristic", content="creator page")
    event.source = "chrome_history"
    event.author_type = "external"
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "FOLLOWS",
                "object_ref": "person:creator_1",
                "object_type": "person",
                "fact_kind": "interaction_evidence",
                "confidence": 0.94,
                "origin_mode": "heuristic",
                "attributes": {"page_kind": "video"},
            }
        ]
    }

    profile = _chrome_history_profile()
    policy = resolve_l2_policy(classify_event_evidence(event))
    candidates, rejected = pipeline._build_structured_graph_candidates(
        event=event,
        profile=profile,
        policy=policy,
        evidence_event_ids=[event.event_id],
    )

    assert candidates == []
    assert rejected == 1


@pytest.mark.asyncio
async def test_build_structured_graph_candidates_accepts_structured_follows_profile_hints():
    from magi.memory.evidence import classify_event_evidence, resolve_l2_policy
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_memory_event(event_id="evt-structured-follows-profile", content="creator page")
    event.source = "chrome_history"
    event.author_type = "external"
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "FOLLOWS",
                "object_ref": "person:creator_1",
                "object_type": "person",
                "fact_kind": "interaction_evidence",
                "confidence": 0.94,
                "origin_mode": "source_structured",
                "attributes": {"page_kind": "creator_profile"},
            }
        ]
    }

    profile = _chrome_history_profile()
    policy = resolve_l2_policy(classify_event_evidence(event))
    candidates, rejected = pipeline._build_structured_graph_candidates(
        event=event,
        profile=profile,
        policy=policy,
        evidence_event_ids=[event.event_id],
    )

    assert rejected == 0
    assert len(candidates) == 1
    assert candidates[0]["predicate"] == "FOLLOWS"
    assert candidates[0]["object_id"] == "person:creator_1"
    assert candidates[0]["extraction_method"] == "structured_hint"


@pytest.mark.asyncio
async def test_build_structured_graph_candidates_accepts_internal_topology_hints():
    from magi.memory.evidence import classify_event_evidence, resolve_l2_policy
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_memory_event(event_id="evt-structured-topology", content="creator profile")
    event.source = "chrome_history"
    event.author_type = "external"
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "subject_ref": "presence:bilibili:creator_1",
                "subject_type": "presence",
                "predicate": "ON_PLATFORM",
                "object_ref": "software:bilibili",
                "object_type": "software",
                "fact_kind": "public_topology",
                "origin_mode": "source_structured",
                "confidence": 0.99,
            }
        ]
    }

    profile = _chrome_history_profile()
    policy = resolve_l2_policy(classify_event_evidence(event))
    candidates, rejected = pipeline._build_structured_graph_candidates(
        event=event,
        profile=profile,
        policy=policy,
        evidence_event_ids=[event.event_id],
    )

    assert rejected == 0
    assert len(candidates) == 1
    assert candidates[0]["predicate"] == "ON_PLATFORM"
    assert candidates[0]["subject_id"] == "presence:bilibili:creator_1"
    assert candidates[0]["object_id"] == "software:bilibili"


class TestAliasValidation:
    """Tests for _is_valid_alias quality gate."""

    @pytest.fixture
    def pipeline_cls(self):
        from magi.memory.l2.pipeline import L2Pipeline
        return L2Pipeline

    def test_rejects_platform_alias_for_media(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        assert p._is_valid_alias("抖音", "坤的真爱粉的抖音直播间", "media") is False

    def test_rejects_platform_alias_for_person(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        assert p._is_valid_alias("YouTube", "some creator channel", "person") is False

    def test_allows_platform_alias_for_software(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        assert p._is_valid_alias("抖音", "Douyin", "software") is True

    def test_rejects_short_alias_for_long_name(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        assert p._is_valid_alias("X", "a very long canonical entity name", "media") is False

    def test_allows_same_alias_as_canonical(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        assert p._is_valid_alias("GitHub", "GitHub", "software") is True

    def test_allows_reasonable_alias(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        assert p._is_valid_alias("React.js", "React Framework", "technology") is True


class TestTypeMergeability:
    """Tests for _are_types_mergeable cross-type dedup gate."""

    @pytest.fixture
    def pipeline_cls(self):
        from magi.memory.l2.pipeline import L2Pipeline
        return L2Pipeline

    def test_same_type_always_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("software", "software") is True

    def test_software_and_product_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("software", "product") is True

    def test_software_and_activity_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("software", "activity") is True

    def test_media_and_topic_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("media", "topic") is True

    def test_person_and_group_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("person", "group") is True

    def test_person_and_software_not_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("person", "software") is False

    def test_place_and_media_not_mergeable(self, pipeline_cls):
        assert pipeline_cls._are_types_mergeable("place", "media") is False


class TestExtractionInstructions:
    """Tests for extraction_instructions wiring into prompt rendering."""

    def test_chrome_profile_has_extraction_instructions(self):
        profile = _chrome_history_profile()
        assert profile.extraction_instructions is not None
        assert "INTERESTED_IN" in profile.extraction_instructions
        assert "VIEWED" in profile.extraction_instructions

    def test_chat_profile_has_extraction_instructions(self):
        from magi.memory.l2.extraction_profiles import get_extraction_profiles
        profile = get_extraction_profiles()["chat.user_message"]
        assert profile.extraction_instructions is not None
        assert "direct user-authored chat messages" in profile.extraction_instructions
        assert "profile signals" in profile.extraction_instructions
        assert "PREFERRED_FORM_OF_ADDRESS" in profile.extraction_instructions
        assert "preference.address" not in profile.extraction_instructions
        assert "trait_name" not in profile.extraction_instructions

    def test_prompt_includes_extraction_instructions(self):
        from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
        from magi.memory.l2.models import L2EventWindow

        prompt = render_phase1_extract_prompt(
            event_window=L2EventWindow(events=[{"event_id": "e1", "content": "test page", "timestamp": 1.0}]),
            focal_subject={"subject_ref": "user:test", "subject_type": "user"},
            extraction_instructions="Use VIEWED for videos and INTERESTED_IN for topics.",
        )
        assert "## Source-Specific Instructions" in prompt
        assert "Use VIEWED for videos" in prompt

    def test_prompt_omits_section_when_no_instructions(self):
        from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
        from magi.memory.l2.models import L2EventWindow

        prompt = render_phase1_extract_prompt(
            event_window=L2EventWindow(events=[{"event_id": "e1", "content": "test page", "timestamp": 1.0}]),
            focal_subject={"subject_ref": "user:test", "subject_type": "user"},
            extraction_instructions=None,
        )
        assert "## Source-Specific Instructions" not in prompt

    def test_phase2_prompt_includes_resolved_entity_ids(self):
        from magi.memory.l2.pipeline.prompts import (
            PHASE2_INTEGRATE_SYSTEM_PROMPT,
            render_phase2_integrate_prompt,
        )

        phase2_prompt = render_phase2_integrate_prompt(
            phase1_result={
                "entities": [
                    {
                        "surface": "归潮",
                        "normalized_name": "归潮",
                        "entity_type": "media",
                        "specificity": "concrete",
                        "resolved_id": "media:1ee3b9131dd8",
                        "is_new": True,
                    }
                ],
                "fact_claims": [
                    {
                        "claim_id": "claim:1",
                        "subject_ref": "user:self",
                        "predicate": "LISTENED",
                        "object_ref": "归潮",
                        "object_type": "media",
                        "specificity": "concrete",
                        "confidence": 1.0,
                    }
                ],
            },
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )

        assert "**归潮** -> media:1ee3b9131dd8" in phase2_prompt
        assert "entity_id: media:1ee3b9131dd8" in phase2_prompt
        assert "Do not recreate graph edges" in PHASE2_INTEGRATE_SYSTEM_PROMPT
        assert "romanize" in PHASE2_INTEGRATE_SYSTEM_PROMPT

    def test_phase2_prompt_includes_all_phase1_entities(self):
        from magi.memory.l2.pipeline.prompts import render_phase2_integrate_prompt

        phase2_prompt = render_phase2_integrate_prompt(
            phase1_result={
                "entities": [
                    {
                        "surface": "Magi",
                        "normalized_name": "Magi",
                        "entity_type": "software",
                        "specificity": "concrete",
                        "resolved_id": "software:magi",
                        "is_new": False,
                    },
                    {
                        "surface": "Codex",
                        "normalized_name": "Codex",
                        "entity_type": "software",
                        "specificity": "concrete",
                        "resolved_id": "software:codex",
                        "is_new": True,
                    },
                ],
                "fact_claims": [],
            },
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )

        assert "**Magi** -> software:magi" in phase2_prompt
        assert "**Codex** -> software:codex" in phase2_prompt

    def test_phase2_prompt_includes_integration_instructions(self):
        from magi.memory.l2.pipeline.prompts import render_phase2_integrate_prompt

        phase2_prompt = render_phase2_integrate_prompt(
            phase1_result={"entities": [], "fact_claims": []},
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
            source_integration_instructions=(
                "For play history, derive preference_profile only from repeated plays."
            ),
        )

        assert "## Source-Specific Integration Instructions" in phase2_prompt
        assert "derive preference_profile only from repeated plays" in phase2_prompt

    def test_phase2_prompt_omits_integration_instructions_when_absent(self):
        from magi.memory.l2.pipeline.prompts import render_phase2_integrate_prompt

        phase2_prompt = render_phase2_integrate_prompt(
            phase1_result={"entities": [], "fact_claims": []},
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )

        assert "## Source-Specific Integration Instructions" not in phase2_prompt

    @pytest.mark.asyncio
    async def test_pipeline_passes_profile_phase2_instructions(self):
        phase2_instructions = "For play history, emit preference_profile only after repeated plays."
        adapter = _FakeAdapter(
            [
                json.dumps(
                    {
                        "entities": [],
                        "fact_claims": [
                            {
                                "subject_ref": "user:u1",
                                "subject_type": "user",
                                "predicate": "INTERESTED_IN",
                                "object_ref": "Track A",
                                "object_type": "media",
                                "fact_kind": "stable_preference",
                                "temporal_cue": "unspecified",
                                "polarity": "positive",
                                "specificity": "concrete",
                                "evidence_text": "played Track A",
                                "confidence": 0.9,
                                "supporting_event_ids": ["evt-phase2-profile-1"],
                            }
                        ],
                        "resolved_refs": [],
                        "diagnostics": {"entity_status": "none"},
                    }
                ),
                json.dumps(
                    {
                        "claim_assessments": [],
                        "assertion_candidates": [],
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
                extraction_profile_provider=lambda: [
                    ExtractionProfileSpec(
                        profile_id="source.play_history",
                        source_types=["play_history"],
                        allowed_entity_types=["media", "topic"],
                        allowed_predicates=["INTERESTED_IN"],
                        allow_graph=True,
                        allow_assertion=True,
                        phase2_instructions=phase2_instructions,
                    )
                ],
            )
            await store.initialize()
            try:
                await store.ingest_event(
                    {
                        "id": "evt-phase2-profile-1",
                        "type": EventTypes.USER_MESSAGE,
                        "timestamp": time.time(),
                        "source": "play_history",
                        "level": EventLevel.INFO.value,
                        "data": {
                            "user_id": "u1",
                            "session_id": "s1",
                            "content": "played Track A",
                        },
                    }
                )

                for _ in range(50):
                    if len(adapter.calls) >= 2:
                        break
                    await asyncio.sleep(0.01)

                assert len(adapter.calls) >= 2
                phase2_prompt = str(adapter.calls[-1]["prompt"])
                assert "## Source-Specific Integration Instructions" in phase2_prompt
                assert phase2_instructions in phase2_prompt
            finally:
                await store.shutdown()

    def test_override_replaces_extraction_instructions(self):
        from magi.memory.l2.extraction_profiles import ExtractionProfile, _apply_overrides
        profile = ExtractionProfile(profile_id="test", extraction_instructions="original")
        overridden = _apply_overrides(profile, {"extraction_instructions": "custom guidance"})
        assert overridden.extraction_instructions == "custom guidance"

    def test_override_preserves_extraction_instructions_when_absent(self):
        from magi.memory.l2.extraction_profiles import ExtractionProfile, _apply_overrides
        profile = ExtractionProfile(profile_id="test", extraction_instructions="original")
        overridden = _apply_overrides(profile, {})
        assert overridden.extraction_instructions == "original"

    def test_chrome_instructions_contain_convergence_guidance(self):
        profile = _chrome_history_profile()
        assert "SELECTIVE" in profile.extraction_instructions
        assert "MERGE" in profile.extraction_instructions
        assert "virtual_object" in profile.extraction_instructions

    def test_chrome_profile_keeps_internal_topology_out_of_llm_allowlists(self):
        profile = _chrome_history_profile()

        assert "presence" not in profile.allowed_entity_types
        assert "ON_PLATFORM" not in profile.allowed_predicates
        assert "presence" in profile.structured_allowed_entity_types
        assert "ON_PLATFORM" in profile.structured_allowed_predicates


class TestEntityTypeFiltering:
    """Tests for allowed_entity_types filtering in _resolve_phase1_entities."""

    @pytest.mark.asyncio
    async def test_disallowed_entity_type_is_filtered(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            phase1_payload = {
                "entities": [
                    {"surface": "GitHub", "entity_type": "software", "confidence": 0.95},
                    {"surface": "Schema Panel", "entity_type": "virtual_object", "confidence": 0.9},
                    {"surface": "SQLite", "entity_type": "technology", "confidence": 0.9},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            }
            phase1_result = L2Phase1Result.from_dict(phase1_payload)
            event = _make_memory_event(event_id="evt-filter-1", content="test")

            allowed = frozenset({"software", "technology", "media", "person", "topic"})
            resolved = await pipeline._resolve_phase1_entities(
                event, phase1_result,
                evidence_event_ids=["evt-filter-1"],
                allowed_entity_types=allowed,
            )

            resolved_types = {m.entity_type for m in resolved}
            assert "software" in resolved_types
            assert "technology" in resolved_types
            assert "virtual_object" not in resolved_types

    @pytest.mark.asyncio
    async def test_no_filter_when_allowed_types_is_none(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            phase1_payload = {
                "entities": [
                    {"surface": "anything", "entity_type": "virtual_object", "confidence": 0.9},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            }
            phase1_result = L2Phase1Result.from_dict(phase1_payload)
            event = _make_memory_event(event_id="evt-filter-2", content="test")

            resolved = await pipeline._resolve_phase1_entities(
                event, phase1_result,
                evidence_event_ids=["evt-filter-2"],
                allowed_entity_types=None,
            )
            assert len(resolved) == 1

    @pytest.mark.asyncio
    async def test_profile_signal_value_is_not_registered_as_entity(self):
        from magi.memory.l2.models import L2Phase1Result
        from magi.memory.l2.pipeline import L2Pipeline

        class _EntityCatalog:
            def __init__(self) -> None:
                self.entities: dict[str, dict[str, str]] = {}
                self.entity_sources: dict[str, tuple[str, ...]] = {}

            async def resolve_alias(self, _alias_text, *, entity_type=None):
                return {"decision": "no_match"}

            async def find_by_canonical_name(self, _canonical_name):
                return []

            async def upsert_entity(
                self,
                *,
                entity_id,
                canonical_name,
                entity_type,
                source_event_ids,
            ):
                self.entities[entity_id] = {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                }
                self.entity_sources[entity_id] = tuple(source_event_ids)

            async def add_alias(self, **_kwargs):
                return None

            async def record_mention(self, **_kwargs):
                return None

            async def filter_projection_source_event_ids(self, *, event_ids, **_kwargs):
                return tuple(event_ids)

            async def list_entities(self, *, limit=20):
                return list(self.entities.values())[:limit]

        pipeline = L2Pipeline.__new__(L2Pipeline)
        pipeline._entity_catalog = _EntityCatalog()
        pipeline._llm_service = None
        pipeline._entity_resolution_cache = {}

        phase1_payload = {
            "entities": [
                {"surface": "哈基米", "normalized_name": "哈基米", "entity_type": "concept", "confidence": 0.95},
                {"surface": "子涵", "normalized_name": "子涵", "entity_type": "concept", "confidence": 0.95},
                {"surface": "GitHub", "normalized_name": "GitHub", "entity_type": "software", "confidence": 0.95},
            ],
            "fact_claims": [
                {
                    "subject_ref": "user:self",
                    "predicate": "PREFERRED_FORM_OF_ADDRESS",
                    "object_ref": "哈基米或者子涵",
                    "object_type": "concept",
                    "fact_kind": "explicit_fact",
                    "confidence": 0.3,
                }
            ],
            "resolved_refs": [],
        }
        phase1_result = L2Phase1Result.from_dict(phase1_payload)
        event = _make_memory_event(
            event_id="evt-profile-signal",
            content="叫我哈基米或者子涵都行吧，我还在用 GitHub",
        )

        resolved = await pipeline._resolve_phase1_entities(
            event,
            phase1_result,
            evidence_event_ids=["evt-profile-signal"],
            evidence_events=[event],
            allowed_entity_types=frozenset({"concept", "software"}),
            profile_signal_object_refs=pipeline._collect_profile_signal_object_refs(phase1_result),
        )

        assert [mention.normalized_surface for mention in resolved] == ["GitHub"]
        entities = await pipeline._entity_catalog.list_entities(limit=20)
        assert {entity["canonical_name"] for entity in entities} == {"GitHub"}
        assert set(pipeline._entity_catalog.entity_sources.values()) == {
            ("evt-profile-signal",)
        }

    @pytest.mark.asyncio
    async def test_vague_references_are_not_registered_as_entities(self):
        from magi.memory.l2.models import L2Phase1Result
        from magi.memory.l2.pipeline import L2Pipeline

        class _EntityCatalog:
            def __init__(self) -> None:
                self.entities: dict[str, dict[str, str]] = {}

            async def resolve_alias(self, _alias_text, *, entity_type=None):
                return {"decision": "no_match"}

            async def find_by_canonical_name(self, _canonical_name):
                return []

            async def upsert_entity(
                self,
                *,
                entity_id,
                canonical_name,
                entity_type,
                source_event_ids,
            ):
                self.entities[entity_id] = {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                }

            async def add_alias(self, **_kwargs):
                return None

            async def record_mention(self, **_kwargs):
                return None

            async def filter_projection_source_event_ids(self, *, event_ids, **_kwargs):
                return tuple(event_ids)

            async def list_entities(self, *, limit=20):
                return list(self.entities.values())[:limit]

        pipeline = L2Pipeline.__new__(L2Pipeline)
        pipeline._entity_catalog = _EntityCatalog()
        pipeline._llm_service = None
        pipeline._entity_resolution_cache = {}

        phase1_result = L2Phase1Result.from_dict({
            "entities": [
                {"surface": "他", "normalized_name": "德克萨斯", "entity_type": "person", "confidence": 0.95},
                {"surface": "那个", "normalized_name": "that one", "entity_type": "other", "confidence": 0.95},
                {"surface": "app", "normalized_name": "app", "entity_type": "software", "confidence": 0.95},
                {"surface": "新专", "normalized_name": "新专", "entity_type": "media", "specificity": "underspecified", "confidence": 0.95},
                {"surface": "GitHub", "normalized_name": "GitHub", "entity_type": "software", "confidence": 0.95},
            ],
            "fact_claims": [],
            "resolved_refs": [],
        })
        event = _make_memory_event(
            event_id="evt-vague-entity",
            content="他和那个 app 是 GitHub 吗",
        )

        resolved = await pipeline._resolve_phase1_entities(
            event,
            phase1_result,
            evidence_event_ids=["evt-vague-entity"],
            evidence_events=[event],
            allowed_entity_types=frozenset({"person", "other", "software", "media"}),
        )

        assert [mention.normalized_surface for mention in resolved] == ["GitHub"]
        entities = await pipeline._entity_catalog.list_entities(limit=20)
        assert {entity["canonical_name"] for entity in entities} == {"GitHub"}

    def test_phase1_projection_rejects_low_value_open_predicate_but_keeps_stable_custom_predicate(self):
        from magi.memory.l2.models import L2Phase1FactClaim, L2Phase1Result
        from magi.memory.l2.ontology import PREDICATE_REGISTRY
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-open-predicate", content="Magi 维护 core-tools 插件")
        profile = SimpleNamespace(
            allow_graph=True,
            effective_structured_allowed_entity_types=frozenset({"product", "software"}),
            effective_structured_allowed_predicates=PREDICATE_REGISTRY,
        )
        phase1_result = L2Phase1Result(
            fact_claims=[
                L2Phase1FactClaim(
                    claim_id="claim:1",
                    subject_ref="user:local_user",
                    predicate="ASKED_ABOUT",
                    object_ref="app",
                    object_type="software",
                    confidence=0.9,
                    supporting_event_ids=["evt-open-predicate"],
                ),
                L2Phase1FactClaim(
                    claim_id="claim:2",
                    subject_ref="user:local_user",
                    predicate="MAINTAINS",
                    object_ref="Magi",
                    object_type="product",
                    confidence=0.9,
                    supporting_event_ids=["evt-open-predicate"],
                ),
            ]
        )
        prepared, rejected_count = pipeline._project_phase1_graph_candidates(
            phase1_result=phase1_result,
            event=event,
            profile=profile,
            resolved_mentions=[],
            evidence_event_ids=["evt-open-predicate"],
            catalog_name_index={},
        )

        assert rejected_count == 1
        assert len(prepared) == 1
        assert prepared[0]["predicate"] == "MAINTAINS"
        assert prepared[0]["object_id"] == "product:magi"

    def test_phase2_profile_assertion_preserves_phase1_value(self):
        from magi.memory.l2.models import (
            L2Phase1FactClaim,
            L2Phase1Result,
            L2Phase2AssertionCandidate,
        )
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-profile-value", content="叫我哈基米或者子涵都行吧")
        phase1_result = L2Phase1Result(
            fact_claims=[
                L2Phase1FactClaim(
                    claim_id="claim:1",
                    subject_ref="user:self",
                    predicate="PREFERRED_FORM_OF_ADDRESS",
                    object_ref="哈基米或者子涵",
                    object_type="concept",
                    fact_kind="explicit_fact",
                    confidence=0.3,
                    supporting_event_ids=["evt-profile-value"],
                )
            ]
        )

        prepared, rejected_count = pipeline._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                allowed_assertion_families={"communication_profile"},
            ),
            policy=SimpleNamespace(allow_assertion_write=True),
            graph_candidates=[],
            default_event_ids=["evt-profile-value"],
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="communication_profile",
                    trait_name="communication.address.preferred",
                    trait_value="haji_mi_or_zi_han",
                    supporting_claim_ids=["claim:1"],
                )
            ],
            phase1_result=phase1_result,
        )

        assert rejected_count == 0
        assert prepared[0]["trait_value"] == "哈基米或者子涵"

    def test_profile_signal_claim_requires_current_user_evidence(self):
        from magi.memory.l2.models import L2BatchEvent, L2Phase1Result
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        phase1_result = L2Phase1Result.from_dict({
            "entities": [],
            "fact_claims": [
                {
                    "subject_ref": "user:self",
                    "predicate": "REAL_NAME",
                    "object_ref": "苏眠",
                    "object_type": "person",
                    "fact_kind": "explicit_fact",
                    "evidence_text": "我是苏眠。",
                    "confidence": 0.8,
                },
                {
                    "subject_ref": "user:self",
                    "predicate": "PREFERRED_FORM_OF_ADDRESS",
                    "object_ref": "子涵",
                    "object_type": "concept",
                    "fact_kind": "explicit_fact",
                    "evidence_text": "叫我子涵就好。",
                    "confidence": 0.8,
                },
            ],
            "resolved_refs": [],
        })
        events = [
            L2BatchEvent(
                event_id="evt-profile-evidence",
                content="你可以叫我子涵就好。",
                author_type="user",
            )
        ]

        rejected_count = pipeline._filter_ungrounded_profile_signal_claims(phase1_result, events)

        assert rejected_count == 1
        assert [claim.predicate for claim in phase1_result.fact_claims] == [
            "PREFERRED_FORM_OF_ADDRESS"
        ]

    def test_phase2_profile_assertion_requires_phase1_profile_signal(self):
        from magi.memory.l2.models import L2Phase1Result, L2Phase2AssertionCandidate
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-profile-inference", content="帮我全面审查这段代码")

        prepared, rejected_count = pipeline._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                allowed_assertion_families={"communication_profile"},
            ),
            policy=SimpleNamespace(allow_assertion_write=True),
            graph_candidates=[],
            default_event_ids=["evt-profile-inference"],
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="communication_profile",
                    trait_name="communication.response_style.preferred",
                    trait_value="全面审查与详细建议",
                    supporting_claim_ids=["claim:invented"],
                )
            ],
            phase1_result=L2Phase1Result.from_dict({
                "entities": [],
                "fact_claims": [],
                "resolved_refs": [],
            }),
        )

        assert prepared == []
        assert rejected_count == 1

    def test_phase2_assertions_rejected_when_mode_is_derived(self):
        from magi.memory.l2.models import L2Phase2AssertionCandidate
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-derived-mode", content="played Track A repeatedly")

        prepared, rejected_count = pipeline._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                assertion_mode="derived",
                allowed_assertion_families={"preference_profile"},
                allowed_assertion_traits=None,
            ),
            policy=SimpleNamespace(allow_assertion_write=True),
            graph_candidates=[],
            default_event_ids=["evt-derived-mode"],
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="preference_profile",
                    trait_name="preference.music",
                    trait_value="Track A",
                )
            ],
        )

        assert prepared == []
        assert rejected_count == 1

    def test_phase2_assertions_respect_trait_allowlist(self):
        from magi.memory.l2.models import L2Phase2AssertionCandidate
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-trait-allowlist", content="played Track A")

        prepared, rejected_count = pipeline._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                assertion_mode="phase2_candidate",
                allowed_assertion_families={"interest_profile"},
                allowed_assertion_traits=frozenset({"interest.music"}),
            ),
            policy=SimpleNamespace(allow_assertion_write=True),
            graph_candidates=[],
            default_event_ids=["evt-trait-allowlist"],
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="interest_profile",
                    trait_name="interest.music",
                    trait_value="Track A",
                    supporting_claim_ids=["claim:1"],
                ),
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="interest_profile",
                    trait_name="interest.movie",
                    trait_value="Movie B",
                    supporting_claim_ids=["claim:1"],
                ),
            ],
            phase1_result=_phase1_result_with_support("evt-trait-allowlist"),
        )

        assert rejected_count == 1
        assert [item["trait_name"] for item in prepared] == ["interest.music"]

    def test_phase2_assertions_allow_trait_namespace_wildcard(self):
        from magi.memory.l2.models import L2Phase2AssertionCandidate
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-trait-wildcard", content="played Track A")

        prepared, rejected_count = pipeline._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                assertion_mode="phase2_candidate",
                allowed_assertion_families={"interest_profile"},
                allowed_assertion_traits=frozenset({"interest.*"}),
            ),
            policy=SimpleNamespace(allow_assertion_write=True),
            graph_candidates=[],
            default_event_ids=["evt-trait-wildcard"],
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="interest_profile",
                    trait_name="interest.music",
                    trait_value="Track A",
                    supporting_claim_ids=["claim:1"],
                ),
            ],
            phase1_result=_phase1_result_with_support("evt-trait-wildcard"),
        )

        assert rejected_count == 0
        assert [item["trait_name"] for item in prepared] == ["interest.music"]

    def test_phase2_assertions_respect_policy_assertion_scope(self):
        from magi.memory.l2.models import L2Phase2AssertionCandidate
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        event = _make_memory_event(event_id="evt-assertion-scope", content="Chrome users discussed Magi")

        prepared, rejected_count = pipeline._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                assertion_mode="phase2_candidate",
                allowed_assertion_families={"interest_profile", "public_sentiment"},
                allowed_assertion_traits=None,
            ),
            policy=SimpleNamespace(
                allow_assertion_write=True,
                assertion_scope="topology_only",
            ),
            graph_candidates=[],
            default_event_ids=["evt-assertion-scope"],
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="interest_profile",
                    trait_name="interest.music",
                    trait_value="Track A",
                    supporting_claim_ids=["claim:1"],
                ),
                L2Phase2AssertionCandidate(
                    entity_ref="user:local_user",
                    trait_family="public_sentiment",
                    trait_name="sentiment.magi",
                    trait_value="positive",
                    supporting_claim_ids=["claim:1"],
                ),
            ],
            phase1_result=_phase1_result_with_support("evt-assertion-scope"),
        )

        assert rejected_count == 1
        assert [item["trait_family"] for item in prepared] == ["public_sentiment"]


class TestEntityNameQuality:
    """Tests for _is_quality_entity_name noise filter."""

    @pytest.fixture
    def pipeline_cls(self):
        from magi.memory.l2.pipeline import L2Pipeline
        return L2Pipeline

    def test_accepts_short_name(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("Claude") is True

    def test_accepts_cjk_short(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("哔哩哔哩") is True

    def test_rejects_empty(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("") is False

    def test_rejects_wide_cjk_name(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("好好好最喜欢的一集以前从来没看过这么好的节目真是太棒了") is False

    def test_rejects_cjk_sentence(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("好好好！最喜欢的一集！") is False

    def test_rejects_email(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("user@example.com") is False

    def test_rejects_ip_address(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("192.168.1.1") is False

    def test_rejects_ui_label(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("Sign in") is False

    def test_accepts_product_name_with_version(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("IntelliJ IDEA 2026.1") is True

    def test_rejects_only_punctuation(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("!!!???") is False

    def test_accepts_name_at_width_boundary(self, pipeline_cls):
        name = "A" * 50  # 50 display-width units (ASCII)
        assert pipeline_cls._is_quality_entity_name(name) is True
        assert pipeline_cls._is_quality_entity_name(name + "B") is False

    def test_accepts_ori_long_english_title(self, pipeline_cls):
        assert pipeline_cls._is_quality_entity_name("Ori and the Will of the Wisps") is True


class TestSameNameEntityDedup:
    """Tests for same-name entity dedup in _resolve_entity_id."""

    @pytest.mark.asyncio
    async def test_reuses_existing_entity_with_same_name(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            phase1_first = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Claude", "entity_type": "software", "confidence": 0.95,
                     "normalized_name": "Claude"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event1 = _make_memory_event(event_id="evt-dedup-1", content="test Claude software")
            resolved1 = await pipeline._resolve_phase1_entities(
                event1, phase1_first,
                evidence_event_ids=["evt-dedup-1"],
            )
            assert len(resolved1) == 1
            first_entity_id = resolved1[0].resolved_entity_id

            # Phase 1 with same canonical name but different type (technology)
            phase1_second = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Claude AI", "entity_type": "technology", "confidence": 0.92,
                     "normalized_name": "Claude"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event2 = _make_memory_event(event_id="evt-dedup-2", content="test Claude technology")
            resolved2 = await pipeline._resolve_phase1_entities(
                event2, phase1_second,
                evidence_event_ids=["evt-dedup-2"],
            )
            assert len(resolved2) == 1
            # Should reuse the same entity_id (deduped by name + mergeable type)
            assert resolved2[0].resolved_entity_id == first_entity_id

    @pytest.mark.asyncio
    async def test_does_not_dedup_incompatible_types(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            phase1_first = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Claude", "entity_type": "person", "confidence": 0.95,
                     "normalized_name": "Claude"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event1 = _make_memory_event(event_id="evt-dedup-3", content="test")
            resolved1 = await pipeline._resolve_phase1_entities(
                event1, phase1_first,
                evidence_event_ids=["evt-dedup-3"],
            )
            first_id = resolved1[0].resolved_entity_id

            phase1_second = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Claude", "entity_type": "software", "confidence": 0.92,
                     "normalized_name": "Claude"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event2 = _make_memory_event(event_id="evt-dedup-4", content="test")
            resolved2 = await pipeline._resolve_phase1_entities(
                event2, phase1_second,
                evidence_event_ids=["evt-dedup-4"],
            )
            # person and software are NOT mergeable -> different entity_id
            assert resolved2[0].resolved_entity_id != first_id


class TestEntityResolutionCache:
    """Tests for session-level entity resolution memo cache."""

    @pytest.mark.asyncio
    async def test_cache_avoids_repeated_alias_lookups(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            phase1 = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Magi", "entity_type": "software", "confidence": 0.95,
                     "normalized_name": "Magi"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event1 = _make_memory_event(event_id="evt-cache-1", content="test Magi")
            resolved1 = await pipeline._resolve_phase1_entities(
                event1, phase1, evidence_event_ids=["evt-cache-1"],
            )
            assert len(resolved1) == 1
            first_id = resolved1[0].resolved_entity_id

            # Second call with identical mention should hit cache
            event2 = _make_memory_event(event_id="evt-cache-2", content="test Magi again")
            resolved2 = await pipeline._resolve_phase1_entities(
                event2, phase1, evidence_event_ids=["evt-cache-2"],
            )
            assert len(resolved2) == 1
            assert resolved2[0].resolved_entity_id == first_id

            # Verify cache is populated
            cache = getattr(pipeline, "_entity_resolution_cache", {})
            assert ("magi", "software") in cache

    @pytest.mark.asyncio
    async def test_cache_key_is_type_sensitive(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            # Create entity "Magi" as software
            phase1_sw = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Magi", "entity_type": "software", "confidence": 0.95,
                     "normalized_name": "Magi"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event1 = _make_memory_event(event_id="evt-ct-1", content="test Magi sw")
            await pipeline._resolve_phase1_entities(
                event1, phase1_sw, evidence_event_ids=["evt-ct-1"],
            )

            # Create entity "Magi" as person (different type → different cache key)
            phase1_person = L2Phase1Result.from_dict({
                "entities": [
                    {"surface": "Magi", "entity_type": "person", "confidence": 0.95,
                     "normalized_name": "Magi"},
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            event2 = _make_memory_event(event_id="evt-ct-2", content="test Magi person")
            resolved2 = await pipeline._resolve_phase1_entities(
                event2, phase1_person, evidence_event_ids=["evt-ct-2"],
            )
            assert len(resolved2) == 1

            cache = getattr(pipeline, "_entity_resolution_cache", {})
            assert ("magi", "software") in cache
            assert ("magi", "person") in cache


class TestPhase2CatalogNameIndex:
    """Tests for Phase 2 object resolution using catalog name index."""

    @pytest.fixture
    def pipeline_cls(self):
        from magi.memory.l2.pipeline import L2Pipeline
        return L2Pipeline

    def test_catalog_index_hit(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        p._entity_catalog = None
        index = {"bilibili": "software:bilibili-hash"}
        result = p._resolve_phase2_object_id(
            raw_object_ref="bilibili",
            object_type="software",
            resolved_mentions=[],
            catalog_name_index=index,
        )
        assert result == "software:bilibili-hash"

    def test_catalog_index_miss_falls_back(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        p._entity_catalog = None
        index = {"something_else": "software:other"}
        result = p._resolve_phase2_object_id(
            raw_object_ref="bilibili",
            object_type="software",
            resolved_mentions=[],
            catalog_name_index=index,
        )
        # Falls back to _build_concept_node
        assert result is not None
        assert result != "software:other"

    def test_resolved_mentions_take_precedence(self, pipeline_cls):
        from magi.memory.l2.pipeline import ResolvedEntityMention
        p = pipeline_cls.__new__(pipeline_cls)
        p._entity_catalog = None
        mention = ResolvedEntityMention(
            mention_text="bilibili",
            normalized_surface="bilibili",
            entity_type="software",
            resolved_entity_id="software:mention-resolved",
            confidence=0.95,
        )
        index = {"bilibili": "software:catalog-entity"}
        result = p._resolve_phase2_object_id(
            raw_object_ref="bilibili",
            object_type="software",
            resolved_mentions=[mention],
            catalog_name_index=index,
        )
        assert result == "software:mention-resolved"

    @pytest.mark.asyncio
    async def test_rejects_invented_colon_id_when_catalog_index_is_available(self):
        from magi.memory.l2.models import L2Phase1FactClaim, L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)
            event = _make_memory_event(
                event_id="evt-guichao",
                content="在网易云音乐听了蔡明希（不才）的《归潮》",
            )
            phase1_result = L2Phase1Result.from_dict({
                "entities": [
                    {
                        "surface": "归潮",
                        "normalized_name": "归潮",
                        "entity_type": "media",
                        "confidence": 0.95,
                    }
                ],
                "fact_claims": [],
                "resolved_refs": [],
            })
            resolved_mentions = await pipeline._resolve_phase1_entities(
                event,
                phase1_result,
                evidence_event_ids=[event.event_id],
                evidence_events=[event],
            )
            catalog_name_index = await pipeline._build_catalog_name_index()

            class _FakeProfile:
                allow_graph = True
                effective_structured_allowed_entity_types = frozenset({"media"})
                effective_structured_allowed_predicates = frozenset({"LISTENED"})

            invented_claim = L2Phase1FactClaim(
                claim_id="claim:1",
                subject_ref="user:u1",
                predicate="LISTENED",
                object_ref="media:guichao-caimingxi",
                object_type="media",
                confidence=1.0,
                supporting_event_ids=[event.event_id],
            )
            prepared, rejected = pipeline._project_phase1_graph_candidates(
                phase1_result=L2Phase1Result(fact_claims=[invented_claim]),
                event=event,
                profile=_FakeProfile(),
                resolved_mentions=resolved_mentions,
                evidence_event_ids=[event.event_id],
                catalog_name_index=catalog_name_index,
            )

            assert prepared == []
            assert rejected == 1

            surface_claim = L2Phase1FactClaim(
                claim_id="claim:1",
                subject_ref="user:u1",
                predicate="LISTENED",
                object_ref="归潮",
                object_type="media",
                confidence=1.0,
                supporting_event_ids=[event.event_id],
            )
            prepared, rejected = pipeline._project_phase1_graph_candidates(
                phase1_result=L2Phase1Result(fact_claims=[surface_claim]),
                event=event,
                profile=_FakeProfile(),
                resolved_mentions=resolved_mentions,
                evidence_event_ids=[event.event_id],
                catalog_name_index=catalog_name_index,
            )

            assert rejected == 0
            assert prepared[0]["object_id"] == phase1_result.entities[0].resolved_id
            assert prepared[0]["object_id"] == resolved_mentions[0].resolved_entity_id


class TestCatalogFindByCanonicalName:
    """Tests for L2EntityCatalog.find_by_canonical_name."""

    @pytest.mark.asyncio
    async def test_find_existing_entity_by_name(self):
        from magi.memory.l2.entities.catalog import L2EntityCatalog

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "test.db")
            _migrate_memory_shared_schema(db_path)
            catalog = L2EntityCatalog(db_path=db_path)
            await catalog.initialize()
            await catalog.upsert_entity(
                entity_id="software:claude",
                canonical_name="Claude",
                entity_type="software",
            )
            results = await catalog.find_by_canonical_name("Claude")
            assert len(results) == 1
            assert results[0]["entity_id"] == "software:claude"
            assert results[0]["entity_type"] == "software"

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self):
        from magi.memory.l2.entities.catalog import L2EntityCatalog

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "test.db")
            _migrate_memory_shared_schema(db_path)
            catalog = L2EntityCatalog(db_path=db_path)
            await catalog.initialize()
            await catalog.upsert_entity(
                entity_id="software:claude",
                canonical_name="Claude",
                entity_type="software",
            )
            results = await catalog.find_by_canonical_name("claude")
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_filter_by_type(self):
        from magi.memory.l2.entities.catalog import L2EntityCatalog

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "test.db")
            _migrate_memory_shared_schema(db_path)
            catalog = L2EntityCatalog(db_path=db_path)
            await catalog.initialize()
            await catalog.upsert_entity(
                entity_id="software:claude",
                canonical_name="Claude",
                entity_type="software",
            )
            await catalog.upsert_entity(
                entity_id="person:claude",
                canonical_name="Claude",
                entity_type="person",
            )
            results_all = await catalog.find_by_canonical_name("Claude")
            assert len(results_all) == 2

            results_person = await catalog.find_by_canonical_name("Claude", entity_type="person")
            assert len(results_person) == 1
            assert results_person[0]["entity_id"] == "person:claude"

    @pytest.mark.asyncio
    async def test_returns_empty_for_nonexistent(self):
        from magi.memory.l2.entities.catalog import L2EntityCatalog

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "test.db")
            _migrate_memory_shared_schema(db_path)
            catalog = L2EntityCatalog(db_path=db_path)
            await catalog.initialize()
            results = await catalog.find_by_canonical_name("NonExistent")
            assert results == []


# ── Episode formation hints: touched place ids + topic keys (Task 1.1) ──


class TestDerivePlaceAndTopicHints:
    """Pure derivation of touched_place_ids + touched_topic_keys from touched entities.

    Episode formation needs place + topic hints so the worker can pass them into
    EpisodeCandidateJob (today only entity_ids flow through, collapsing every
    episode into 30-min activity buckets). Entity ids are formatted
    ``{entity_type}:{slug}``, so the type is recoverable from the id prefix.
    """

    def _pipeline(self):
        from magi.memory.l2.pipeline import L2Pipeline

        return L2Pipeline.__new__(L2Pipeline)

    def test_place_ids_are_place_typed_touched_entities(self):
        pipeline = self._pipeline()
        place_ids, _topic_keys = pipeline._derive_place_and_topic_hints(
            [
                "place:shanghai",
                "person:alice",
                "place:tokyo",
                "software:github",
            ]
        )
        assert place_ids == ["place:shanghai", "place:tokyo"]

    def test_topic_keys_are_sorted_unique_topic_typed_entities(self):
        pipeline = self._pipeline()
        _place_ids, topic_keys = pipeline._derive_place_and_topic_hints(
            [
                "topic:rust",
                "topic:ai",
                "topic:rust",
                "person:bob",
            ]
        )
        assert topic_keys == ["topic:ai", "topic:rust"]

    def test_empty_touched_entities_yield_empty_hints(self):
        pipeline = self._pipeline()
        place_ids, topic_keys = pipeline._derive_place_and_topic_hints([])
        assert place_ids == []
        assert topic_keys == []

    def test_no_place_or_topic_entities_yield_empty_hints(self):
        pipeline = self._pipeline()
        place_ids, topic_keys = pipeline._derive_place_and_topic_hints(
            ["person:alice", "software:github", "user:local_user"]
        )
        assert place_ids == []
        assert topic_keys == []


class TestEpisodeCandidateJobEntityAttribution:
    def _worker(self):
        from magi.memory.l2.pipeline.workers import L2PipelineWorkerMixin

        return L2PipelineWorkerMixin()

    def _job(self):
        from magi.memory.l2.models import L2BatchJob

        return L2BatchJob(
            job_id="job-episode-attribution",
            bucket_key="session:s1",
            flush_reason="test",
            estimated_tokens=0,
            events=[
                {
                    "event_id": "evt-chat",
                    "timestamp": 100.0,
                    "event_type": EventTypes.USER_MESSAGE,
                },
                {
                    "event_id": "evt-browse",
                    "timestamp": 120.0,
                    "event_type": "SENSOR_EVENT",
                },
            ],
        )

    def test_episode_jobs_use_per_event_entity_map(self):
        jobs = self._worker()._build_episode_candidate_jobs(
            self._job(),
            result={
                "event_entity_map": {
                    "evt-chat": ["person:sarah", "user:local_user"],
                    "evt-browse": ["software:v2ex"],
                },
                "touched_place_ids": [],
                "touched_topic_keys": [],
            },
            touched_entity_ids=["person:sarah", "software:v2ex", "user:local_user"],
        )

        assert [job.event_id for job in jobs] == ["evt-chat", "evt-browse"]
        assert jobs[0].entity_ids == ["person:sarah", "user:local_user"]
        assert jobs[1].entity_ids == ["software:v2ex"]

    def test_episode_jobs_fall_back_to_batch_entities_without_event_map(self):
        jobs = self._worker()._build_episode_candidate_jobs(
            self._job(),
            result={"touched_place_ids": [], "touched_topic_keys": []},
            touched_entity_ids=["person:sarah", "software:v2ex"],
        )

        assert jobs[0].entity_ids == ["person:sarah", "software:v2ex"]
        assert jobs[1].entity_ids == ["person:sarah", "software:v2ex"]

    def test_first_context_story_never_forms_an_episode_candidate(self):
        job = self._job()
        job.events[0]["metadata_json"] = {
            "interaction_kind": "first_context_story",
            "first_context": {
                "question_id": "recent_feeling",
                "question_text": "最近有哪件小事，让你心情有一点变化？",
            },
        }

        jobs = self._worker()._build_episode_candidate_jobs(
            job,
            result={"touched_place_ids": [], "touched_topic_keys": []},
            touched_entity_ids=["user:local_user"],
        )

        assert [item.event_id for item in jobs] == ["evt-browse"]

    def test_phase2_touch_scope_exposes_event_entity_map(self):
        from magi.memory.l2.pipeline.phase2_flow import _phase2_touch_scope

        class _Pipeline:
            def _collect_touched_entities(self, graph_candidates, assertion_candidates):
                _ = graph_candidates, assertion_candidates
                return ["user:local_user", "person:sarah", "software:v2ex"]

            def _derive_place_and_topic_hints(self, touched_entity_ids):
                _ = touched_entity_ids
                return [], []

        batch = SimpleNamespace(direct_write_candidates=[], self_entity_id=None)
        candidates = SimpleNamespace(
            graph_candidates=[
                {
                    "subject_id": "user:local_user",
                    "object_id": "person:sarah",
                    "evidence_event_ids": ["evt-chat"],
                }
            ],
            assertion_candidates=[
                {
                    "entity_id": "software:v2ex",
                    "evidence_events": ["evt-browse"],
                }
            ],
            contradiction_hints=[],
        )

        payload = _phase2_touch_scope(
            _Pipeline(),
            batch,
            candidates,
            relation_count=1,
            conflict_decision=None,
        )

        assert payload["event_entity_map"] == {
            "evt-chat": ["person:sarah", "user:local_user"],
            "evt-browse": ["software:v2ex"],
        }
