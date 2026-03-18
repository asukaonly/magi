from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path

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

    async def generate(self, prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"prompt": prompt, **kwargs})
        if self._responses:
            return self._responses.pop(0)
        return self._fallback_response


class _FakeScenarioPool:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self.adapter = adapter
        self.requested_scenarios: list[object] = []

    def get(self, scenario):  # type: ignore[no-untyped-def]
        self.requested_scenarios.append(scenario)
        return self.adapter


def test_extraction_job_payload_can_be_created_from_event_id():
    from magi.memory.l2_models import L2EventExtractionJob

    job = L2EventExtractionJob.from_event_id("evt-1")

    assert job.job_type == "extract"
    assert job.event_ids == ["evt-1"]
    assert job.batch_key == "event:evt-1"


def test_reconcile_job_accepts_multiple_entities():
    from magi.memory.l2_models import L2EntityReconcileJob

    job = L2EntityReconcileJob(entity_ids=["user:u1", "place:shanghai"])

    assert job.job_type == "reconcile"
    assert job.entity_ids == ["place:shanghai", "user:u1"]
    assert job.batch_key == "entities:place:shanghai|user:u1"


@pytest.mark.parametrize(
    ("text", "user_id"),
    [
        ("", "u1"),
        ("   ", "u1"),
        ("hello", ""),
    ],
)
def test_manual_l2_event_request_rejects_blank_text_or_user(text: str, user_id: str):
    from magi.memory.l2_models import ManualL2EventRequest

    with pytest.raises(ValueError):
        ManualL2EventRequest(text=text, user_id=user_id)


def test_contradiction_hint_and_reconcile_outcome_serialize_deterministically():
    from magi.memory.l2_models import ContradictionHint, ReconciledTraitOutcome

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


def test_normalized_memory_event_captures_entity_focus_hint_from_payload():
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={"user_id": "u1", "message": "hello", "entity_focus_hint": "place:shanghai"},
        source="chat",
        level=EventLevel.INFO,
        correlation_id="corr-l2",
    )

    normalized = normalize_runtime_event(event)

    assert normalized.entity_focus_hint == "place:shanghai"


def test_normalized_memory_event_captures_extraction_profile_metadata():
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "user_id": "u1",
            "message": "hello",
            "structured_entity_hints": [
                {
                    "mention_text": "GitHub",
                    "entity_type": "software",
                    "canonical_name_hint": "GitHub",
                }
            ],
            "structured_graph_hints": [
                {
                    "subject_ref": "user:u1",
                    "predicate": "VISITED",
                    "object_ref": "product:github",
                    "object_type": "product",
                }
            ],
        },
        source="timeline",
        level=EventLevel.INFO,
        correlation_id="corr-l2-profile",
        metadata={"extraction_profile_id": "timeline.chrome_history"},
    )

    normalized = normalize_runtime_event(event)
    metadata = json.loads(normalized.metadata)

    assert normalized.extraction_profile_id == "timeline.chrome_history"
    assert normalized.structured_entity_hints == [
        {
            "mention_text": "GitHub",
            "entity_type": "software",
            "canonical_name_hint": "GitHub",
        }
    ]
    assert normalized.structured_graph_hints == [
        {
            "subject_ref": "user:u1",
            "predicate": "VISITED",
            "object_ref": "product:github",
            "object_type": "product",
        }
    ]
    assert metadata["extraction_profile_id"] == "timeline.chrome_history"


@pytest.mark.asyncio
async def test_l1_round_trip_preserves_extraction_profile_metadata():
    from magi.memory.l1_event_store import L1EventStore

    with tempfile.TemporaryDirectory() as temp_dir:
        store = L1EventStore(db_path=str(Path(temp_dir) / "l1_events.db"), vector_enabled=False)
        await store.initialize()
        try:
            normalized = normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "message": "hello",
                        "structured_entity_hints": [
                            {
                                "mention_text": "GitHub",
                                "entity_type": "software",
                            }
                        ],
                        "structured_graph_hints": [
                            {
                                "subject_ref": "user:u1",
                                "predicate": "VISITED",
                                "object_ref": "product:github",
                                "object_type": "product",
                            }
                        ],
                    },
                    source="timeline",
                    level=EventLevel.INFO,
                    correlation_id="corr-l2-profile-roundtrip",
                    metadata={"extraction_profile_id": "timeline.chrome_history"},
                )
            )

            await store.store(normalized)
            restored = await store.get_memory_event(normalized.event_id)

            assert restored is not None
            assert restored.extraction_profile_id == "timeline.chrome_history"
            assert restored.structured_entity_hints == [
                {
                    "mention_text": "GitHub",
                    "entity_type": "software",
                }
            ]
            assert restored.structured_graph_hints == [
                {
                    "subject_ref": "user:u1",
                    "predicate": "VISITED",
                    "object_ref": "product:github",
                    "object_type": "product",
                }
            ]
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
                        "message": "I have been stressed about work.",
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
                    "message": "I feel calm now.",
                },
            }
        )

        await store.shutdown()

        stats = store.get_l2_pipeline_stats()
        assert stats["is_running"] is False


