from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory import MemoryStoreTuning
from magi.memory import UnifiedMemoryStore as _RuntimeUnifiedMemoryStore
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION
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
        claim_ids = re.findall(r"\bclm_[0-9a-f]{32}\b", prompt)
        if claim_ids:
            response_text = response_text.replace('"claim:1"', json.dumps(claim_ids[0]))
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


def _semantic_routes_for_phase1(phase1_result):  # type: ignore[no-untyped-def]
    from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route

    routes = {}
    for claim in phase1_result.fact_claims:
        object_ref = str(claim.object_ref or "")
        object_entity_id = object_ref if ":" in object_ref else None
        subject_ref = str(claim.subject_ref or "")
        if subject_ref.startswith("user:"):
            subject_ref = "user:local_user"
        route = derive_semantic_route(
            SemanticRouteInput(
                claim_id=claim.claim_id,
                subject_id=subject_ref,
                subject_type=str(claim.subject_type or "user"),
                canonical_predicate=str(claim.predicate or ""),
                fact_kind=str(claim.fact_kind or "explicit_fact"),
                object_type=str(claim.object_type or "other"),
                object_value=claim.object_ref,
                object_entity_id=object_entity_id,
                temporal_cue=str(claim.temporal_cue),
                specificity=str(claim.specificity or "concrete"),
                target_from=claim.target_from,
                target_to=claim.target_to,
                raw_time_expression=claim.raw_time_expression,
                time_resolution="unscheduled",
            )
        )
        routes[claim.claim_id] = route
    return routes


def _synthetic_occurrence_stats_for_phase1(phase1_result):  # type: ignore[no-untyped-def]
    """Return explicit ledger-shaped statistics for validator unit tests."""

    from magi.memory.l2.assertions.occurrence_stats import (
        ClaimOccurrenceStats,
        ClaimRouteValueKey,
    )

    routes = _semantic_routes_for_phase1(phase1_result)
    claims_by_key = {}
    events_by_key = {}
    policy_claims_by_key = {}
    for claim in phase1_result.fact_claims:
        route = routes.get(claim.claim_id)
        if route is None or not route.can_project_assertion or not route.value_fingerprint:
            continue
        key = ClaimRouteValueKey(str(route.slot_key), str(route.value_fingerprint))
        claims_by_key.setdefault(key, set()).add(claim.claim_id)
        events_by_key.setdefault(key, set()).update(claim.supporting_event_ids)
        policy_claims_by_key.setdefault(key, []).append(claim)
    return {
        key: ClaimOccurrenceStats(
            key=key,
            fact_kind=_single_phase1_claim_field(
                policy_claims_by_key[key],
                "fact_kind",
                "explicit_fact",
            ),
            canonical_predicate=_single_phase1_claim_field(
                policy_claims_by_key[key],
                "predicate",
                "",
            ).upper(),
            temporal_cue=_single_phase1_claim_field(
                policy_claims_by_key[key],
                "temporal_cue",
                "unspecified",
            ),
            evidence_class="user_self_report",
            source_strength="direct_user",
            durable_permitted=True,
            claim_ids=tuple(sorted(claim_ids)),
            supporting_event_ids=tuple(sorted(events_by_key[key])),
            trusted_event_ids=tuple(sorted(events_by_key[key])),
            recent_policy_event_ids=(
                tuple(sorted(events_by_key[key]))
                if _single_phase1_claim_field(
                    policy_claims_by_key[key],
                    "temporal_cue",
                    "unspecified",
                )
                == "recent"
                else ()
            ),
            observation_count=len(claim_ids),
            evidence_count=len(events_by_key[key]),
            distinct_days=1 if events_by_key[key] else 0,
            first_observed_at=1.0 if events_by_key[key] else None,
            last_observed_at=1.0 if events_by_key[key] else None,
            span_days=0.0,
            recency_days=0.0 if events_by_key[key] else None,
        )
        for key, claim_ids in claims_by_key.items()
    }


def _single_phase1_claim_field(claims, field_name, fallback):  # type: ignore[no-untyped-def]
    values = {
        str(getattr(raw, "value", raw) or "").strip().casefold()
        for claim in claims
        for raw in [getattr(claim, field_name, "")]
    }
    values.discard("")
    return next(iter(values)) if len(values) == 1 else fallback


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
    "session,user,source,owner,expected",
    [
        (" s1 ", "u1", "chrome", "owner", "session:s1"),
        (None, "u1", None, None, "user:u1"),
        ("  ", "u1", None, None, "user:u1"),
        (None, None, None, None, None),
        (None, "u1", "chrome_history", None, "source:chrome_history|user:u1"),
        (None, "u1", "netease_music", None, "source:netease_music|user:u1"),
        (None, "u2", "chrome_history", None, "source:chrome_history|user:u2"),
        (None, "u1", " chrome ", " owner ", "source:chrome|owner:owner|user:u1"),
    ],
)
def test_batch_keys_preserve_owner_and_source_isolation(session, user, source, owner, expected):
    from magi.memory.l2.models import build_l2_batch_bucket_key

    assert (
        build_l2_batch_bucket_key(
            session_id=session, user_id=user, source_type=source, owner_key=owner
        )
        == expected
    )


def test_microbatch_bucket_key_scopes_source_owner_to_user():
    from magi.memory.l2.models import build_l2_batch_bucket_key

    assert build_l2_batch_bucket_key(
        session_id=None,
        user_id="u1",
        source_type="chrome_history",
        owner_key="Default:github.com",
    ) == "source:chrome_history|owner:Default:github.com|user:u1"


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


@pytest.mark.asyncio
async def test_typed_contradiction_is_applied_and_reconciled_from_storage(tmp_path):
    from magi.memory.l2.models import ContradictionHint, L2TomAssertionWrite

    pipeline = await _build_pipeline(temp_dir=str(tmp_path))
    store = pipeline._cognition_store
    await store.upsert_assertion_candidate(
        L2TomAssertionWrite(
            entity_id="user:u1",
            entity_type="user",
            trait_name="preference.food",
            trait_value="sushi",
            confidence_score=0.9,
            evidence_events=["evt-1"],
            volatility_index=0.1,
            source_domain="conversation",
            inference_depth="semantic",
            validation_state="tentative",
            first_inferred_at=100.0,
            last_validated_at=100.0,
        ).to_dict()
    )
    before = (await store.list_tom_assertions(entity_id="user:u1"))[0]
    hint = ContradictionHint(
        target_record_id=before["assertion_id"],
        target_record_type="tom_trait_assertion",
        contradiction_kind="preference_reversal",
        confidence=0.65,
        evidence_text="I do not like sushi anymore",
        recommended_action="downgrade_confidence",
    )
    assert await store.apply_contradiction_hint(hint) is True
    after = (await store.list_tom_assertions(entity_id="user:u1"))[0]
    assert after["assertion_id"] == before["assertion_id"]
    assert after["validation_state"] == "contradicted"
    assert after["confidence_score"] < before["confidence_score"]
    outcomes = await store.reconcile_entity(
        entity_id="user:u1", entity_type="user", evidence_timestamps={"evt-1": 100.0}
    )
    assert len(outcomes) == 1
    result = outcomes[0].to_dict()
    assert {
        key: result[key]
        for key in [
            "source_assertion_id",
            "entity_id",
            "trait_name",
            "winning_value",
            "status",
            "evidence_event_ids",
        ]
    } == {
        "source_assertion_id": before["assertion_id"],
        "entity_id": "user:u1",
        "trait_name": "preference.food",
        "winning_value": "sushi",
        "status": "contradicted",
        "evidence_event_ids": ["evt-1"],
    }
    persisted = (await store.list_tom_assertions(entity_id="user:u1"))[0]
    assert result["confidence"] == persisted["confidence_score"]
    assert result["recommended_snapshot_field"] == "none"


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
            assert restored.session_id == "s1"
            assert restored.turn_id == "turn-1"
            assert restored.content == "hello"
            assert restored.author_type == "user"
            assert restored.content_type == "text"
        finally:
            await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_during_extraction", [False, True])
