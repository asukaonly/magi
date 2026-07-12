from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from magi.llm.concurrency_limiter import LLMRequestPriority


class _FakeUsagePublisher:
    def __init__(self) -> None:
        self.payloads = []

    async def publish(self, payload) -> None:  # type: ignore[no-untyped-def]
        self.payloads.append(payload)


class _FakeCompletionsClient:
    def __init__(self, response) -> None:  # type: ignore[no-untyped-def]
        self.response = response
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        return self.response


class _FakeOpenAIClient:
    def __init__(self, response) -> None:  # type: ignore[no-untyped-def]
        self.completions = _FakeCompletionsClient(response)
        self.chat = SimpleNamespace(completions=self.completions)


class _FakeAdapter:
    def __init__(
        self,
        response: str | list[object],
        *,
        provider_name: str = "openai",
        model_name: str = "gpt-test",
        usage: tuple[int, int, int] | None = None,
        usage_publisher: _FakeUsagePublisher | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        if isinstance(response, list):
            self._responses = list(response)
        else:
            self._responses = [response]
        usage_obj = (
            SimpleNamespace(
                prompt_tokens=usage[0],
                completion_tokens=usage[1],
                total_tokens=usage[2],
            )
            if usage is not None
            else None
        )
        message = SimpleNamespace(content=response, tool_calls=[], role="assistant")
        self._client = _FakeOpenAIClient(
            SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="stop")],
                usage=usage_obj,
            )
        )
        self._llm_usage_event_publisher = usage_publisher

        async def _create_completion(**kwargs):  # type: ignore[no-untyped-def]
            self._client.completions.kwargs = kwargs
            next_response = self._responses.pop(0) if self._responses else "{}"
            if isinstance(next_response, Exception):
                raise next_response
            message = SimpleNamespace(content=str(next_response), tool_calls=[], role="assistant")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="stop")],
                usage=usage_obj,
            )

        self._client.completions.create = _create_completion
        self._client.chat.completions.create = _create_completion


class _FakeScenarioPool:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self.adapter = adapter

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return self.adapter


class _ScenarioAwarePool:
    def __init__(self, adapters: dict[object, _FakeAdapter]) -> None:
        self.adapters = adapters

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return self.adapters[scenario]


class _SelectionAwarePool(_ScenarioAwarePool):
    def __init__(self, adapters: dict[object, _FakeAdapter], selections: dict[object, object]) -> None:
        super().__init__(adapters)
        self._selections = selections

    def get_selection(self, scenario):  # type: ignore[no-untyped-def]
        return self._selections.get(scenario)


class _RecordingLimiter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run_with_limit(self, key, operation, *, limit=None, priority=None):  # type: ignore[no-untyped-def]
        self.calls.append({"key": key, "limit": limit, "priority": priority})
        return await operation()


def _install_recording_limiter(monkeypatch: pytest.MonkeyPatch) -> _RecordingLimiter:
    limiter = _RecordingLimiter()
    monkeypatch.setattr(
        "magi.llm.provider_bridge.get_llm_concurrency_limiter",
        lambda: limiter,
    )
    return limiter


def _make_event_window(**overrides):  # type: ignore[no-untyped-def]
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary

    summary_payload = overrides.pop("summary", None)
    summary = summary_payload if isinstance(summary_payload, L2EventWindowSummary) else L2EventWindowSummary(**dict(summary_payload or {}))
    return L2EventWindow(summary=summary, **overrides)


def test_phase1_prompt_includes_entity_types_and_predicates():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT, render_phase1_extract_prompt

    prompt = render_phase1_extract_prompt(
        event_window=_make_event_window(event_ids=["evt-1"], texts=["Visited GitHub"]),
        focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
    )

    # Entity types and predicates are declared in the Phase 1 system prompt
    assert "product" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "VISITED" in PHASE1_EXTRACT_SYSTEM_PROMPT
    # User prompt uses Markdown
    assert "## Focal Subject" in prompt
    assert "user:u1" in prompt