def test_entity_mention_prompt_rendering_is_deterministic():
    from magi.memory.l2_llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    prompt = service.render_entity_mention_prompt(
        event_text="I like Shanghai.",
        context_texts=["I also call it Modu."],
    )

    assert "I like Shanghai." in prompt
    assert "I also call it Modu." in prompt
    assert prompt.count("Event text:") == 1


def test_contradiction_and_reconcile_prompt_rendering_is_deterministic():
    from magi.memory.l2_prompt_templates import (
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
async def test_invalid_json_from_llm_fails_closed():
    from magi.memory.l2_llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("not-json")))

    mentions = await service.extract_entity_mentions(event_text="I like Shanghai.", context_texts=[])

    assert mentions == []


@pytest.mark.asyncio
async def test_low_confidence_resolution_is_returned_as_unresolved():
    from magi.memory.l2_llm_service import L2LLMService

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
async def test_single_event_tom_candidates_are_capped_to_low_confidence():
    from magi.memory.l2_llm_service import L2LLMService

    response = json.dumps(
        {
            "assertion_candidates": [
                {
                    "entity_ref": "user:u1",
                    "entity_type": "user",
                    "trait_family": "stress",
                    "trait_name": "stress_level",
                    "trait_value": "high",
                    "inference_depth": "defensive_psychology",
                    "volatility_index": 0.7,
                    "confidence": 0.92,
                    "validation_state": "tentative",
                    "evidence_texts": ["I am stressed about work."],
                    "supporting_event_ids": ["evt-1"],
                    "notes": None,
                }
            ]
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    assertions = await service.extract_tom_assertions(
        event_window={"event_ids": ["evt-1"], "texts": ["I am stressed about work."]},
        focal_entities=[{"entity_id": "user:u1", "entity_type": "user"}],
    )

    assert assertions[0]["confidence"] == 0.3


@pytest.mark.asyncio
async def test_invalid_json_from_contradiction_and_reconcile_llm_fails_closed():
    from magi.memory.l2_llm_service import L2LLMService

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
                ]
            }
        ),
        json.dumps({"assertion_candidates": []}),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
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
                        "message": "我好喜欢魔都",
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
async def test_extract_worker_uses_recent_session_context_in_mention_prompt():
    from magi.memory.l2_prompt_templates import UNIFIED_EXTRACTION_SYSTEM_PROMPT

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
                        "message": "I call Shanghai Modu sometimes.",
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
                        "message": "I like Shanghai.",
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
async def test_extract_worker_persists_llm_tom_assertions():
    responses = [
        json.dumps({"mentions": []}),
        json.dumps(
            {
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
                ]
            }
        ),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
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
                        "message": "I am stressed about work today.",
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
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            assert store.l2 is not None
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
                json.dumps({"mentions": []}),
                json.dumps({"assertion_candidates": []}),
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
                        "message": "I feel calm and relaxed now.",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1:
                    break
                await asyncio.sleep(0.01)

            assertions = await store.l2.list_tom_assertions(entity_id="user:u1")

            assert assertions[0]["assertion_id"] == existing_assertion_id
            assert assertions[0]["validation_state"] == "contradicted"
            assert assertions[0]["confidence_score"] < 0.84
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
                        "response": "You might enjoy Hangzhou weather this week.",
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
                        "response": "According to the weather tool, Hangzhou is 17C right now.",
                    },
                    "metadata": {
                        "tool_name": "weather_api",
                        "tool_call_id": "call-weather-1",
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
            json.dumps({"mentions": []}),
            json.dumps(
                {
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
                    ]
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
                        "message": "I am stressed about work today.",
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
                        "response": "You mentioned earlier that you feel stressed about work today.",
                    },
                    "metadata": {
                        "derived_from_event_ids": ["evt-user-stress-1"],
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
                        "message": "I like sushi.",
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
                        "response": "You might want sushi for dinner.",
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
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            with caplog.at_level(logging.INFO, logger="magi.memory.l2_pipeline"):
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
                            "response": "You might enjoy sushi tonight.",
                        },
                    }
                )

                for _ in range(50):
                    stats = store.get_l2_pipeline_stats()
                    if stats["extract_completed"] >= 1:
                        break
                    await asyncio.sleep(0.01)

            messages = [record.getMessage() for record in caplog.records if record.name == "magi.memory.l2_pipeline"]
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
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            with caplog.at_level(logging.INFO, logger="magi.memory.l2_pipeline"):
                await store.ingest_event(
                    {
                        "id": "evt-log-unified-1",
                        "type": EventTypes.USER_MESSAGE,
                        "timestamp": time.time(),
                        "source": "timeline",
                        "level": EventLevel.INFO.value,
                        "data": {
                            "user_id": "u1",
                            "session_id": "s1",
                            "message": "Visited GitHub today",
                        },
                        "metadata": {
                            "extraction_profile_id": "timeline.chrome_history",
                        },
                    }
                )

                for _ in range(50):
                    stats = store.get_l2_pipeline_stats()
                    if stats["extract_completed"] >= 1:
                        break
                    await asyncio.sleep(0.01)

            messages = [record.getMessage() for record in caplog.records if record.name == "magi.memory.l2_pipeline"]
            assert any("L2 extract completed" in message for message in messages)
            assert any("timeline.chrome_history" in message for message in messages)
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
                        "message": "但我讨厌吃西湖醋鱼",
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
                        "message": "但我讨厌吃西湖醋鱼",
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
                        "message": "但我讨厌吃西湖醋鱼",
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
async def test_unified_extraction_respects_chrome_history_profile_restrictions():
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
                        "supporting_event_ids": ["evt-chrome-1"],
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
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-chrome-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "timeline",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "message": "Visited GitHub today",
                    },
                    "metadata": {
                        "extraction_profile_id": "timeline.chrome_history",
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
async def test_structured_entity_hints_bypass_llm_mention_extraction():
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [],
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
                    }
                ],
                "assertion_candidates": [],
                "diagnostics": {"entity_status": "none"},
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
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-structured-hint-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "timeline",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "message": "Visited GitHub today",
                        "structured_entity_hints": [
                            {
                                "mention_text": "GitHub",
                                "normalized_surface": "github",
                                "entity_type": "product",
                                "canonical_name_hint": "GitHub",
                                "confidence": 0.95,
                            }
                        ],
                    },
                    "metadata": {
                        "extraction_profile_id": "timeline.chrome_history",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []
            mentions = await store.l2_entity_catalog.list_mentions() if store.l2_entity_catalog is not None else []

            assert [item["predicate"] for item in relationships] == ["VISITED"]
            assert mentions[0]["mention_text"] == "GitHub"
            assert len(adapter.calls) == 1
            prompt = str(adapter.calls[0]["prompt"])
            assert '"allowed_entity_types": [' in prompt
            assert '"product"' in prompt
        finally:
            await store.shutdown()


@pytest.mark.asyncio
async def test_structured_graph_hints_are_validated_before_persistence():
    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [],
                "graph_candidates": [],
                "assertion_candidates": [],
                "diagnostics": {"entity_status": "none"},
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
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            await store.ingest_event(
                {
                    "id": "evt-structured-graph-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "timeline",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "message": "Visited GitHub today",
                        "structured_entity_hints": [
                            {
                                "mention_text": "GitHub",
                                "normalized_surface": "github",
                                "entity_type": "product",
                                "canonical_name_hint": "GitHub",
                                "confidence": 0.95,
                            }
                        ],
                        "structured_graph_hints": [
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
                    },
                    "metadata": {
                        "extraction_profile_id": "timeline.chrome_history",
                    },
                }
            )

            for _ in range(50):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] >= 1 and stats["relations_written"] >= 1:
                    break
                await asyncio.sleep(0.01)

            relationships = await store.l2.get_relationships(subject_id="user:u1") if store.l2 is not None else []

            assert [item["predicate"] for item in relationships] == ["VISITED"]
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
        )
        await store.initialize()
        try:
            assert store.l1 is not None
            assert store.l2 is not None
            assert store.l2_pipeline is not None

            timestamps = [1710000000.0, 1710090000.0, 1710185000.0]
            with caplog.at_level(logging.INFO, logger="magi.memory.l2_pipeline"), caplog.at_level(
                logging.INFO, logger="magi.memory.l2_cognition_store"
            ):
                for index, ts in enumerate(timestamps, start=1):
                    memory_event = normalize_runtime_event(
                        Event(
                            type=EventTypes.USER_MESSAGE,
                            data={"user_id": "u1", "session_id": "s1", "message": f"Stress signal {index}"},
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

            assert assertions[0]["validation_state"] == "stable"
            assert assertions[0]["confidence_score"] >= 0.82
            assert snapshot is not None
            assert snapshot["core_traits"]["stress_level"] == "high"
            assert snapshot["current_stress_level"] == 1.0
            messages = [record.getMessage() for record in caplog.records]
            assert any("L2 reconcile completed" in message for message in messages)
            assert any("L2 snapshot completed" in message for message in messages)
            assert any("L2 snapshot refreshed" in message for message in messages)
        finally:
            await store.shutdown()