async def test_ingest_returns_before_extraction_and_shutdown_drains_owned_work(
    tmp_path, shutdown_during_extraction
):
    entered = asyncio.Event()
    release = asyncio.Event()
    response = json.dumps(
        {
            "entities": [],
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
                    "subject_ref": "user:self",
                    "predicate": "REAL_NAME",
                    "object_ref": "Asuka",
                    "object_type": "concept",
                    "fact_kind": "explicit_fact",
                    "temporal_cue": "stable",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "My real name is Asuka.",
                    "confidence": 0.95,
                    "supporting_event_ids": ["evt-gated"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "none"},
        }
    )

    class GatedAdapter(_FakeAdapter):
        async def _create_completion(self, **kwargs):
            entered.set()
            await release.wait()
            return await super()._create_completion(**kwargs)

    adapter = GatedAdapter(response)
    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memory"),
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_FakeScenarioPool(adapter),
    )
    await store.initialize()
    pipeline = store.l2_pipeline
    workers = [
        *pipeline._extract_workers,
        pipeline._flush_worker,
        pipeline._reconcile_worker,
        pipeline._snapshot_worker,
    ]
    ingest = asyncio.create_task(
        store.ingest_event(
            _make_memory_event(event_id="evt-gated", content="My real name is Asuka.")
        )
    )
    shutdown = None
    try:
        done, _ = await asyncio.wait({ingest}, timeout=3)
        assert ingest in done, "Ingestion waited for the blocked extraction provider"
        result = ingest.result()
        assert result["l1_written"] and result["l2_job_enqueued"]
        assert result["l2_relation_count"] == result["l2_assertion_count"] == 0
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert await store.l2.list_tom_assertions(entity_id="user:u1") == []
        if shutdown_during_extraction:
            shutdown = asyncio.create_task(pipeline.shutdown())
            done, _ = await asyncio.wait({shutdown}, timeout=0.05)
            assert not done, "Shutdown returned with extraction still blocked"
        release.set()
        if shutdown is not None:
            await asyncio.wait_for(shutdown, timeout=5)
        else:
            for queue in [
                pipeline._extract_queue,
                pipeline._reconcile_queue,
                pipeline._snapshot_queue,
            ]:
                await asyncio.wait_for(queue.join(), timeout=5)
            await pipeline.shutdown()
        assert all(worker.done() for worker in workers)
        for queue in [pipeline._extract_queue, pipeline._reconcile_queue, pipeline._snapshot_queue]:
            assert queue.empty()
            await asyncio.wait_for(queue.join(), timeout=1)
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        outcomes = await store.l2.list_claim_projection_outcomes(claim_id=claims[0]["claim_id"])
        projected = [row for row in outcomes if row["target_kind"] == "assertion"]
        assert len(projected) == 1 and projected[0]["outcome"] == "projected"
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert [
            (row["assertion_id"], row["trait_name"], row["trait_value"], row["evidence_events"])
            for row in assertions
        ] == [(projected[0]["target_id"], "identity.real_name", "Asuka", ["evt-gated"])]
        assert len(adapter.calls) == 1
        stats = store.get_l2_pipeline_stats()
        assert stats["extract_completed"] == 1 and stats["extract_failed"] == 0
        assert stats["is_running"] is False
    finally:
        release.set()
        await asyncio.gather(ingest, return_exceptions=True)
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
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


@pytest.mark.parametrize(
    "has_catalog,has_llm,error",
    [
        (False, False, "entity_catalog"),
        (False, True, "entity_catalog"),
        (True, False, "llm_service"),
        (True, True, None),
    ],
)
def test_pipeline_requires_both_collaborators(tmp_path, has_catalog, has_llm, error):
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.store import L2CognitionStore

    kwargs = {}
    if has_catalog:
        kwargs["entity_catalog"] = SimpleNamespace()
    if has_llm:
        kwargs["llm_service"] = SimpleNamespace()
    store = L2CognitionStore(db_path=str(tmp_path / "memory.db"))
    if error:
        with pytest.raises(ValueError, match=error):
            L2Pipeline(store, **kwargs)
    else:
        L2Pipeline(store, **kwargs)


@pytest.mark.parametrize(
    "interval,age,expected",
    [(90, 89, None), (90, 90, "interval_elapsed"), (30, 30, "interval_elapsed")],
)
def test_configured_batch_interval_controls_flush_boundary(monkeypatch, interval, age, expected):
    from magi.memory.l2.models import L2PendingBatchBucket

    monkeypatch.setattr("magi.memory.l2.pipeline.queueing.time.time", lambda: 1000.0)
    store = UnifiedMemoryStore(
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=interval,
        tuning=MemoryStoreTuning(),
    )
    bucket = L2PendingBatchBucket(
        bucket_key="session:s1", events=[{"event_id": "e1"}], created_at=1000.0 - age
    )
    assert store.l2_pipeline._flush_reason_for_bucket(bucket) == expected


