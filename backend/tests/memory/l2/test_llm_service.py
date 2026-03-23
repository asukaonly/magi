from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


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


def _make_event_window(**overrides):  # type: ignore[no-untyped-def]
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary

    summary_payload = overrides.pop("summary", None)
    summary = summary_payload if isinstance(summary_payload, L2EventWindowSummary) else L2EventWindowSummary(**dict(summary_payload or {}))
    return L2EventWindow(summary=summary, **overrides)


def test_unified_prompt_only_includes_profile_allowed_entity_types():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    profile = ExtractionProfile(
        profile_id="timeline.chrome_history",
        allowed_entity_types=frozenset({"product"}),
        allowed_predicates=frozenset({"VISITED"}),
        allowed_assertion_families=frozenset(),
        allow_assertion=False,
    )

    prompt = service.render_unified_extraction_prompt(
        event_window=_make_event_window(event_ids=["evt-1"], texts=["Visited GitHub"]),
        profile=profile,
        focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
    )
    payload = json.loads(prompt.split("\n\n", maxsplit=1)[1])

    assert payload["allowed_entity_types"] == ["product"]
    assert payload["allowed_predicates"] == ["VISITED"]


def test_unified_prompt_describes_food_mapping_and_none_status():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    profile = ExtractionProfile(profile_id="chat.user_message")

    prompt = service.render_unified_extraction_prompt(
        event_window=_make_event_window(event_ids=["evt-1"], texts=["I hate West Lake vinegar fish"]),
        profile=profile,
        focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
    )

    assert "Specific dishes, drinks, snacks, and ingredients must use `food`." in prompt
    assert '"entity_status": "found|none"' in prompt


def test_unified_prompt_includes_context_bundle_and_resolved_ref_schema():
    from magi.memory.l2.context_bundle import ContextBundle, ContextEntity
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    profile = ExtractionProfile(profile_id="chat.user_message")

    prompt = service.render_unified_extraction_prompt(
        event_window=_make_event_window(event_ids=["evt-1"], texts=["我真的很烦这种天气耶"]),
        profile=profile,
        focal_subject={"entity_ref": "user:self", "entity_type": "user"},
        context_bundle=ContextBundle(
            live_context_entities=[
                ContextEntity(
                    context_id="weather_state:hangzhou-rainy-11c",
                    kind="weather_state",
                    summary="杭州，阵雨，11度",
                )
            ]
        ),
    )
    payload = json.loads(prompt.split("\n\n", maxsplit=1)[1])

    assert payload["context_bundle"]["live_context_entities"][0]["context_id"] == "weather_state:hangzhou-rainy-11c"
    assert payload["output_schema"]["resolved_context_refs"][0]["reference_type"] == (
        "context_entity|canonical_entity|self_actor|unresolved"
    )


def test_unified_prompt_includes_batch_window_rules_and_summary():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import L2EventWindow, L2EventWindowSummary

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    profile = ExtractionProfile(profile_id="chat.user_message")

    prompt = service.render_unified_extraction_prompt(
        event_window=L2EventWindow(
            event_ids=["evt-1", "evt-2"],
            events=[
                {"event_id": "evt-1", "content": "Alice likes ramen"},
                {"event_id": "evt-2", "content": "She eats it every week"},
            ],
            texts=["Alice likes ramen", "She eats it every week"],
            summary=L2EventWindowSummary(event_count=2, session_id="s-1", user_id="u-1"),
        ),
        profile=profile,
        focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
    )
    payload = json.loads(prompt.split("\n\n", maxsplit=1)[1])

    assert payload["event_window"]["summary"]["event_count"] == 2
    assert any(
        "Use batch-level context across the supplied event window" in rule for rule in payload["rules"]
    )


def test_conflict_arbitration_uses_core_scenario_adapter():
    from magi.config.models import LLMScenario
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import (
        ContradictionHint,
        L2CandidateSet,
        L2ConflictArbitrationResult,
        L2EventWindow,
        L2EventWindowSummary,
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
            existing_records=[{"record_id": "triple-1"}],
            source_events=[],
        )
    )

    assert isinstance(result, L2ConflictArbitrationResult)
    assert result.decision == "keep_existing"
    assert fast_adapter._client.completions.kwargs == {}
    assert deep_adapter._client.completions.kwargs["messages"][0]["content"]


