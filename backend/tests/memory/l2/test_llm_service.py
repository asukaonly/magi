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
        response: str,
        *,
        provider_name: str = "openai",
        model_name: str = "gpt-test",
        usage: tuple[int, int, int] | None = None,
        usage_publisher: _FakeUsagePublisher | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
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


class _FakeScenarioPool:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self.adapter = adapter

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return self.adapter


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
        event_window={"event_ids": ["evt-1"], "texts": ["Visited GitHub"]},
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
        event_window={"event_ids": ["evt-1"], "texts": ["I hate West Lake vinegar fish"]},
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
        event_window={"event_ids": ["evt-1"], "texts": ["我真的很烦这种天气耶"]},
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


def test_unified_extraction_parses_mentions_graph_and_assertions():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

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
            event_window={"event_ids": ["evt-1"], "texts": ["但我讨厌吃西湖醋鱼"]},
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
            context_bundle=None,
        )
    )

    assert result["mentions"] == [{"mention_text": "西湖醋鱼", "entity_type": "dish"}]
    assert result["resolved_context_refs"] == [{"surface": "我", "reference_type": "self_actor", "resolved_ref": "user:self"}]
    assert result["graph_candidates"] == [{"predicate": "DISLIKES", "object_type": "dish"}]
    assert result["assertion_candidates"][0]["trait_family"] == "taste_profile"
    assert result["assertion_candidates"][0]["confidence"] == 0.3
    assert result["diagnostics"] == {"entity_status": "found"}


def test_unified_extraction_fails_closed_on_invalid_json():
    from magi.memory.l2.extraction_profiles import ExtractionProfile
    from magi.memory.l2.llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("not-json")))

    result = asyncio.run(
        service.extract_unified_candidates(
            event_window={"event_ids": ["evt-1"], "texts": ["hello"]},
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
            context_bundle=None,
        )
    )

    assert result == {
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
                event_window={"event_ids": ["evt-1"], "texts": ["I like Rust"]},
                profile=ExtractionProfile(profile_id="chat.user_message"),
                focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
                context_bundle=None,
            )
        )

    assert result["diagnostics"] == {"entity_status": "found"}
    assert [call.args[0] for call in mock_info.call_args_list] == [
        "L2 unified extraction started",
        "L2 LLM call started",
        "L2 LLM call completed",
        "L2 unified extraction completed",
    ]
    extras = mock_info.call_args_list[3].kwargs["extra"]
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
                event_window={"event_ids": ["evt-1"], "texts": ["hello"]},
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
        "L2 LLM call started",
        "L2 LLM call completed",
        "L2 unified extraction completed",
    ]
    started_extra = mock_info.call_args_list[0].kwargs["extra"]
    llm_started_extra = mock_info.call_args_list[1].kwargs["extra"]
    llm_completed_extra = mock_info.call_args_list[2].kwargs["extra"]
    completed_extra = mock_info.call_args_list[3].kwargs["extra"]
    assert started_extra["event_ids"] == ["evt-1"]
    assert started_extra["profile_id"] == "chat.user_message"
    assert llm_started_extra["request_kind"] == "memory:l2_unified_extraction"
    assert llm_started_extra["provider"] == "glm"
    assert llm_started_extra["model"] == "glm-4.5"
    assert llm_completed_extra["request_kind"] == "memory:l2_unified_extraction"
    assert llm_completed_extra["usage_available"] is True
    assert llm_completed_extra["prompt_tokens"] == 21
    assert llm_completed_extra["completion_tokens"] == 9
    assert llm_completed_extra["total_tokens"] == 30
    assert completed_extra["event_ids"] == ["evt-1"]
    assert completed_extra["profile_id"] == "chat.user_message"


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
            event_window={"event_ids": ["evt-usage-1"], "texts": ["hello"]},
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
