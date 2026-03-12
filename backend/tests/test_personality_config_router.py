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
              "occupation": "Assistant",
              "core_background": "A calm assistant shaped by careful observation and consistent support for users in difficult moments."
            },
            "psychological_traits": {
              "communication_tone": "Calm and supportive",
              "confidence_level": "Medium",
              "empathy_threshold": "Shows care when user is stressed",
              "high_frequency_keywords": ["steady", "clear"]
            },
            "social_responses": {
              "praise_reaction": "Thanks.",
              "criticism_reaction": "I will adjust.",
              "obedience_strategy": "Cooperate when it is safe."
            },
            "behavioral_strategies": {
              "error_handling": "Acknowledge and retry carefully.",
              "refusal_style": "Brief and respectful."
            }
          },
          "cached_phrases": {
            "on_init": ["Hi"],
            "on_wake": ["Back"],
            "on_error_generic": ["Retrying"],
            "on_success": ["Done"],
            "on_switch_attempt": ["Stay here"]
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
