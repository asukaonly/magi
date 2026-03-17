from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory import UnifiedMemoryStore
from magi.memory.event_contracts import normalize_runtime_event


class _FakeAdapter:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    async def generate(self, prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"prompt": prompt, **kwargs})
        return self._response


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