def test_phase1_system_prompt_describes_food_mapping_and_none_status():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT

    assert "food" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "dish" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "drink" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "snack" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "ingredient" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert '"entity_status": "found|none"' in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_system_prompt_discourages_question_preferences():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT

    assert "question" in PHASE1_EXTRACT_SYSTEM_PROMPT.lower()
    assert "Do NOT extract preferences from questions" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Do NOT create preference facts for generic/category-level objects" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_includes_context_and_resolved_ref_schema():
    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT, render_phase1_extract_prompt

    prompt = render_phase1_extract_prompt(
        event_window=_make_event_window(
            event_ids=["evt-1"],
            texts=["我真的很烦这种天气耶"],
            context_texts=["杭州，阵雨，11度"],
        ),
        focal_subject={"entity_ref": "user:self", "entity_type": "user"},
        context_messages=[
            {"role": "user", "content": "杭州，阵雨，11度"},
        ],
    )

    assert "Recent Context" in prompt
    assert "杭州，阵雨，11度" in prompt
    assert "resolved_refs" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "reference_type" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase2_prompt_includes_deterministic_evidence_packet():
    from magi.memory.l2.models import (
        L2BatchEvent,
        L2EventWindow,
        L2EventWindowSummary,
        L2HistoryContext,
    )
    from magi.memory.l2.pipeline.evidence_packet import build_phase2_evidence_packet
    from magi.memory.l2.pipeline.prompts import render_phase2_integrate_prompt

    event_window = L2EventWindow(
        event_ids=["evt-current"],
        events=[
            L2BatchEvent(
                event_id="evt-current",
                content="Visited DeepSeek docs",
                timestamp=1_710_000_600.0,
                source="chrome_history",
                author_type="user",
            )
        ],
        history_contexts=[
            L2HistoryContext(
                event_id="evt-history",
                content="Visited DeepSeek API pricing",
                timestamp=1_710_000_000.0,
                matched_entity_id="product:deepseek",
                canonical_name="DeepSeek",
                match_source="alias_exact",
            )
        ],
        summary=L2EventWindowSummary(event_count=1, user_id="local_user"),
    )
    phase1_payload = {
        "entities": [
            {
                "surface": "DeepSeek",
                "entity_type": "product",
                "specificity": "concrete",
                "resolved_id": "product:deepseek",
                "is_new": False,
            }
        ],
        "fact_claims": [
            {
                "claim_id": "claim:deepseek",
                "subject_ref": "user:local_user",
                "predicate": "VIEWED",
                "object_ref": "DeepSeek",
                "object_type": "product",
                "confidence": 0.7,
                "evidence_text": "Visited DeepSeek docs",
            }
        ],
        "resolved_refs": [],
    }
    existing_edges = [
        {
            "triple_id": "edge-1",
            "subject_id": "user:local_user",
            "predicate": "VIEWED",
            "object_id": "product:deepseek",
            "object_type": "product",
            "source_type": "chrome_history",
            "observation_count": 4,
            "evidence_event_ids": ["a", "b", "c", "d"],
            "first_observed_at": 1_709_900_000.0,
            "last_observed_at": 1_710_000_500.0,
            "confidence": 0.74,
        }
    ]
    existing_assertions = [
        {
            "assertion_id": "assert-1",
            "trait_family": "preference_profile",
            "trait_name": "interest.deepseek",
            "trait_value": "DeepSeek",
            "validation_state": "tentative",
            "confidence_score": 0.44,
            "source_domain": "external_activity",
        }
    ]
    evidence_packet = build_phase2_evidence_packet(
        phase1_result=phase1_payload,
        existing_graph_edges=existing_edges,
        existing_assertions=existing_assertions,
        event_window=event_window,
    )

    prompt = render_phase2_integrate_prompt(
        phase1_result=phase1_payload,
        focal_subject={"entity_ref": "user:local_user", "entity_type": "user"},
        evidence_packet=evidence_packet,
    )

    assert "Deterministic Evidence Packet" in prompt
    assert "No LLM was used to gather this packet" in prompt
    assert "evt-history" in prompt
    assert "observed=4x" in prompt
    assert "single passive behavior" in prompt.lower()
    assert "interest.deepseek" in prompt


