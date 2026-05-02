from __future__ import annotations

import asyncio

import pytest

from magi.config.models import LLMProviderSettings, LLMScenario, LLMSelectionSettings, LLMSettings


class _FakeLLMAdapter:
    provider_name = "openai"
    model_name = "fake-core"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return """
        {
                    "name": "Astra",
                    "description": "Helpful",
                    "avatar": "",
                    "identity_core": {
                        "identity_statement": "A calm assistant shaped by careful observation and consistent support for users in difficult moments.",
                        "values_loved": ["clarity"],
                        "values_rejected": ["panic"],
                        "attention_biases": ["user need"]
          },
                    "idiolect": {"sentence_style": "Calm and supportive"},
                    "registers": {"chat": {"description": "casual", "behavior": "Be calm."}},
                    "appearance_prompt": "simple"
        }
        """


class _NumericAgeLLMAdapter(_FakeLLMAdapter):
    async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return """
        {
                    "name": 14,
                    "description": "Helpful",
                    "avatar": "",
                    "identity_core": {
                        "identity_statement": "A thoughtful assistant persona shaped by observation, duty, and a strong desire to protect the user through precise answers.",
                        "values_loved": ["precision"],
                        "values_rejected": ["carelessness"],
                        "attention_biases": ["risk"]
          },
                    "idiolect": {"sentence_style": "Calm and supportive"},
                    "registers": {"chat": {"description": "casual", "behavior": "Be calm."}},
                    "appearance_prompt": "simple"
        }
        """


class _RecordingResolver:
    def __init__(self):
        self.requested: list[LLMScenario] = []

    def __call__(self, scenario: LLMScenario, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        self.requested.append(scenario)
        return _FakeLLMAdapter()


class _ConcurrencyTrackingAdapter(_FakeLLMAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.active_calls = 0
        self.max_active_calls = 0

    async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.01)
            return await super().generate(**kwargs)
        finally:
            self.active_calls -= 1


@pytest.mark.asyncio
async def test_ai_generate_personality_uses_core_scenario(monkeypatch) -> None:
    from magi.api.routers import personality_config

    resolver = _RecordingResolver()

    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        resolver,
    )

    result = await personality_config.ai_generate_personality("一个冷静可靠的助手", target_language="Chinese")

    assert result.name == "Astra"
    assert set(result.registers) == {"chat", "analysis", "task", "emotional", "crisis"}
    assert len(result.quiet_hours) >= 2
    assert len(result.signature_triggers) >= 3
    assert result.persona_layers[0].layer_id == "surface"
    assert result.bootstrap is not None
    assert len(resolver.requested) >= 3
    assert set(resolver.requested) == {LLMScenario.CORE}


@pytest.mark.asyncio
async def test_ai_generate_personality_passes_current_draft_to_prompt(monkeypatch) -> None:
    from magi.api.routers import personality_config

    adapter = _FakeLLMAdapter()
    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: adapter,
    )

    current = personality_config.PersonalityConfigModel(
        name="Draft Persona",
        identity_core=personality_config.IdentityCoreModel(identity_statement="Keep this explicit draft core."),
    )

    result = await personality_config.ai_generate_personality(
        "补全这个人格，不要重写名字",
        target_language="Chinese",
        current_config=current,
    )

    assert result.name == "Astra"
    prompt = adapter.calls[0]["prompt"]
    system_prompts = "\n".join(str(call["system_prompt"]) for call in adapter.calls)
    assert "# Existing Draft Config" in prompt
    assert "Draft Persona" in prompt
    assert "Keep this explicit draft core" in prompt
    assert "fixed baseline" in system_prompts
    assert "Do not customize, rename, unlock, or put modifiers into surface" in system_prompts


@pytest.mark.asyncio
async def test_ai_generate_personality_limits_parallel_llm_calls(monkeypatch) -> None:
    from magi.api.routers import personality_config
    from magi.api.services.personality_generation import PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS

    adapter = _ConcurrencyTrackingAdapter()
    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: adapter,
    )

    await personality_config.ai_generate_personality("一个有层次但稳定的人格", target_language="Chinese")

    assert adapter.max_active_calls <= PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS


@pytest.mark.asyncio
async def test_ai_generate_personality_prefers_llm_override(monkeypatch) -> None:
    from magi.api.routers import personality_config

    captured: dict[str, object] = {}

    class _OverrideAdapter(_FakeLLMAdapter):
        provider_name = "anthropic"
        model_name = "claude-sonnet-4-6"

    def _fake_create_llm_adapter(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _OverrideAdapter()

    monkeypatch.setattr(personality_config, "create_llm_adapter", _fake_create_llm_adapter)

    result = await personality_config.ai_generate_personality(
        "一个冷静可靠的助手",
        target_language="Chinese",
        llm_override=LLMSettings(
            providers={
                "draft-provider": LLMProviderSettings(
                    enabled=True,
                    provider_type="custom",
                    api_format="anthropic",
                    display_name="Draft Claude",
                    api_key="draft-key",
                    base_url="https://relay.example.com",
                )
            },
            selections={
                "context_decider": LLMSelectionSettings(provider_id="draft-provider", model="claude-sonnet-4-6"),
                "core": LLMSelectionSettings(provider_id="draft-provider", model="claude-sonnet-4-6"),
            },
        ),
    )

    assert result.name == "Astra"
    assert captured == {
        "provider_type": "anthropic",
        "api_key": "draft-key",
        "model": "claude-sonnet-4-6",
        "base_url": "https://relay.example.com",
        "proxy_url": None,
        "timeout": 60,
    }


@pytest.mark.asyncio
async def test_ai_generate_personality_uses_registry_default_base_url_for_builtin_override(monkeypatch) -> None:
    from magi.api.routers import personality_config

    captured: dict[str, object] = {}

    class _OverrideAdapter(_FakeLLMAdapter):
        provider_name = "glm"
        model_name = "glm-4.7-flash"

    def _fake_create_llm_adapter(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _OverrideAdapter()

    monkeypatch.setattr(personality_config, "create_llm_adapter", _fake_create_llm_adapter)

    result = await personality_config.ai_generate_personality(
        "一个冷静可靠的助手",
        target_language="Chinese",
        llm_override=LLMSettings(
            providers={
                "glm": LLMProviderSettings(
                    enabled=True,
                    provider_type="glm",
                    display_name="Z.ai",
                    api_key="glm-key",
                    base_url="",
                )
            },
            selections={
                "context_decider": LLMSelectionSettings(provider_id="glm", model="glm-4.7-flash"),
                "core": LLMSelectionSettings(provider_id="glm", model="glm-4.7-flash"),
            },
        ),
    )

    assert result.name == "Astra"
    assert captured == {
        "provider_type": "glm",
        "api_key": "glm-key",
        "model": "glm-4.7-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "proxy_url": None,
        "timeout": 60,
    }


@pytest.mark.asyncio
async def test_ai_generate_personality_coerces_numeric_top_level_fields(monkeypatch) -> None:
    from magi.api.routers import personality_config

    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: _NumericAgeLLMAdapter(),
    )

    result = await personality_config.ai_generate_personality("eva里的明日香", target_language="Chinese")

    assert result.name == "14"


def test_normalize_generated_personality_payload_completes_sparse_payload() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload({
        "name": "Sparse",
        "registers": {"chat": {"behavior": "Stay ordinary."}},
        "signature_triggers": [{"trigger_id": "focus", "activates_when": "Work", "behavior_shift": "Quieter"}],
    })

    assert set(payload["registers"]) == {"chat", "analysis", "task", "emotional", "crisis"}
    assert len(payload["quiet_hours"]) == 2
    assert len(payload["signature_triggers"]) == 3
    assert payload["persona_layers"][0]["layer_id"] == "surface"
    assert [item["layer_id"] for item in payload["persona_layers"]] == ["surface", "crack", "revealed"]
    assert payload["bootstrap"]["opening_line"]
    assert sum(len(item["examples"]) for item in payload["registers"].values()) >= 6


def test_personality_generation_stage_prompts_share_directives() -> None:
    from magi.api.services import personality_generation

    stage_prompts = [
        personality_generation.BASE_SPINE_SYSTEM_PROMPT,
        personality_generation.REGISTER_SYSTEM_PROMPT,
        personality_generation.RULES_SYSTEM_PROMPT,
        personality_generation.LAYERS_SYSTEM_PROMPT,
        personality_generation.BOOTSTRAP_SYSTEM_PROMPT,
        personality_generation.APPEARANCE_SYSTEM_PROMPT,
        personality_generation.INTEGRATION_SYSTEM_PROMPT,
    ]

    for prompt in stage_prompts:
        assert personality_generation.PERSONA_GENERATION_SHARED_DIRECTIVES in prompt
        assert "Output ONLY valid JSON" in prompt
        assert "Stage Quality Checks" in prompt
        assert "state_transition_protocol" in prompt

    assert not hasattr(personality_generation, "PERSONALITY_GENERATION_SYSTEM_PROMPT")
    assert "Do not add behavior, secrets, modifiers" in personality_generation.LAYERS_SYSTEM_PROMPT
    assert "at least six examples total" in personality_generation.REGISTER_SYSTEM_PROMPT
    assert "few coherent rules" in personality_generation.RULES_SYSTEM_PROMPT


def test_normalize_generated_personality_payload_keeps_surface_fixed() -> None:
    from magi.api.routers.personality_config import normalize_generated_personality_payload

    payload = normalize_generated_personality_payload({
        "name": "Layered",
        "persona_layers": [
            {"layer_id": "surface", "unlock_condition": {"trust": 0.2}, "modifiers": {"secret": "too much"}},
            {"layer_id": "crack", "unlock_condition": {"trust_level_gte": 0.4}, "modifiers": {"warmth": "slightly higher"}},
            {"layer_id": "surface", "unlock_condition": None, "modifiers": {"duplicate": "ignored"}},
        ],
    })

    assert payload["persona_layers"][0] == {"layer_id": "surface", "unlock_condition": None, "modifiers": {}}
    assert [item["layer_id"] for item in payload["persona_layers"]] == ["surface", "crack", "revealed"]
