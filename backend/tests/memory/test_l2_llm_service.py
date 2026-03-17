from __future__ import annotations

import json


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

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return self.adapter


def test_unified_prompt_only_includes_profile_allowed_entity_types():
    from magi.memory.l2_extraction_profiles import ExtractionProfile
    from magi.memory.l2_llm_service import L2LLMService

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
    from magi.memory.l2_extraction_profiles import ExtractionProfile
    from magi.memory.l2_llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("{}")))
    profile = ExtractionProfile(profile_id="chat.user_message")

    prompt = service.render_unified_extraction_prompt(
        event_window={"event_ids": ["evt-1"], "texts": ["I hate West Lake vinegar fish"]},
        profile=profile,
        focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
    )

    assert "Specific dishes, drinks, snacks, and ingredients must use `food`." in prompt
    assert '"entity_status": "found|none"' in prompt


def test_unified_extraction_parses_mentions_graph_and_assertions():
    from magi.memory.l2_extraction_profiles import ExtractionProfile
    from magi.memory.l2_llm_service import L2LLMService

    response = json.dumps(
        {
            "mentions": [{"mention_text": "西湖醋鱼", "entity_type": "dish"}],
            "graph_candidates": [{"predicate": "DISLIKES", "object_type": "dish"}],
            "assertion_candidates": [{"trait_family": "taste_profile", "confidence": 0.8}],
            "diagnostics": {"entity_status": "found"},
        },
        ensure_ascii=False,
    )
    service = L2LLMService(_FakeScenarioPool(_FakeAdapter(response)))

    result = __import__("asyncio").run(
        service.extract_unified_candidates(
            event_window={"event_ids": ["evt-1"], "texts": ["但我讨厌吃西湖醋鱼"]},
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )
    )

    assert result["mentions"] == [{"mention_text": "西湖醋鱼", "entity_type": "dish"}]
    assert result["graph_candidates"] == [{"predicate": "DISLIKES", "object_type": "dish"}]
    assert result["assertion_candidates"][0]["trait_family"] == "taste_profile"
    assert result["assertion_candidates"][0]["confidence"] == 0.3
    assert result["diagnostics"] == {"entity_status": "found"}


def test_unified_extraction_fails_closed_on_invalid_json():
    from magi.memory.l2_extraction_profiles import ExtractionProfile
    from magi.memory.l2_llm_service import L2LLMService

    service = L2LLMService(_FakeScenarioPool(_FakeAdapter("not-json")))

    result = __import__("asyncio").run(
        service.extract_unified_candidates(
            event_window={"event_ids": ["evt-1"], "texts": ["hello"]},
            profile=ExtractionProfile(profile_id="chat.user_message"),
            focal_subject={"entity_ref": "user:u1", "entity_type": "user"},
        )
    )

    assert result == {
        "mentions": [],
        "graph_candidates": [],
        "assertion_candidates": [],
        "diagnostics": {"entity_status": "none"},
    }
