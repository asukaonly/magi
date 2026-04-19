from __future__ import annotations

import pytest

from magi.config.models import LLMProviderSettings, LLMScenario, LLMSelectionSettings, LLMSettings


class _FakeLLMAdapter:
    provider_name = "openai"
    model_name = "fake-core"

    async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return """
        {
          "persona_entity": {
            "basic_profile": {
              "name": "Astra",
              "age": "Unknown",
              "gender": "Unknown",
              "description": "Helpful",
              "avatar": "",
              "occupation": "Assistant"
            },
            "core_identity": {
              "inner_narrative": "A calm assistant shaped by careful observation and consistent support for users in difficult moments.",
              "language_fingerprint": "Calm and supportive",
              "attention_bias": ""
            }
          },
          "appearance_prompt": "simple",
          "state_transition_protocol": [
            {"trigger_type": "crisis", "trigger_condition": "danger", "target_state_name": "Guardian", "behavior_shift": "protective"},
            {"trigger_type": "intimacy", "trigger_condition": "trust", "target_state_name": "Confidant", "behavior_shift": "gentle"},
            {"trigger_type": "hostility", "trigger_condition": "insult", "target_state_name": "Boundary", "behavior_shift": "firm"},
            {"trigger_type": "absurdity", "trigger_condition": "nonsense", "target_state_name": "Playful", "behavior_shift": "light"}
          ]
        }
        """


class _NumericAgeLLMAdapter(_FakeLLMAdapter):
    async def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return """
        {
          "persona_entity": {
            "basic_profile": {
              "name": "Asuka",
              "age": 14,
              "gender": "女",
              "description": "Helpful",
              "avatar": "",
              "occupation": "Student"
            },
            "core_identity": {
              "inner_narrative": "A thoughtful assistant persona shaped by observation, duty, and a strong desire to protect the user through precise answers.",
              "language_fingerprint": "Calm and supportive",
              "attention_bias": ""
            }
          },
          "appearance_prompt": "simple",
          "state_transition_protocol": [
            {"trigger_type": "crisis", "trigger_condition": "danger", "target_state_name": "Guardian", "behavior_shift": "protective"},
            {"trigger_type": "intimacy", "trigger_condition": "trust", "target_state_name": "Confidant", "behavior_shift": "gentle"},
            {"trigger_type": "hostility", "trigger_condition": "insult", "target_state_name": "Boundary", "behavior_shift": "firm"},
            {"trigger_type": "absurdity", "trigger_condition": "nonsense", "target_state_name": "Playful", "behavior_shift": "light"}
          ]
        }
        """


class _RecordingResolver:
    def __init__(self):
        self.requested: list[LLMScenario] = []

    def __call__(self, scenario: LLMScenario, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        self.requested.append(scenario)
        return _FakeLLMAdapter()


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

    assert result.persona_entity.basic_profile.name == "Astra"
    assert resolver.requested == [LLMScenario.CORE]


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

    assert result.persona_entity.basic_profile.name == "Astra"
    assert captured == {
        "provider_type": "anthropic",
        "api_key": "draft-key",
        "model": "claude-sonnet-4-6",
        "base_url": "https://relay.example.com",
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

    assert result.persona_entity.basic_profile.name == "Astra"
    assert captured == {
        "provider_type": "glm",
        "api_key": "glm-key",
        "model": "glm-4.7-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "timeout": 60,
    }


@pytest.mark.asyncio
async def test_ai_generate_personality_coerces_numeric_basic_profile_fields(monkeypatch) -> None:
    from magi.api.routers import personality_config

    monkeypatch.setattr(
        personality_config,
        "resolve_adapter_for_scenario",
        lambda *args, **kwargs: _NumericAgeLLMAdapter(),
    )

    result = await personality_config.ai_generate_personality("eva里的明日香", target_language="Chinese")

    assert result.persona_entity.basic_profile.name == "Asuka"
    assert result.persona_entity.basic_profile.age == "14"