def test_phase2_evidence_packet_counts_history_support_for_candidates():
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary, L2HistoryContext
    from magi.memory.l2.phase1_models import L2Phase1Entity, L2Phase1FactClaim, L2Phase1Result
    from magi.memory.l2.pipeline.evidence_packet import build_phase2_evidence_packet

    phase1 = L2Phase1Result(
        entities=[
            L2Phase1Entity(
                surface="Docker",
                normalized_name="Docker",
                entity_type="software",
                resolved_id="software:docker",
            )
        ],
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:local_user",
                predicate="USES",
                object_ref="Docker",
                object_type="software",
            )
        ],
    )
    window = L2EventWindow(
        event_ids=["evt-now"],
        events=[],
        texts=[],
        history_contexts=[
            L2HistoryContext(
                event_id="evt-old-1",
                timestamp=1_710_000_000.0,
                content="Used Docker to inspect the local stack.",
                matched_entity_id="software:docker",
                matched_text="Docker",
                canonical_name="Docker",
            ),
            L2HistoryContext(
                event_id="evt-old-2",
                timestamp=1_710_100_000.0,
                content="Debugged containers with docker compose.",
                matched_entity_id="software:docker",
                matched_text="docker",
                canonical_name="Docker",
            ),
        ],
        summary=L2EventWindowSummary(event_count=1, history_context_count=2),
    )

    packet = build_phase2_evidence_packet(
        phase1_result=phase1,
        existing_graph_edges=[],
        existing_assertions=[],
        event_window=window,
    )

    assert packet["history_support"] == [
        {
            "id": "software:docker",
            "label": "Docker",
            "type": "software",
            "history_event_count": 2,
            "latest_timestamp": 1_710_100_000.0,
        }
    ]


def test_phase1_prompt_includes_batch_window_events():
    from magi.memory.l2.models import L2BatchEvent, L2EventWindow, L2EventWindowSummary
    from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt

    prompt = render_phase1_extract_prompt(
        event_window=L2EventWindow(
            event_ids=["evt-1", "evt-2"],
            events=[
                L2BatchEvent(event_id="evt-1", content="Alice likes ramen"),
                L2BatchEvent(event_id="evt-2", content="She eats it every week"),
            ],
            texts=["Alice likes ramen", "She eats it every week"],
            summary=L2EventWindowSummary(event_count=2, session_id="s-1", user_id="u-1"),
        ),
        focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
    )

    assert "evt-1" in prompt
    assert "evt-2" in prompt
    assert "Alice likes ramen" in prompt
    assert "She eats it every week" in prompt
    assert "## Messages to Analyze" in prompt


def test_integrate_phase2_passes_source_integration_instructions():
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary, L2Phase1Result

    adapter = _FakeAdapter(
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [],
            }
        )
    )
    service = L2LLMService(_FakeScenarioPool(adapter))

    asyncio.run(
        service.integrate_phase2(
            phase1_result=L2Phase1Result(),
            existing_graph_edges=[],
            existing_assertions=[],
            event_window=L2EventWindow(
                events=[{"event_id": "evt-song", "content": "played Track A", "timestamp": 1.0}],
                summary=L2EventWindowSummary(session_id="s1"),
            ),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
            phase2_instructions="For play history, emit preference_profile only after repeated plays.",
        )
    )

    user_prompt = adapter._client.completions.kwargs["messages"][-1]["content"]
    assert "## Source-Specific Integration Instructions" in user_prompt
    assert "preference_profile only after repeated plays" in user_prompt


def test_chat_source_l2_extraction_uses_medium_priority_limiter(
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary, L2Phase1Result

    limiter = _install_recording_limiter(monkeypatch)
    adapter = _FakeAdapter(
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [],
            }
        )
    )
    service = L2LLMService(_FakeScenarioPool(adapter))

    asyncio.run(
        service.integrate_phase2(
            phase1_result=L2Phase1Result(),
            existing_graph_edges=[],
            existing_assertions=[],
            event_window=L2EventWindow(
                events=[
                    {
                        "event_id": "evt-chat",
                        "content": "I like quiet cafes.",
                        "timestamp": 1.0,
                        "source": "chat",
                    }
                ],
                summary=L2EventWindowSummary(session_id="s1"),
            ),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )
    )

    assert limiter.calls[-1]["priority"] is LLMRequestPriority.MEDIUM