def test_unified_extraction_uses_scenario_max_output_tokens_when_configured():
    from magi.config.models import LLMScenario
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    adapter = _FakeAdapter(
        json.dumps(
            {
                "mentions": [],
                "resolved_context_refs": [],
                "graph_candidates": [],
                "assertion_candidates": [],
                "diagnostics": {"entity_status": "none"},
            }
        )
    )
    selection = SimpleNamespace(limits=SimpleNamespace(max_output_tokens=2048))
    service = L2LLMService(
        _SelectionAwarePool(
            {LLMScenario.CONTEXT_DECIDER: adapter},
            {LLMScenario.CONTEXT_DECIDER: selection},
        )
    )

    asyncio.run(
        service.extract_unified_candidates(
            event_window=_make_event_window(event_ids=["evt-1"], events=[], texts=["hello"], summary={}),
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )
    )

    assert adapter._client.completions.kwargs["max_tokens"] == 2048


def test_unified_extraction_parses_mentions_graph_and_assertions():
    from magi.memory.l2.context_bundle import ResolvedContextRef
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import L2EventWindow, L2UnifiedExtractionResult

    response = json.dumps(
        {
            "mentions": [{"mention_text": "西湖醋鱼", "entity_type": "dish"}],
            "resolved_context_refs": [{"surface": "我", "reference_type": "self_actor", "resolved_ref": "user:self"}],
            "graph_candidates": [{"predicate": "DISLIKES", "object_type": "dish"}],
            "assertion_candidates": [{"trait_family": "taste_profile", "confidence": 0.8}],
            "diagnostics": {"entity_status": "found"},
        },
        ensure_ascii=False,
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    result = asyncio.run(
        service.extract_unified_candidates(
            event_window=L2EventWindow(event_ids=["evt-1"], texts=["但我讨厌吃西湖醋鱼"]),
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
            context_bundle=None,
        )
    )

    assert isinstance(result, L2UnifiedExtractionResult)
    assert result.mentions == [{"mention_text": "西湖醋鱼", "entity_type": "dish"}]
    assert isinstance(result.resolved_context_refs[0], ResolvedContextRef)
    assert result.resolved_context_refs[0].to_dict() == {
        "surface": "我",
        "reference_type": "self_actor",
        "resolved_ref": "user:self",
        "resolved_kind": "",
        "confidence": 0.0,
        "evidence_text": "",
    }
    assert result.graph_candidates == [{"predicate": "DISLIKES", "object_type": "dish"}]
    assert result.assertion_candidates[0]["trait_family"] == "taste_profile"
    assert result.assertion_candidates[0]["confidence"] == 0.3
    assert result.diagnostics == {"entity_status": "found"}


def test_contradiction_hint_detection_returns_typed_hints():
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.models import ContradictionHint

    response = json.dumps(
        {
            "contradiction_hints": [
                {
                    "target_record_id": "triple-1",
                    "target_record_type": "knowledge_graph",
                    "contradiction_kind": "preference_reversal",
                    "confidence": 0.91,
                    "evidence_text": "I do not like sushi anymore.",
                    "recommended_action": "mark_deprecated",
                }
            ]
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    hints = asyncio.run(
        service.detect_contradiction_hints(
            new_event={"event_id": "evt-1", "content": "I do not like sushi anymore."},
            existing_records=[{"record_id": "triple-1", "record_type": "knowledge_graph"}],
        )
    )

    assert len(hints) == 1
    assert isinstance(hints[0], ContradictionHint)
    assert hints[0].target_record_id == "triple-1"
    assert hints[0].recommended_action == "mark_deprecated"


def test_unified_extraction_fails_closed_on_invalid_json():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("not-json")))

    result = asyncio.run(
        service.extract_unified_candidates(
            event_window=_make_event_window(event_ids=["evt-1"], texts=["hello"]),
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
            context_bundle=None,
        )
    )

    assert result.to_dict() == {
        "mentions": [],
        "resolved_context_refs": [],
        "graph_candidates": [],
        "assertion_candidates": [],
        "diagnostics": {"entity_status": "none"},
    }


def test_unified_extraction_logs_timing():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    response = json.dumps(
        {
            "mentions": [{"mention_text": "Rust", "entity_type": "technology"}],
            "graph_candidates": [],
            "assertion_candidates": [],
            "diagnostics": {"entity_status": "found"},
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    with patch("magi.memory.l2.llm_service.logger.info") as mock_info:
        result = asyncio.run(
            service.extract_unified_candidates(
                event_window=_make_event_window(event_ids=["evt-1"], texts=["I like Rust"]),
                profile=ExtractionProfile(profile_id="chat.user_message"),
                focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
                context_bundle=None,
            )
        )

    assert result.diagnostics == {"entity_status": "found"}
    assert [call.args[0] for call in mock_info.call_args_list] == [
        "L2 unified extraction started",
        "L2 LLM call completed",
        "L2 unified extraction completed",
    ]
    llm_completed_extras = mock_info.call_args_list[1].kwargs
    extras = mock_info.call_args_list[2].kwargs
    assert llm_completed_extras["duration_ms"] >= 0.0
    assert extras["profile_id"] == "chat.user_message"
    assert extras["mention_count"] == 1
    assert extras["duration_ms"] >= 0.0


def test_unified_extraction_uses_provider_bridge_and_logs_usage():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    response = json.dumps(
        {
            "mentions": [],
            "graph_candidates": [],
            "assertion_candidates": [],
            "diagnostics": {"entity_status": "none"},
        }
    )
    adapter = _FakeAdapter(response, provider_name="glm", model_name="glm-4.5", usage=(21, 9, 30))
    service = L2LLMService(_FakeScenarioPool(adapter))

    with patch("magi.memory.l2.llm_service.logger.info") as mock_info:
        asyncio.run(
            service.extract_unified_candidates(
                event_window=_make_event_window(event_ids=["evt-1"], texts=["hello"]),
                profile=ExtractionProfile(profile_id="chat.user_message"),
                focal_subject={"entity_ref": "user:self", "entity_type": "user"},
                context_bundle=None,
            )
        )

    create_kwargs = adapter._client.completions.kwargs
    assert create_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert create_kwargs["response_format"] == {"type": "json_object"}
    assert [call.args[0] for call in mock_info.call_args_list] == [
        "L2 unified extraction started",
        "L2 LLM call completed",
        "L2 unified extraction completed",
    ]
    started_extra = mock_info.call_args_list[0].kwargs
    llm_completed_extra = mock_info.call_args_list[1].kwargs
    completed_extra = mock_info.call_args_list[2].kwargs
    assert started_extra["event_ids"] == ["evt-1"]
    assert started_extra["profile_id"] == "chat.user_message"
    assert llm_completed_extra["request_kind"] == "memory:l2_unified_extraction"
    assert llm_completed_extra["provider"] == "glm"
    assert llm_completed_extra["model"] == "glm-4.5"
    assert llm_completed_extra["duration_ms"] >= 0.0
    assert llm_completed_extra["usage_available"] is True
    assert llm_completed_extra["prompt_tokens"] == 21
    assert llm_completed_extra["completion_tokens"] == 9
    assert llm_completed_extra["total_tokens"] == 30
    assert completed_extra["event_ids"] == ["evt-1"]
    assert completed_extra["profile_id"] == "chat.user_message"


def test_unified_extraction_logs_batch_session_context():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    response = json.dumps(
        {
            "mentions": [],
            "graph_candidates": [],
            "assertion_candidates": [],
            "diagnostics": {"entity_status": "none"},
        }
    )
    adapter = _FakeAdapter(response)
    service = L2LLMService(_FakeScenarioPool(adapter))

    with patch("magi.memory.l2.llm_service.logger.info") as mock_info:
        asyncio.run(
            service.extract_unified_candidates(
                event_window=_make_event_window(
                    event_ids=["evt-1", "evt-2"],
                    events=[
                        {"event_id": "evt-1", "session_id": "sess-1"},
                        {"event_id": "evt-2", "session_id": "sess-1"},
                    ],
                    texts=["Alice likes ramen", "She eats it weekly"],
                    summary={"event_count": 2, "session_id": "sess-1", "user_id": "u-1"},
                ),
                profile=ExtractionProfile(profile_id="chat.user_message"),
                focal_subject={"entity_ref": "user:self", "entity_type": "user"},
                context_bundle=None,
            )
        )
    started_extra = mock_info.call_args_list[0].kwargs
    llm_completed_extra = mock_info.call_args_list[1].kwargs
    completed_extra = mock_info.call_args_list[2].kwargs
    assert started_extra["session_id"] == "sess-1"
    assert started_extra["batch_event_count"] == 2
    assert llm_completed_extra["session_id"] == "sess-1"
    assert completed_extra["session_id"] == "sess-1"


def test_llm_call_completed_log_renders_duration(capsys):
    from magi.core.logger import configure_logging
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    configure_logging(level="INFO", json_logs=False)
    response = json.dumps(
        {
            "mentions": [],
            "graph_candidates": [],
            "assertion_candidates": [],
            "diagnostics": {"entity_status": "none"},
        }
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    asyncio.run(
        service.extract_unified_candidates(
            event_window=_make_event_window(event_ids=["evt-1"], texts=["hello"]),
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:self", "entity_type": "user"},
            context_bundle=None,
        )
    )

    captured = capsys.readouterr()
    assert "L2 LLM call completed" in captured.out
    assert "duration_ms=" in captured.out


@pytest.mark.asyncio
async def test_unified_extraction_publishes_usage_events_for_llm_stats(tmp_path: Path) -> None:
    from magi.events.memory_backend import MemoryMessageBackend
    from magi.llm.usage_events import LLMUsageEventPublisher
    from magi.llm.usage_store import LLMUsageStore
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    message_bus = MemoryMessageBackend()
    await message_bus.start()
    usage_store = LLMUsageStore(db_path=tmp_path / "llm_usage.db")
    await usage_store.start(message_bus)
    try:
        publisher = LLMUsageEventPublisher(message_bus)
        adapter = _FakeAdapter(
            json.dumps(
                {
                    "mentions": [],
                    "graph_candidates": [],
                    "assertion_candidates": [],
                    "diagnostics": {"entity_status": "none"},
                }
            ),
            provider_name="openai",
            model_name="gpt-4.1-mini",
            usage=(18, 6, 24),
            usage_publisher=publisher,
        )
        service = L2LLMService(_FakeScenarioPool(adapter))

        await service.extract_unified_candidates(
            event_window=_make_event_window(event_ids=["evt-usage-1"], texts=["hello"]),
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:self", "entity_type": "user"},
            context_bundle=None,
        )

        deadline = asyncio.get_running_loop().time() + 2.0
        summary = await usage_store.get_summary(days=1)
        while summary["totals"]["total_calls"] == 0 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
            summary = await usage_store.get_summary(days=1)

        assert summary["totals"]["total_calls"] == 1
        assert summary["totals"]["calls_with_usage"] == 1
        assert summary["totals"]["prompt_tokens"] == 18
        assert summary["totals"]["completion_tokens"] == 6
        assert summary["totals"]["total_tokens"] == 24
        assert summary["request_kinds"][0]["request_kind"] == "memory:l2_unified_extraction"
    finally:
        await usage_store.stop()
        await message_bus.stop()


def test_unified_extraction_retries_after_rate_limit() -> None:
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    adapter = _FakeAdapter(
        [
            RuntimeError("429 Too Many Requests"),
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
    service = L2LLMService(_FakeScenarioPool(adapter))

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with patch("magi.memory.l2.llm_service.asyncio.sleep", side_effect=_fake_sleep):
        result = asyncio.run(
            service.extract_unified_candidates(
                event_window=_make_event_window(event_ids=["evt-rate-limit-1"], texts=["hello"]),
                profile=ExtractionProfile(profile_id="chat.user_message"),
                focal_subject={"entity_ref": "user:self", "entity_type": "user"},
                context_bundle=None,
            )
        )

    assert result.diagnostics == {"entity_status": "none"}
    assert sleep_calls == [1.0]


def test_unified_extraction_returns_empty_after_retry_budget_exhausted() -> None:
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    adapter = _FakeAdapter(
        [
            RuntimeError("rate limit"),
            RuntimeError("429 Too Many Requests"),
            RuntimeError("RateLimitError"),
            RuntimeError("still rate limited"),
        ]
    )
    service = L2LLMService(_FakeScenarioPool(adapter))

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with patch("magi.memory.l2.llm_service.asyncio.sleep", side_effect=_fake_sleep):
        result = asyncio.run(
            service.extract_unified_candidates(
                event_window=_make_event_window(event_ids=["evt-rate-limit-2"], texts=["hello"]),
                profile=ExtractionProfile(profile_id="chat.user_message"),
                focal_subject={"entity_ref": "user:self", "entity_type": "user"},
                context_bundle=None,
            )
        )

    assert result.to_dict() == {
        "mentions": [],
        "resolved_context_refs": [],
        "graph_candidates": [],
        "assertion_candidates": [],
        "diagnostics": {"entity_status": "none"},
    }
    assert sleep_calls == [1.0, 2.0, 4.0]