@pytest.mark.asyncio
async def test_extract_queue_rejects_jobs_without_projection_leases():
    from magi.memory.l2.models import L2BatchJob

    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)
        job = L2BatchJob(
            job_id="unleased",
            bucket_key="event:unleased",
            events=[{"event_id": "unleased", "content": "ignored"}],
            flush_reason="direct",
            estimated_tokens=1,
        )

        with pytest.raises(ValueError, match="durable projection leases"):
            await pipeline._enqueue_extract_job(job)


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
    assert await service.resolve_entities_batch(items=[]) == {}
    assert adapter.calls == []
    results = await service.resolve_entities_batch(
        items=[
            L2BatchEntityResolutionItem(
                mention_key="0",
                mention=L2EntityResolutionMention(mention_text="Alice", entity_type="person"),
                candidate_entities=[
                    L2EntityCandidate(
                        entity_id="person:alice", canonical_name="Alice", entity_type="person"
                    )
                ],
            ),
            L2BatchEntityResolutionItem(
                mention_key="1",
                mention=L2EntityResolutionMention(mention_text="BobX", entity_type="person"),
                candidate_entities=[
                    L2EntityCandidate(
                        entity_id="person:bob", canonical_name="Bob", entity_type="person"
                    )
                ],
            ),
        ],
    )
    assert len(adapter.calls) == 1, "Should use a single LLM call for batch"
    assert results["0"].decision == "match"
    assert results["0"].matched_entity_id == "person:alice"
    assert results["1"].decision == "unresolved"


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
async def test_extract_worker_records_mentions_and_resolved_graph_edge():
    responses = [
        # Phase 1: extract entity
        json.dumps(
            {
                "entities": [
                    {
                        "referent_kind": "entity",
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
                        "assertion_mode": "asserted",
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

            for _ in range(400):
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
                    "referent_kind": "entity",
                    "surface": "DIIV",
                    "normalized_name": "DIIV",
                    "entity_type": "group",
                    "specificity": "concrete",
                    "resolved_id": "group:diiv",
                    "is_new": False,
                    "confidence": 0.95,
                },
                {
                    "referent_kind": "entity",
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
                    "assertion_mode": "asserted",
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

            for _ in range(400):
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
async def test_graph_projection_needs_no_wording_model_call(
    caplog,
):
    phase1_response = json.dumps(
        {
            "entities": [
                {
                    "referent_kind": "entity",
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
                    "assertion_mode": "asserted",
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
                    "supporting_event_ids": ["evt-phase2-degraded"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "found"},
        },
        ensure_ascii=False,
    )
    adapter = _FakeAdapter([phase1_response, "not-json", "still-not-json"])

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
            with caplog.at_level(logging.INFO, logger="magi.memory.l2.pipeline"):
                await store.ingest_event(
                    {
                        "id": "evt-phase2-degraded",
                        "type": EventTypes.USER_MESSAGE,
                        "timestamp": time.time(),
                        "source": "chat",
                        "level": EventLevel.INFO.value,
                        "data": {
                            "user_id": "u1",
                            "session_id": "s-phase2-degraded",
                            "content": "我好喜欢魔都",
                        },
                    }
                )

                for _ in range(400):
                    stats = store.get_l2_pipeline_stats()
                    if stats["extract_completed"] >= 1 or stats["extract_failed"] >= 1:
                        break
                    await asyncio.sleep(0.01)

            stats = store.get_l2_pipeline_stats()
            relationships = await store.l2.get_relationships(subject_id="user:u1")

            assert stats["extract_completed"] == 1
            assert stats["extract_failed"] == 0
            assert len(adapter.calls) == 1
            assert not any(
                "L2 optional summary generation failed" in record.getMessage()
                for record in caplog.records
            )
            assert any(
                edge["predicate"] == "LIKES"
                and edge["object_id"] == "place:shanghai"
                for edge in relationships
            )
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_goal_materialization_needs_no_wording_model_call():
    event_time = time.time()
    phase1_response = json.dumps(
        {
            "entities": [
                {
                    "referent_kind": "entity",
                    "surface": "去海边",
                    "normalized_name": "海边旅行",
                    "entity_type": "activity",
                    "specificity": "concrete",
                    "resolved_id": "activity:beach-trip",
                    "is_new": False,
                    "alias_signals": ["去海边"],
                    "confidence": 0.96,
                }
            ],
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
                    "subject_ref": "user:self",
                    "predicate": "PLANS_TO",
                    "object_ref": "去海边",
                    "object_type": "activity",
                    "fact_kind": "future_intent",
                    "temporal_cue": "unspecified",
                    "raw_time_expression": "",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "我计划去海边",
                    "evidence_mode": "direct",
                    "confidence": 0.96,
                    "supporting_event_ids": ["evt-goal-phase2-degraded"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "found"},
        },
        ensure_ascii=False,
    )
    adapter = _FakeAdapter([phase1_response, "not-json", "still-not-json"])

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
            assert store.l2_entity_catalog is not None
            await store.l2_entity_catalog.upsert_entity(
                entity_id="activity:beach-trip",
                canonical_name="海边旅行",
                entity_type="activity",
            )
            await store.l2_entity_catalog.add_alias(
                entity_id="activity:beach-trip",
                alias_text="去海边",
                confidence=0.98,
            )

            await store.ingest_event(
                {
                    "id": "evt-goal-phase2-degraded",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": event_time,
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-goal-phase2-degraded",
                        "content": "我计划去海边",
                    },
                }
            )

            for _ in range(400):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["assertions_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            assert len(assertions) == 1
            assert assertions[0]["trait_family"] == "goal_profile"
            assert assertions[0]["trait_name"] == "goal.intent"
            assert assertions[0]["trait_value"] == "去海边"
            assert assertions[0]["temporal_scope"] == "recent"
            assert assertions[0]["expires_at"] == pytest.approx(
                event_time + 30 * 24 * 60 * 60
            )

            claims = await store.l2.list_grounded_claims()
            outcomes = await store.l2.list_claim_projection_outcomes(
                claim_id=claims[0]["claim_id"]
            )
            assertion_outcomes = [
                outcome for outcome in outcomes if outcome["target_kind"] == "assertion"
            ]
            assert [outcome["outcome"] for outcome in assertion_outcomes] == ["projected"]
            assert store.get_l2_pipeline_stats()["extract_failed"] == 0
            assert len(adapter.calls) == 1
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_goal_text_is_materialized_without_creating_an_activity_entity():
    event_time = time.time()
    phase1_response = json.dumps(
        {
            "entities": [
                {
                    "referent_kind": "entity",
                    "surface": "海边",
                    "normalized_name": "海边",
                    "entity_type": "place",
                    "specificity": "concrete",
                    "resolved_id": None,
                    "is_new": True,
                    "alias_signals": [],
                    "confidence": 0.96,
                }
            ],
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
                    "subject_ref": "user:self",
                    "subject_type": "user",
                    "predicate": "PLANS_TO",
                    "object_ref": "去海边",
                    "object_type": "activity",
                    "fact_kind": "future_intent",
                    "temporal_cue": "unspecified",
                    "raw_time_expression": "",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "我计划去海边",
                    "evidence_mode": "direct",
                    "antecedent_event_ids": [],
                    "confidence": 0.96,
                    "supporting_event_ids": ["evt-materialized-goal"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "found"},
        },
        ensure_ascii=False,
    )
    adapter = _FakeAdapter([phase1_response])

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
            assert store.l2_entity_catalog is not None

            await store.ingest_event(
                {
                    "id": "evt-materialized-goal",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": event_time,
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s-materialized-goal",
                        "content": "我计划去海边",
                    },
                }
            )

            for _ in range(400):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["assertions_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            assert len(assertions) == 1
            assert assertions[0]["trait_name"] == "goal.intent"
            assert assertions[0]["trait_value"] == "去海边"

            claims = await store.l2.list_grounded_claims()
            assert len(claims) == 1
            refs = await store.l2.list_claim_entity_refs(
                claim_id=claims[0]["claim_id"]
            )
            object_refs = [ref for ref in refs if ref["ref_role"] == "object"]
            assert object_refs == []

            outcomes = await store.l2.list_claim_projection_outcomes(
                claim_id=claims[0]["claim_id"]
            )
            route_outcomes = [
                outcome for outcome in outcomes if outcome["target_kind"] == "route"
            ]
            assert [outcome["outcome"] for outcome in route_outcomes] == ["routed"]

            entities = await store.l2_entity_catalog.list_entities(limit=10)
            activity_entities = [
                entity
                for entity in entities
                if entity["entity_type"] == "activity"
                and entity["canonical_name"] == "去海边"
            ]
            assert activity_entities == []
            assert store.get_l2_pipeline_stats()["extract_failed"] == 0
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
                        "referent_kind": "entity",
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
                        "assertion_mode": "asserted",
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
            for _ in range(400):
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
async def test_resolved_mention_joins_durable_identity_and_source_evidence():
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
            entity_id = resolved_mentions[0].resolved_entity_id
            assert entity_id
            entities = await pipeline._entity_catalog.list_entities(limit=10)
            assert [
                (row["entity_id"], row["canonical_name"], row["entity_type"]) for row in entities
            ] == [(entity_id, "上海", "place")]
            mentions = await pipeline._entity_catalog.list_mentions(limit=10)
            assert [
                (row["resolved_entity_id"], row["mention_text"], row["evidence_event_ids"])
                for row in mentions
            ] == [(entity_id, "魔都", [event.event_id])]
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
            for _ in range(400):
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
            for _ in range(400):
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
            assert store.l2_pipeline is not None
            await store.l2_pipeline.shutdown()
            await store.l1.store(
                _make_memory_event(
                    event_id="evt-history-1",
                    session_id="s-old",
                    user_id="u1",
                    timestamp=time.time() - 60,
                    content="I call Shanghai Modu sometimes.",
                )
            )
            await store.l1.complete_cognition_handoff("evt-history-1")
            await store.l2_entity_catalog.upsert_entity(
                canonical_name="Shanghai",
                entity_type="place",
                entity_id="place:shanghai",
            )
            await store.l2_entity_catalog.add_alias(entity_id="place:shanghai", alias_text="Modu")
            assert await store.drain_l1_cognition_handoffs() == 0
            await store.l2_pipeline.start()

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
            for _ in range(400):
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
            assert store.l2_pipeline is not None
            await store.l2_pipeline.shutdown()
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
            await store.l1.complete_cognition_handoff("evt-history-early")
            await store.l1.complete_cognition_handoff("evt-history-late")
            await store.l2_entity_catalog.upsert_entity(
                canonical_name="Shanghai",
                entity_type="place",
                entity_id="place:shanghai",
            )
            await store.l2_entity_catalog.add_alias(entity_id="place:shanghai", alias_text="Modu")
            assert await store.drain_l1_cognition_handoffs() == 0
            await store.l2_pipeline.start()

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
            for _ in range(400):
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
async def test_source_events_without_session_do_not_use_user_recent_context():
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
                    content="This chat sentence must not leak into source context.",
                )
            )
            source_event = normalize_runtime_event(
                Event(
                    type="SOURCE_EVENT",
                    data={
                        "user_id": "u1",
                        "session_id": None,
                        "content": "Visited a page about DIIV",
                        "author_type": "source",
                        "content_type": "text",
                    },
                    source="chrome_history",
                    level=EventLevel.INFO,
                    correlation_id="corr-source-no-session",
                    timestamp=300.0,
                    event_id="evt-source-no-session",
                )
            )

            messages = await store.l2_pipeline._load_context_messages(source_event)

            assert messages == []
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_extract_worker_materializes_routed_assertions():
    responses = [
        # Phase 1: extract a fact claim about the current mood
        json.dumps(
            {
                "entities": [],
                "fact_claims": [
                    {
                        "assertion_mode": "asserted",
                        "subject_ref": "user:self",
                        "predicate": "FEELS",
                        "object_ref": "stressed",
                        "object_type": "concept",
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
        # Empty wording output must not suppress host materialization.
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

            for _ in range(400):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["assertions_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1") if store.l2 is not None else []

            assert len(assertions) == 1
            assert assertions[0]["trait_name"] == "mood"
            # Assertion may already have been reconciled (temporary trait → corroborated)
            assert assertions[0]["validation_state"] in ("tentative", "corroborated")
            assert assertions[0]["confidence_score"] == pytest.approx(0.94)
            assert store.get_l2_pipeline_stats()["reconcile_enqueued"] >= 1
            claims = await store.l2.list_grounded_claims()
            assert len(claims) == 1
            outcomes = await store.l2.list_claim_projection_outcomes(
                claim_id=claims[0]["claim_id"]
            )
            assertion_outcomes = [
                outcome for outcome in outcomes if outcome["target_kind"] == "assertion"
            ]
            assert len(assertion_outcomes) == 1
            assert assertion_outcomes[0]["outcome"] == "projected"
            assert assertion_outcomes[0]["target_id"] == assertions[0]["assertion_id"]
            assert assertion_outcomes[0]["attempt_key"] == claims[0]["origin_attempt_key"]
            assert (
                assertion_outcomes[0]["route_contract_version"]
                == ROUTE_CONTRACT_VERSION
            )
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_projection_preserves_unrelated_existing_assertions():
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
            # Seed already-processed evidence before background handoff recovery resumes.
            await store.l2_pipeline.shutdown()
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
                await store.l1.complete_cognition_handoff(event_id)
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
            assert await store.drain_l1_cognition_handoffs() == 0
            adapter._responses = [
                # Phase 1: extract a fact claim for host projection
                json.dumps(
                    {
                        "entities": [],
                        "fact_claims": [
                            {
                                "assertion_mode": "asserted",
                                "subject_ref": "user:self",
                                "predicate": "FEELS",
                                "object_ref": "calm",
                                "object_type": "concept",
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
            ]
            await store.l2_pipeline.start()

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

            for _ in range(400):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["reconcile_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            summaries = await store.l3.list_summaries(limit=10) if store.l3 is not None else []

            existing = next(
                item for item in assertions if item["assertion_id"] == existing_assertion_id
            )
            # The independent reconcile worker may normalize a stable row to
            # corroborated while this test waits. An unrelated Claim must
            # not contradict or supersede it.
            assert existing["validation_state"] in {"stable", "corroborated"}
            assert existing["confidence_score"] == pytest.approx(0.84)
            assert any(item["trait_value"] == "calm" for item in assertions)
            assert store.get_l2_pipeline_stats()["extract_completed"] == 1
            assert store.get_l2_pipeline_stats()["extract_failed"] == 0
            assert not any(item["summary_category"] == "conflict_resolution" for item in summaries)
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
@pytest.mark.parametrize("assistant_content_type", ["text", "tool_result"])
async def test_ingestion_extracts_user_evidence_and_blocks_assistant_evidence(
    tmp_path, assistant_content_type
):
    adapter = _FakeAdapter(
        json.dumps(
            {
                "entities": [],
                "fact_claims": [],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "none"},
            }
        )
    )
    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memory"),
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_FakeScenarioPool(adapter),
    )
    await store.initialize()
    try:
        user_result = await store.ingest_event(
            _make_memory_event(event_id="evt-user", content="Hello.")
        )
        assistant_result = await store.ingest_event(
            {
                "id": "evt-assistant",
                "type": EventTypes.AI_RESPONSE,
                "timestamp": time.time(),
                "source": "assistant",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "Hello back.",
                    "author_type": "assistant",
                    "content_type": assistant_content_type,
                },
            }
        )
        assert user_result["l1_written"] and user_result["l2_job_enqueued"]
        assert assistant_result["l1_written"] and not assistant_result["l2_job_enqueued"]
        await store.l2_pipeline.flush_pending_projection_jobs()
        await asyncio.wait_for(store.l2_pipeline._extract_queue.join(), timeout=5)
        stats = store.get_l2_pipeline_stats()
        assert stats["extract_by_evidence_class"] == {"user_self_report": 1}
        assert stats["extract_completed"] == 1 and stats["extract_failed"] == 0
        assert len(adapter.calls) == 1
        assert await store.l2.get_relationships(subject_id="user:u1") == []
        assert await store.l2.list_tom_assertions(entity_id="user:u1") == []
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_assistant_quote_does_not_add_new_evidence_weight():
    adapter = _FakeAdapter(
        [
            # Phase 1: extract a fact claim about the current mood
            json.dumps(
                {
                    "entities": [],
                    "fact_claims": [
                        {
                            "assertion_mode": "asserted",
                            "subject_ref": "user:self",
                            "predicate": "FEELS",
                            "object_ref": "stressed",
                            "object_type": "concept",
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

            for _ in range(400):
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
async def test_unified_extraction_normalizes_food_and_persists_dislikes_edge():
    adapter = _FakeAdapter(
        [
            # Phase 1: extract entity (dish → normalized to food) + fact claim
            json.dumps(
                {
                    "entities": [
                        {
                            "referent_kind": "entity",
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
                            "assertion_mode": "asserted",
                            "subject_ref": "user:u1",
                            "predicate": "DISLIKES",
                            "object_ref": "西湖醋鱼",
                            "object_type": "dish",
                            "fact_kind": "stable_preference",
                            "temporal_cue": "unspecified",
                            "polarity": "positive",
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
            json.dumps({"summaries": []}, ensure_ascii=False),
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

            for _ in range(400):
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
async def test_preference_claim_projects_graph_and_assertion_without_special_suppression():
    adapter = _FakeAdapter(
        [
            json.dumps(
                {
                    "entities": [
                        {
                            "referent_kind": "entity",
                            "surface": "西湖醋鱼",
                            "normalized_name": "西湖醋鱼",
                            "entity_type": "food",
                            "specificity": "concrete",
                            "resolved_id": None,
                            "is_new": True,
                            "alias_signals": [],
                            "confidence": 0.95,
                        }
                    ],
                    "fact_claims": [
                        {
                            "assertion_mode": "asserted",
                            "subject_ref": "user:self",
                            "subject_type": "user",
                            "predicate": "DISLIKES",
                            "object_ref": "西湖醋鱼",
                            "object_type": "food",
                            "fact_kind": "stable_preference",
                            "temporal_cue": "unspecified",
                            "polarity": "positive",
                            "specificity": "concrete",
                            "evidence_text": "但我讨厌吃西湖醋鱼",
                            "confidence": 0.88,
                            "supporting_event_ids": ["evt-unified-food-dup-1"],
                        }
                    ],
                    "resolved_refs": [],
                    "diagnostics": {"entity_status": "found"},
                },
                ensure_ascii=False,
            ),
            json.dumps({"summaries": []}, ensure_ascii=False),
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

            for _ in range(400):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assert store.l2 is not None
            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
            relationships = await store.l2.get_relationships(subject_id="user:u1")

            assert any(edge["predicate"] == "DISLIKES" for edge in relationships)
            assert len(assertions) == 1
            assert assertions[0]["trait_name"] == "preference.affinity"
            assert assertions[0]["trait_value"] == "dislike"
        finally:
            await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_assertion", [False, True])
async def test_contributed_profile_gates_real_assertion_projection_and_reports_counts(
    tmp_path, monkeypatch, allow_assertion
):
    from unittest.mock import Mock
    from magi.memory.l2.pipeline import workers

    log = Mock(wraps=workers.logger.info)
    monkeypatch.setattr(workers.logger, "info", log)
    event_id = "evt-profile"
    claims = []
    for predicate, object_ref, object_type, temporal_cue, evidence in [
        ("VISITED", "Shanghai", "place", "one_off", "Visited Shanghai today"),
        ("REAL_NAME", "Asuka", "concept", "stable", "My real name is Asuka"),
    ]:
        claims.append(
            {
                "assertion_mode": "asserted",
                "subject_ref": "user:self",
                "predicate": predicate,
                "object_ref": object_ref,
                "object_type": object_type,
                "fact_kind": "explicit_fact",
                "temporal_cue": temporal_cue,
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": evidence,
                "confidence": 0.95,
                "supporting_event_ids": [event_id],
            }
        )
    adapter = _FakeAdapter(
        json.dumps(
            {
                "entities": [
                    {
                        "referent_kind": "entity",
                        "surface": "Shanghai",
                        "normalized_name": "Shanghai",
                        "entity_type": "place",
                        "confidence": 0.95,
                    }
                ],
                "fact_claims": claims,
                "resolved_refs": [],
                "diagnostics": {"entity_status": "found"},
            }
        )
    )
    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memory"),
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_FakeScenarioPool(adapter),
        extraction_profile_provider=lambda: [
            {
                "profile_id": "source.test_profile",
                "source_types": ["test_source"],
                "allowed_predicates": ["VISITED"],
                "allow_assertion": allow_assertion,
            }
        ],
    )
    await store.initialize()
    try:
        event = _make_memory_event(
            event_id=event_id, content="My real name is Asuka. Visited Shanghai today."
        )
        event.source = "test_source"
        await store.ingest_event(event)
        await store.l2_pipeline.flush_pending_projection_jobs()
        await asyncio.wait_for(store.l2_pipeline._extract_queue.join(), timeout=5)
        stats = store.get_l2_pipeline_stats()
        assert stats["extract_completed"] == 1 and stats["extract_failed"] == 0
        assert len(adapter.calls) == 1
        relationships = await store.l2.get_relationships(subject_id="user:u1")
        assert [row["predicate"] for row in relationships] == ["VISITED"]
        entities = await store.l2_pipeline._entity_catalog.find_by_canonical_name("Shanghai")
        assert relationships[0]["object_id"] == entities[0]["entity_id"]
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert [
            (row["trait_name"], row["trait_value"], row["evidence_events"]) for row in assertions
        ] == ([("identity.real_name", "Asuka", [event_id])] if allow_assertion else [])
        assert len(await store.l2.list_grounded_claims()) == 2
        completed = [
            call.kwargs
            for call in log.call_args_list
            if call.args and call.args[0] == "L2 extract completed"
        ]
        assert len(completed) == 1
        assert {
            key: completed[0][key]
            for key in [
                "profile_id",
                "materialization_count",
                "rejected_graph_candidate_count",
                "relation_count",
                "assertion_count",
            ]
        } == {
            "profile_id": "source.test_profile",
            "materialization_count": 1,
            "rejected_graph_candidate_count": 1,
            "relation_count": 1,
            "assertion_count": int(allow_assertion),
        }
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
                        "natural_summary": "The user reports high stress.",
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
                        "natural_summary": "The user prefers concise communication.",
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
                for _ in range(400):
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
async def test_session_flush_queues_accumulated_entities_and_preserves_other_sessions(tmp_path):
    pipeline = await _build_pipeline(temp_dir=str(tmp_path), batch_flush_interval_seconds=9999)
    pipeline._accumulate_session_entities(None, ["user:ignored"])
    pipeline._accumulate_session_entities("s1", [])
    pipeline._accumulate_session_entities("s1", ["user:u1", "person:alice"])
    pipeline._accumulate_session_entities("s1", ["person:alice", "place:tokyo"])
    pipeline._accumulate_session_entities("s2", ["user:u2"])
    assert await pipeline.flush_session("missing") == []
    assert pipeline._reconcile_queue.empty() and pipeline._snapshot_queue.empty()
    expected = ["person:alice", "place:tokyo", "user:u1"]
    assert await pipeline.flush_session("s1") == expected
    assert pipeline._session_touched_entities == {"s2": {"user:u2"}}
    for queue in [pipeline._reconcile_queue, pipeline._snapshot_queue]:
        assert queue.get_nowait() == expected
        queue.task_done()
        assert queue.empty()
    assert await pipeline.flush_session("s1") == []
    assert pipeline._reconcile_queue.empty() and pipeline._snapshot_queue.empty()
    assert pipeline.get_statistics()["reconcile_enqueued"] == 1
    assert pipeline.get_statistics()["snapshot_enqueued"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("enable_l2", [False, True])
async def test_session_end_flushes_owned_entities_only_when_l2_enabled(tmp_path, enable_l2):
    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memory"),
        enable_l2=enable_l2,
    )
    await store.initialize()
    try:
        if enable_l2:
            store.l2_pipeline._accumulate_session_entities("s-end", ["user:u1"])
            store.l2_pipeline._accumulate_session_entities("s-other", ["user:u2"])
        assert await store.on_session_end("s-end") == (["user:u1"] if enable_l2 else [])
        assert await store.on_session_end("s-end") == []
        if enable_l2:
            assert store.l2_pipeline._session_touched_entities == {"s-other": {"user:u2"}}
            assert store.get_l2_pipeline_stats()["reconcile_enqueued"] == 1
            assert store.get_l2_pipeline_stats()["snapshot_enqueued"] == 1
    finally:
        await store.shutdown()


# ── Structured Entity Hints & Alias Validation ──


@pytest.mark.asyncio
@pytest.mark.parametrize("with_hints", [False, True])
async def test_structured_hints_preserve_existing_context_without_catalog_writes(
    tmp_path, with_hints
):
    from copy import deepcopy

    pipeline = await _build_pipeline(temp_dir=str(tmp_path))
    event = _make_memory_event(event_id="evt-hints", content="testing hints")
    event.metadata_json = (
        {
            "structured_entity_hints": [
                {
                    "mention_text": "GitHub",
                    "entity_type": "software",
                    "canonical_name_hint": "replace attempt",
                    "resolved_entity_id": "software:github",
                },
                {
                    "mention_text": "openai-python",
                    "entity_type": "media",
                    "canonical_name_hint": "openai-python",
                    "resolved_entity_id": "media:openai",
                },
            ]
        }
        if with_hints
        else {}
    )
    existing = [
        {
            "entity_id": "software:github",
            "canonical_name": "original GitHub",
            "entity_type": "software",
            "extra": "preserved",
        }
    ]
    expected = deepcopy(existing)
    if with_hints:
        expected.append(
            {
                "entity_id": "media:openai",
                "canonical_name": "openai-python",
                "entity_type": "media",
                "aliases": ["openai-python"],
                "hint_only": True,
            }
        )
    pipeline._inject_structured_entity_hints(event, existing)
    assert existing == expected
    assert await pipeline._entity_catalog.list_entities(limit=10) == []


@pytest.mark.asyncio
async def test_upsert_structured_graph_hints_uses_normalized_entity_id_for_aliases():
    """Aliases from graph hints must point at the catalog-normalized entity id."""
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline = await _build_pipeline(temp_dir=temp_dir)

        event = _make_memory_event(event_id="evt-graph-site-alias", content="Chrome 浏览 Google")
        event.metadata_json = {
            "structured_graph_hints": [
                {
                    "assertion_mode": "asserted",
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
        assert resolved["entity_id"] == "site:google.com"


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
                            "assertion_mode": "asserted",
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
                projection_leases=[],
            )

            assert count == 2
            assert {
                (candidate["object_id"], tuple(candidate["evidence_event_ids"]))
                for candidate in candidates
            } == {
                ("software:github", ("evt-structured-batch-1",)),
                ("software:docker", ("evt-structured-batch-2",)),
            }
        finally:
            await pipeline.shutdown()


@pytest.mark.asyncio
async def test_structured_graph_ref_preserves_its_explicit_identity():
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
                    "assertion_mode": "asserted",
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
            if "apple-ipad-pro" in str(entity.get("canonical_name") or "")
        ]
        assert len(ipad_entities) == 1
        catalog_name_index = await pipeline._build_catalog_name_index()
        object_id = pipeline._resolve_grounded_object_id(
            raw_object_ref="hardware:apple-ipad-pro-(11-inch)-(3rd-generation)",
            object_type="hardware", resolved_mentions=[], catalog_name_index=catalog_name_index,
        )
        assert object_id == "hardware:apple-ipad-pro-(11-inch)-(3rd-generation)"


@pytest.mark.asyncio
async def test_phase1_resolved_id_preserves_same_name_identities():
    """Same-name catalog rows must not override explicit resolved IDs."""
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

        await pipeline._entity_catalog.upsert_entity(
            entity_id="hardware:apple-ipad-pro-(11-inch)-(3rd-generation)",
            canonical_name=canonical_name, entity_type="hardware",
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

        assert resolved_mentions[0].resolved_entity_id == "hardware:apple-ipad-pro-(11-inch)-(3rd-generation)"
        entities = await pipeline._entity_catalog.list_entities(limit=10)
        ipad_entities = [
            entity
            for entity in entities
            if "apple-ipad-pro" in str(entity.get("canonical_name") or "")
        ]
        assert {entity["entity_id"] for entity in ipad_entities} == {canonical_id, "hardware:apple-ipad-pro-(11-inch)-(3rd-generation)"}


def test_inject_structured_graph_hints_adds_fact_claims():
    """Source-provided graph hints should be injected as deterministic Phase 1 fact claims."""
    from magi.memory.l2.models import L2Phase1Result
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_memory_event(event_id="evt-graph-hints", content="source supplied graph hints")
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "assertion_mode": "asserted",
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
async def test_extract_worker_persists_structured_graph_hints_without_model_edges():
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
                event_type="SOURCE_EVENT",
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
                            "assertion_mode": "asserted",
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

            for _ in range(400):
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
async def test_structured_and_model_graph_projections_preserve_independent_support(monkeypatch):
    """Retain structured evidence alongside a nonempty model projection without inflating support."""
    from magi.memory.event_contracts import (
        IngestTarget,
        MemoryDomain,
        MemoryEvent,
        RetentionClass,
        TomDepth,
    )

    from unittest.mock import AsyncMock

    hint_confidence = 0.85

    # Phase 1 must return content so pipeline proceeds past the "empty Phase 1"
    # early-return.  The external_observation policy (allow_assertion_write=True)
    # blocks the fast-track path, so Claim projection will run.
    responses = [
        json.dumps(
            {
                "entities": [
                    {
                        "referent_kind": "entity",
                        "surface": "Shanghai",
                        "normalized_name": "Shanghai",
                        "entity_type": "place",
                        "confidence": 0.95,
                    }
                ],
                "fact_claims": [
                    {
                        "assertion_mode": "asserted",
                        "predicate": "VISITED",
                        "subject_ref": "user:self",
                        "object_ref": "Shanghai",
                        "object_type": "place",
                        "fact_kind": "explicit_fact",
                        "temporal_cue": "one_off",
                        "polarity": "positive",
                        "specificity": "concrete",
                        "evidence_text": "Visited Shanghai today",
                        "confidence": 0.95,
                        "supporting_event_ids": ["evt-double-write-check-1"],
                    }
                ],
                "resolved_refs": [],
                "diagnostics": {"entity_status": "found"},
            }
        )
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
        project = AsyncMock(wraps=store.l2_pipeline._run_projection_flow)
        monkeypatch.setattr(store.l2_pipeline, "_run_projection_flow", project)
        try:
            event = MemoryEvent(
                event_id="evt-double-write-check-1",
                correlation_id="evt-double-write-check-1",
                timestamp=time.time(),
                created_at=time.time(),
                event_type="SOURCE_EVENT",
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
                content="GitHub profile page. Visited Shanghai today.",
                author_type="external",
                content_type="observation",
                importance_score=0.6,
                level=EventLevel.INFO.value,
                metadata_json={
                    "structured_graph_hints": [
                        {
                            "assertion_mode": "asserted",
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

            await store.l2_pipeline.flush_pending_projection_jobs()
            await asyncio.wait_for(store.l2_pipeline._extract_queue.join(), timeout=5)
            project.assert_awaited_once()
            stats = store.get_l2_pipeline_stats()
            assert stats["extract_completed"] == 1 and stats["extract_failed"] == 0
            assert len(await store.l2.list_grounded_claims()) == 1

            assert store.l2 is not None
            relationships = await store.l2.get_relationships(subject_id="user:u1")

            assert {row["predicate"] for row in relationships} == {"USES", "VISITED"}
            hint_edges = [
                e
                for e in relationships
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
                event_type="SOURCE_EVENT",
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
                            "assertion_mode": "asserted",
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

            for _ in range(400):
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
    event = _make_memory_event(event_id="evt-structured-pref", content="source hinted preference")
    event.source = "chrome_history"
    event.author_type = "external"
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "assertion_mode": "asserted",
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
                "assertion_mode": "asserted",
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
                "assertion_mode": "asserted",
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
                "assertion_mode": "asserted",
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


class TestExtractionInstructions:
    """Tests for extraction_instructions wiring into prompt rendering."""


    @pytest.mark.parametrize(
        "instructions", [None, "Use VIEWED for videos and INTERESTED_IN for topics."]
    )
    def test_prompt_includes_only_supplied_source_instructions(self, instructions):
        from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
        from magi.memory.l2.models import L2EventWindow

        prompt = render_phase1_extract_prompt(
            event_window=L2EventWindow(
                events=[{"event_id": "e1", "content": "test page", "timestamp": 1.0}]
            ),
            focal_subject={"subject_ref": "user:test", "subject_type": "user"},
            extraction_instructions=instructions,
        )
        assert ("## Source-Specific Instructions" in prompt) is (instructions is not None)
        if instructions:
            assert instructions in prompt


    @pytest.mark.parametrize(
        "overrides,expected",
        [({}, "original"), ({"extraction_instructions": "custom guidance"}, "custom guidance")],
    )
    def test_instruction_override_preserves_or_replaces_supplied_value(self, overrides, expected):
        from magi.memory.l2.extraction_profiles import ExtractionProfile, _apply_overrides

        profile = ExtractionProfile(profile_id="test", extraction_instructions="original")
        assert _apply_overrides(profile, overrides).extraction_instructions == expected


    @pytest.mark.asyncio
    async def test_contributed_profile_keeps_structured_types_out_of_model_entity_writes(
        self, tmp_path
    ):
        from magi.memory.l2.models import L2Phase1Result

        profile = _chrome_history_profile()
        pipeline = await _build_pipeline(temp_dir=str(tmp_path))
        event = _make_memory_event(event_id="evt-source-policy", content="GitHub profile page")
        phase1 = L2Phase1Result.from_dict(
            {
                "entities": [
                    {
                        "referent_kind": "entity",
                        "surface": "GitHub",
                        "entity_type": "software",
                        "confidence": 0.95,
                    },
                    {
                        "referent_kind": "entity",
                        "surface": "GitHub profile",
                        "entity_type": "presence",
                        "confidence": 0.95,
                    },
                ],
                "fact_claims": [],
                "resolved_refs": [],
            }
        )
        resolved = await pipeline._resolve_phase1_entities(
            event,
            phase1,
            evidence_event_ids=[event.event_id],
            allowed_entity_types=profile.allowed_entity_types,
        )
        assert [(item.normalized_surface, item.entity_type) for item in resolved] == [
            ("GitHub", "software")
        ]
        assert "presence" in profile.structured_allowed_entity_types
        assert "ON_PLATFORM" in profile.structured_allowed_predicates
        assert "ON_PLATFORM" not in profile.allowed_predicates


class TestEntityTypeFiltering:
    """Tests for allowed_entity_types filtering in _resolve_phase1_entities."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "allowed,expected",
        [
            (frozenset({"software"}), {("GitHub", "software")}),
            (None, {("GitHub", "software"), ("SQLite", "technology")}),
        ],
    )
    async def test_entity_type_policy_controls_catalog_writes(self, tmp_path, allowed, expected):
        from magi.memory.l2.models import L2Phase1Result

        pipeline = await _build_pipeline(temp_dir=str(tmp_path))
        phase1 = L2Phase1Result.from_dict(
            {
                "entities": [
                    {
                        "referent_kind": "entity",
                        "surface": "GitHub",
                        "entity_type": "software",
                        "confidence": 0.95,
                    },
                    {
                        "referent_kind": "entity",
                        "surface": "SQLite",
                        "entity_type": "technology",
                        "confidence": 0.9,
                    },
                ],
                "fact_claims": [],
                "resolved_refs": [],
            }
        )
        event = _make_memory_event(event_id="evt-filter", content="GitHub SQLite")
        resolved = await pipeline._resolve_phase1_entities(
            event, phase1, evidence_event_ids=[event.event_id], allowed_entity_types=allowed
        )
        assert {(item.normalized_surface, item.entity_type) for item in resolved} == expected
        entities = await pipeline._entity_catalog.list_entities(limit=10)
        assert {(row["canonical_name"], row["entity_type"]) for row in entities} == expected
        assert {item.resolved_entity_id for item in resolved} == {row["entity_id"] for row in entities}


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
                projection_leases=(),
                source_namespace=None,
                source_key=None,
            ):
                _ = projection_leases
                self.entities[entity_id] = {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                }
                self.entity_sources[entity_id] = tuple(source_event_ids)
                return entity_id

            async def add_alias(self, **_kwargs):
                return None

            async def record_mention(self, **_kwargs):
                return None

            async def filter_projection_source_event_ids(self, *, event_ids, **_kwargs):
                return tuple(event_ids)

            async def list_entities(self, *, limit=20, entity_ids=None):
                return [
                    entity for key, entity in self.entities.items()
                    if entity_ids is None or key in entity_ids
                ][:limit]

        pipeline = L2Pipeline.__new__(L2Pipeline)
        pipeline._entity_catalog = _EntityCatalog()
        pipeline._llm_service = None
        pipeline._entity_resolution_cache = {}

        phase1_payload = {
            "entities": [
                {"referent_kind": "entity", "surface": "哈基米", "normalized_name": "哈基米", "entity_type": "concept", "confidence": 0.95},
                {"referent_kind": "entity", "surface": "子涵", "normalized_name": "子涵", "entity_type": "concept", "confidence": 0.95},
                {"referent_kind": "entity", "surface": "GitHub", "normalized_name": "GitHub", "entity_type": "software", "confidence": 0.95},
            ],
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
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
                projection_leases=(),
                source_namespace=None,
                source_key=None,
            ):
                _ = projection_leases
                self.entities[entity_id] = {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                }
                return entity_id

            async def add_alias(self, **_kwargs):
                return None

            async def record_mention(self, **_kwargs):
                return None

            async def filter_projection_source_event_ids(self, *, event_ids, **_kwargs):
                return tuple(event_ids)

            async def list_entities(self, *, limit=20, entity_ids=None):
                return [
                    entity for key, entity in self.entities.items()
                    if entity_ids is None or key in entity_ids
                ][:limit]

        pipeline = L2Pipeline.__new__(L2Pipeline)
        pipeline._entity_catalog = _EntityCatalog()
        pipeline._llm_service = None
        pipeline._entity_resolution_cache = {}

        phase1_result = L2Phase1Result.from_dict({
            "entities": [
                {"referent_kind": "unknown", "surface": "他", "normalized_name": "德克萨斯", "entity_type": "person", "confidence": 0.95},
                {"referent_kind": "unknown", "surface": "那个", "normalized_name": "that one", "entity_type": "other", "confidence": 0.95},
                {"referent_kind": "unknown", "surface": "app", "normalized_name": "app", "entity_type": "software", "confidence": 0.95},
                {"referent_kind": "entity", "surface": "新专", "normalized_name": "新专", "entity_type": "media", "specificity": "underspecified", "confidence": 0.95},
                {"referent_kind": "entity", "surface": "GitHub", "normalized_name": "GitHub", "entity_type": "software", "confidence": 0.95},
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
        from .test_phase1_graph_projection import _routes, _sources

        prepared, rejected_outcomes = pipeline._project_phase1_graph_candidates(
            phase1_result=phase1_result,
            semantic_routes=_routes(phase1_result.fact_claims, {"claim:2": "product:magi"}),
            claim_sources=_sources(phase1_result.fact_claims, event),
            event=event,
            profile=profile,
            resolved_mentions=[],
            evidence_event_ids=["evt-open-predicate"],
            catalog_name_index={},
        )

        assert len(rejected_outcomes) == 1
        assert rejected_outcomes[0].reason_code == "unsupported_route"
        assert len(prepared) == 1
        assert prepared[0]["predicate"] == "MAINTAINS"
        assert prepared[0]["object_id"] == "product:magi"

    def test_profile_signal_claim_requires_current_user_evidence(self):
        from magi.memory.l2.models import L2BatchEvent, L2Phase1Result
        from magi.memory.l2.pipeline import L2Pipeline

        pipeline = L2Pipeline.__new__(L2Pipeline)
        phase1_result = L2Phase1Result.from_dict({
            "entities": [],
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
                    "subject_ref": "user:self",
                    "predicate": "REAL_NAME",
                    "object_ref": "苏眠",
                    "object_type": "person",
                    "fact_kind": "explicit_fact",
                    "evidence_text": "我是苏眠。",
                    "confidence": 0.8,
                },
                {
                    "assertion_mode": "asserted",
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


class TestSameNameEntityDedup:
    """Tests for same-name entity dedup in _resolve_entity_id."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "first_type,second_type,second_surface",
        [("software", "technology", "Claude AI"), ("person", "software", "Claude")],
    )
    async def test_same_name_stays_unresolved_without_equivalence_evidence(
        self, tmp_path, first_type, second_type, second_surface
    ):
        from magi.memory.l2.models import L2Phase1Result

        pipeline = await _build_pipeline(temp_dir=str(tmp_path))
        resolved = []
        for event_id, entity_type, surface in [
            ("evt-first", first_type, "Claude"),
            ("evt-second", second_type, second_surface),
        ]:
            phase1 = L2Phase1Result.from_dict(
                {
                    "entities": [
                        {
                            "referent_kind": "entity",
                            "surface": surface,
                            "entity_type": entity_type,
                            "confidence": 0.95,
                            "normalized_name": "Claude",
                        }
                    ],
                    "fact_claims": [],
                    "resolved_refs": [],
                }
            )
            event = _make_memory_event(event_id=event_id, content=surface)
            mentions = await pipeline._resolve_phase1_entities(
                event, phase1, evidence_event_ids=[event_id]
            )
            assert len(mentions) == 1
            resolved.append(mentions[0])
        assert resolved[0].resolved_entity_id
        assert resolved[1].resolved_entity_id is None
        entities = await pipeline._entity_catalog.list_entities(limit=10)
        assert [(row["entity_id"], row["entity_type"]) for row in entities] == [
            (resolved[0].resolved_entity_id, first_type)
        ]


class TestEntityResolutionCache:
    """Tests for session-level entity resolution memo cache."""

    @pytest.mark.asyncio
    async def test_cache_reuses_only_same_evidence_resolution(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock
        from magi.memory.l2.models import L2Phase1Result

        pipeline = await _build_pipeline(temp_dir=str(tmp_path))
        resolve = AsyncMock(wraps=pipeline._entity_catalog.find_resolution_candidates)
        monkeypatch.setattr(pipeline._entity_catalog, "find_resolution_candidates", resolve)

        async def resolve_fresh(event_id):
            phase1 = L2Phase1Result.from_dict(
                {
                    "entities": [
                        {
                            "referent_kind": "entity",
                            "surface": "Magi",
                            "entity_type": "software",
                            "confidence": 0.95,
                            "normalized_name": "Magi",
                        }
                    ],
                    "fact_claims": [],
                    "resolved_refs": [],
                }
            )
            event = _make_memory_event(event_id=event_id, content="test Magi")
            return await pipeline._resolve_phase1_entities(event, phase1, evidence_event_ids=[event_id])

        first = await resolve_fresh("evt-cache-1")
        assert len(first) == 1 and first[0].resolved_entity_id
        assert resolve.await_count == 1
        second = await resolve_fresh("evt-cache-1")
        assert [item.resolved_entity_id for item in second] == [first[0].resolved_entity_id]
        assert resolve.await_count == 1
        await resolve_fresh("evt-cache-2")
        assert resolve.await_count == 2

    @pytest.mark.asyncio
    async def test_degraded_resolution_does_not_seed_an_identity_cache(self):
        from magi.memory.l2.models import L2Phase1Result

        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = await _build_pipeline(temp_dir=temp_dir)

            # Create entity "Magi" as software
            phase1_sw = L2Phase1Result.from_dict({
                "entities": [
                    {"referent_kind": "entity", "surface": "Magi", "entity_type": "software", "confidence": 0.95,
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
                    {"referent_kind": "entity", "surface": "Magi", "entity_type": "person", "confidence": 0.95,
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
            assert ("evt-ct-1:0:magi", "software") in cache
            assert ("evt-ct-2:0:magi", "person") not in cache
            assert resolved2[0].resolved_entity_id is None


class TestGraphCatalogNameIndex:
    """Tests for graph object resolution using catalog name index."""

    @pytest.fixture
    def pipeline_cls(self):
        from magi.memory.l2.pipeline import L2Pipeline
        return L2Pipeline

    def test_catalog_index_hit(self, pipeline_cls):
        p = pipeline_cls.__new__(pipeline_cls)
        p._entity_catalog = None
        index = {"bilibili": "software:bilibili-hash"}
        result = p._resolve_grounded_object_id(
            raw_object_ref="bilibili",
            object_type="software",
            resolved_mentions=[],
            catalog_name_index=index,
        )
        assert result == "software:bilibili-hash"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reference,expected",
        [("bilibili", "software:bilibili"), ("missing", None), ("software:invented", None)],
    )
    async def test_graph_references_require_known_catalog_identity(self, tmp_path, reference, expected):
        pipeline = await _build_pipeline(temp_dir=str(tmp_path))
        await pipeline._entity_catalog.upsert_entity(
            entity_id="software:bilibili", canonical_name="bilibili", entity_type="software"
        )
        index = await pipeline._build_catalog_name_index()
        assert (
            pipeline._resolve_grounded_object_id(
                raw_object_ref=reference,
                object_type="software",
                resolved_mentions=[],
                catalog_name_index=index,
            )
            == expected
        )

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
        result = p._resolve_grounded_object_id(
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
                        "referent_kind": "entity",
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
            from .test_phase1_graph_projection import _routes, _sources

            prepared, rejected = pipeline._project_phase1_graph_candidates(
                phase1_result=L2Phase1Result(fact_claims=[invented_claim]),
                semantic_routes=_routes([invented_claim], {}),
                claim_sources=_sources([invented_claim], event),
                event=event,
                profile=_FakeProfile(),
                resolved_mentions=resolved_mentions,
                evidence_event_ids=[event.event_id],
                catalog_name_index=catalog_name_index,
            )

            assert prepared == []
            assert len(rejected) == 1
            assert rejected[0].outcome == "unresolved_entity"
            assert rejected[0].reason_code == "unresolved_object"

            surface_claim = L2Phase1FactClaim(
                claim_id="claim:1",
                subject_ref="user:u1",
                predicate="LISTENED",
                object_ref="归潮",
                object_type="media",
                confidence=1.0,
                supporting_event_ids=[event.event_id],
            )
            from .test_phase1_graph_projection import _routes, _sources

            prepared, rejected = pipeline._project_phase1_graph_candidates(
                phase1_result=L2Phase1Result(fact_claims=[surface_claim]),
                semantic_routes=_routes([surface_claim], {surface_claim.claim_id: resolved_mentions[0].resolved_entity_id}),
                claim_sources=_sources([surface_claim], event),
                event=event,
                profile=_FakeProfile(),
                resolved_mentions=resolved_mentions,
                evidence_event_ids=[event.event_id],
                catalog_name_index=catalog_name_index,
            )

            assert rejected == []
            assert prepared[0]["object_id"] == phase1_result.entities[0].resolved_id
            assert prepared[0]["object_id"] == resolved_mentions[0].resolved_entity_id


class TestCatalogFindByCanonicalName:
    """Tests for L2EntityCatalog.find_by_canonical_name."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Magi", {"software:magi", "person:magi"}),
            ("magi", {"software:magi", "person:magi"}),
            ("missing", set()),
        ],
    )
    async def test_name_lookup_matches_case_without_losing_homonyms(self, tmp_path, name, expected):
        from magi.memory.l2.entities.catalog import L2EntityCatalog

        db_path = str(tmp_path / "memory.db")
        _migrate_memory_shared_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.initialize()
        for entity_id, canonical_name, entity_type in [
            ("software:magi", "Magi", "software"),
            ("person:magi", "Magi", "person"),
            ("software:other", "Other", "software"),
        ]:
            await catalog.upsert_entity(
                entity_id=entity_id, canonical_name=canonical_name, entity_type=entity_type
            )
        rows = await catalog.find_by_canonical_name(name)
        assert {row["entity_id"] for row in rows} == expected
        assert {(row["entity_id"], row["entity_type"]) for row in rows} == {
            (entity_id, entity_id.split(":")[0]) for entity_id in expected
        }


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


# ── Episode formation hints: touched place ids + topic keys (Task 1.1) ──


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
                    "event_type": "SOURCE_EVENT",
                },
            ],
        )

    @pytest.mark.parametrize("mapped", [False, True])
    def test_episode_candidate_identity_and_metadata_follow_event_evidence(self, mapped):
        from magi.memory.l2.pipeline.event_entity_map import build_event_entity_map

        event_map = (
            build_event_entity_map(
                [
                    {"entity_id": "person:sarah", "evidence_event_ids": ["evt-chat"]},
                    {"entity_id": "software:v2ex", "evidence_event_ids": ["evt-browse"]},
                ]
            )
            if mapped
            else {}
        )
        jobs = self._worker()._build_episode_candidate_jobs(
            self._job(),
            result={
                "event_entity_map": event_map,
                "touched_place_ids": ["place:tokyo"],
                "touched_topic_keys": ["coding"],
            },
            touched_entity_ids=["software:v2ex", "person:sarah", "person:sarah"],
        )
        expected_entities = (
            [["person:sarah"], ["software:v2ex"]] if mapped else [["software:v2ex", "person:sarah"]] * 2
        )
        assert [
            (job.event_id, job.event_timestamp, job.entity_ids, job.place_ids, job.topic_keys)
            for job in jobs
        ] == [
            ("evt-chat", 100.0, expected_entities[0], ["place:tokyo"], ["coding"]),
            ("evt-browse", 120.0, expected_entities[1], ["place:tokyo"], ["coding"]),
        ]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [5, 6])
async def test_flush_worker_recovers_sqlite_contention_and_completes_durable_job(
    tmp_path, monkeypatch, error_code
):
    import sqlite3
    from magi.core.sqlite import sqlite_connection_async

    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memory"),
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_FakeScenarioPool(_FakeAdapter(
            '{"entities": [], "fact_claims": [], "resolved_refs": []}'
        )),
    )
    await store.initialize()
    original_claim = store.l2.claim_ready_projection_jobs
    attempts = 0

    async def contend_once(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = sqlite3.OperationalError("database is locked")
            error.sqlite_errorcode = error_code
            raise error
        return await original_claim(**kwargs)

    monkeypatch.setattr(store.l2, "claim_ready_projection_jobs", contend_once)
    try:
        result = await store.ingest_event(_make_memory_event(
            event_id="retry-after-lock", content="My real name is Asuka."
        ))
        assert result["l1_written"] and result["l2_job_enqueued"]
        async with asyncio.timeout(5):
            while True:
                worker = store.l2_pipeline._flush_worker
                if worker.done():
                    await worker
                    pytest.fail("Projection poller stopped before completing its durable job")
                async with sqlite_connection_async(store.memory_db_path) as db:
                    async with db.execute(
                        "SELECT status FROM l2_projection_jobs WHERE event_id = ?",
                        ("retry-after-lock",),
                    ) as cursor:
                        row = await cursor.fetchone()
                if row is not None and row[0] == "completed":
                    break
                await asyncio.sleep(0.02)
        assert attempts >= 2
        assert store.l2_pipeline.get_statistics()["extract_completed"] == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_flush_worker_does_not_hide_non_contention_database_errors(tmp_path, monkeypatch):
    import sqlite3

    pipeline = await _build_pipeline(temp_dir=str(tmp_path))
    error = sqlite3.OperationalError("no such table: l2_projection_jobs")
    error.sqlite_errorcode = sqlite3.SQLITE_ERROR

    async def broken_schema():
        raise error

    monkeypatch.setattr(pipeline, "_claim_pending_projection_jobs", broken_schema)
    pipeline._stats.is_running = True
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            await pipeline._run_flush_worker()
    finally:
        pipeline._stats.is_running = False