def test_non_chat_source_l2_extraction_keeps_low_priority_limiter(
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary, L2Phase1Result

    limiter = _install_recording_limiter(monkeypatch)
    adapter = _FakeAdapter(
        json.dumps(
            {
                "claim_assessments": [],
                "assertion_candidates": [],
            }
        )
    )
    service = L2LLMService(_FakeScenarioPool(adapter))

    asyncio.run(
        service.integrate_phase2(
            phase1_result=L2Phase1Result(),
            existing_graph_edges=[],
            existing_assertions=[],
            event_window=L2EventWindow(
                events=[
                    {
                        "event_id": "evt-song",
                        "content": "played Track A",
                        "timestamp": 1.0,
                        "source": "media",
                    }
                ],
                summary=L2EventWindowSummary(session_id="s1"),
            ),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )
    )

    assert limiter.calls[-1]["priority"] is LLMRequestPriority.LOW


def test_chat_source_entity_resolution_uses_medium_priority_limiter(
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import L2EntityCandidate, L2EntityResolutionMention

    limiter = _install_recording_limiter(monkeypatch)
    adapter = _FakeAdapter(
        json.dumps(
            {
                "resolution": {
                    "decision": "match",
                    "matched_entity_id": "place:cafe",
                    "matched_entity_name": "Quiet Cafe",
                    "confidence": 0.91,
                    "reason_tags": ["same_name"],
                    "should_merge": False,
                    "canonical_name_suggestion": None,
                }
            }
        )
    )
    service = L2LLMService(_FakeScenarioPool(adapter))

    asyncio.run(
        service.resolve_entity(
            mention=L2EntityResolutionMention(
                mention_text="Quiet Cafe",
                entity_type="place",
                context_text="I like Quiet Cafe.",
            ),
            candidate_entities=[
                L2EntityCandidate(
                    entity_id="place:cafe",
                    canonical_name="Quiet Cafe",
                    entity_type="place",
                )
            ],
            source="chat",
        )
    )

    assert limiter.calls[-1]["priority"] is LLMRequestPriority.MEDIUM


def test_conflict_arbitration_uses_core_scenario_adapter():
    from magi.config.models import LLMScenario
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        ContradictionHint,
        L2CandidateSet,
        L2ConflictArbitrationResult,
        L2ExistingRecord,
        L2EventWindow,
        L2EventWindowSummary,
        L2SourceEvent,
    )

    fast_adapter = _FakeAdapter("{}")
    deep_adapter = _FakeAdapter(
        json.dumps(
            {
                "decision": "keep_existing",
                "winning_record_ids": ["triple-1"],
                "superseded_record_ids": [],
                "reason": "Older evidence is stronger.",
            }
        ),
        model_name="gpt-deep",
    )
    service = L2LLMService(
        _ScenarioAwarePool(
            {
                LLMScenario.CONTEXT_DECIDER: fast_adapter,
                LLMScenario.CORE: deep_adapter,
            }
        )
    )

    result = asyncio.run(
        service.arbitrate_conflict(
            new_event_window=L2EventWindow(
                event_ids=["evt-1"],
                events=[],
                summary=L2EventWindowSummary(event_count=1, session_id="s1"),
            ),
            new_candidates=L2CandidateSet(graph_candidates=[], assertion_candidates=[]),
            contradiction_hints=[
                ContradictionHint(
                    target_record_id="triple-1",
                    target_record_type="knowledge_graph",
                    contradiction_kind="preference_reversal",
                    confidence=0.9,
                    evidence_text="I do not like sushi anymore.",
                    recommended_action="mark_deprecated",
                )
            ],
            existing_records=[L2ExistingRecord(record_id="triple-1", record_type="knowledge_graph")],
            source_events=[
                L2SourceEvent(
                    event_id="evt-1",
                    timestamp=1710000000.0,
                    source="chat",
                    event_type="UserMessage",
                    content="I do not like sushi anymore.",
                    author_type="user",
                )
            ],
        )
    )

    assert isinstance(result, L2ConflictArbitrationResult)
    assert result.decision == "keep_existing"
    assert fast_adapter._client.completions.kwargs == {}
    assert deep_adapter._client.completions.kwargs["messages"][0]["content"]


def test_entity_reconcile_returns_typed_outcomes():
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        L2ReconcileEntity,
        ReconciledTraitOutcome,
    )

    response = json.dumps(
        {
            "reconciled_traits": [
                {
                    "entity_id": "user:u1",
                    "entity_type": "user",
                    "trait_name": "stress_level",
                    "winning_value": "high",
                    "status": "corroborated",
                    "confidence": 0.82,
                    "evidence_event_ids": ["evt-1", "evt-2"],
                    "time_span_hours": 24.0,
                    "stability_kind": "temporary_state",
                    "recommended_snapshot_field": "current_stress_level",
                }
            ]
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    outcomes = asyncio.run(
        service.reconcile_entity_state(
            entity=L2ReconcileEntity(entity_id="user:u1", entity_type="user"),
            graph_facts=[],
            assertions=[],
            recent_events=[],
        )
    )

    assert len(outcomes) == 1
    assert isinstance(outcomes[0], ReconciledTraitOutcome)
    assert outcomes[0].trait_name == "stress_level"
    assert outcomes[0].confidence == 0.82
