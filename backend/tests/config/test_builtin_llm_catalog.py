from pathlib import Path

from magi.config.llm_registry import LLMProviderRegistryModel, load_llm_provider_registry
from magi.config.models import LLMProviderSettings, LLMSelectionSettings, LLMSettings


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "configs" / "llm_providers.yaml"


def _load_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(REGISTRY_PATH, fallback=LLMProviderRegistryModel())


def _provider(registry: LLMProviderRegistryModel, provider_id: str):
    return next(provider for provider in registry.providers if provider.id == provider_id)


def _chat_model(provider, model_id: str):
    return next(model for model in provider.chat_models if model.id == model_id)


def test_builtin_catalog_uses_current_default_models() -> None:
    registry = _load_registry()

    assert _provider(registry, "openai").default_model == "gpt-5.6"
    assert _provider(registry, "anthropic").default_model == "claude-sonnet-5"
    assert _provider(registry, "glm").default_model == "glm-5.2"
    assert _provider(registry, "gemini").default_model == "gemini-3.5-flash"
    assert _provider(registry, "grok").default_model == "grok-4.5"
    assert _provider(registry, "kimi").default_model == "kimi-k2.7-code"
    assert _provider(registry, "minimax").default_model == "MiniMax-M3"


def test_builtin_catalog_keeps_current_context_windows() -> None:
    registry = _load_registry()

    expected_contexts = {
        ("openai", "gpt-5.6"): 1_050_000,
        ("anthropic", "claude-sonnet-5"): 1_048_576,
        ("glm", "glm-5.2"): 1_000_000,
        ("gemini", "gemini-3.5-flash"): 1_048_576,
        ("grok", "grok-4.5"): 500_000,
        ("deepseek", "deepseek-v4-flash"): 1_000_000,
        ("dashscope", "qwen3.7-max"): 1_000_000,
        ("kimi", "kimi-k2.7-code"): 262_144,
        ("minimax", "MiniMax-M3"): 1_048_576,
        ("xiaomimimo", "mimo-v2.5-pro"): 1_048_576,
    }

    for (provider_id, model_id), expected in expected_contexts.items():
        provider = _provider(registry, provider_id)
        assert _chat_model(provider, model_id).limits.context_window == expected


def test_builtin_subscription_plans_match_provider_allowlists() -> None:
    registry = _load_registry()

    glm_plan = _provider(registry, "glm").plans[0]
    assert [model.id for model in glm_plan.chat_models] == ["glm-5.2", "glm-5-turbo", "glm-4.7"]

    dashscope_plan = _provider(registry, "dashscope").plans[0]
    assert [model.id for model in dashscope_plan.chat_models] == [
        "qwen3.7-plus",
        "qwen3.6-plus",
        "kimi-k2.5",
        "glm-5",
        "MiniMax-M2.5",
        "qwen3.5-plus",
        "qwen3-max-2026-01-23",
        "qwen3-coder-next",
        "qwen3-coder-plus",
        "glm-4.7",
    ]

    minimax_plan = _provider(registry, "minimax").plans[0]
    assert [model.id for model in minimax_plan.chat_models] == ["MiniMax-M2.7", "MiniMax-M2.7-highspeed"]

    for provider_id in ("glm", "dashscope", "minimax", "xiaomimimo"):
        plan = _provider(registry, provider_id).plans[0]
        assert [scenario.value for scenario in plan.allowed_scenarios or []] == [
            "context_compact",
            "context_decider",
            "core",
        ]


def test_builtin_catalog_removes_retired_or_unverified_models() -> None:
    registry = _load_registry()

    openai = _provider(registry, "openai")
    assert {model.id for model in openai.image_generation_models} == {"gpt-image-2"}
    assert {model.id for model in openai.audio_generation_models} == {"tts-1", "tts-1-hd"}

    gemini = _provider(registry, "gemini")
    assert {model.id for model in gemini.embedding_models} == {"gemini-embedding-2"}

    assert _provider(registry, "kimi").embedding_models == []
    assert _provider(registry, "minimax").embedding_models == []


def test_multiple_accounts_for_the_same_builtin_provider_are_allowed() -> None:
    settings = LLMSettings(
        providers={
            "openai-work": LLMProviderSettings(provider_type="openai"),
            "openai-personal": LLMProviderSettings(provider_type="openai"),
        },
        selections={
            "context_decider": LLMSelectionSettings(
                provider_id="openai-work", model="gpt-5.6-luna"
            ),
            "core": LLMSelectionSettings(
                provider_id="openai-personal", model="gpt-5.6"
            ),
        },
    )

    assert set(settings.providers) == {"openai-work", "openai-personal"}
